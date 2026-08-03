"""API REST/WebSocket per l'interfaccia web.

Le modifiche non hanno un endpoint ciascuno: passano tutte da ``/api/op/{nome}``
che chiama il metodo omonimo di ``Store``. Cosi' la UI e il server MCP usano
esattamente le stesse operazioni e non possono divergere.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from urllib.parse import quote

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import chat as chat_mod
from . import effects as fx
from . import ffmpeg, hw, presets, proxy, render
from .model import TRANSITIONS
from .store import PRESETS, EditError, Store

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"

# operazioni di editing esposte alla UI (nomi dei metodi di Store)
OPS = {
    "import_media", "set_media", "remove_media", "rename_folder",
    "add_track", "set_track", "remove_track", "move_track",
    "add_clip", "add_text", "add_color", "remove_clip", "move_clip", "trim_clip",
    "split_clip", "set_speed", "set_reverse", "set_transform", "set_audio",
    "set_fades", "set_clip", "set_text", "add_effect", "update_effect",
    "remove_effect", "append_sequence", "crossfade", "set_transition", "close_gaps",
    "set_loudnorm", "set_settings", "undo", "redo", "save",
}


class Session:
    """Progetto aperto + code di lavoro. Una sola sessione per processo."""

    def __init__(self) -> None:
        self.store: Store | None = None
        self.jobs: dict[str, dict] = {}
        self.listeners: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.lock = threading.RLock()
        # conversazione con l'assistente: contiene i blocchi tool_use/tool_result,
        # che i turni successivi devono rimandare intatti
        self.chat: list[dict] = []

    def need(self) -> Store:
        if self.store is None:
            raise HTTPException(400, "nessun progetto aperto")
        return self.store

    def publish(self, event: dict) -> None:
        """Notifica i client connessi (chiamabile anche da thread di lavoro)."""
        if self.loop is None:
            return
        for q in list(self.listeners):
            self.loop.call_soon_threadsafe(q.put_nowait, event)

    def revision(self) -> str:
        """Impronta del progetto: invalida le cache di anteprima quando cambia."""
        if self.store is None:
            return "0"
        blob = json.dumps(self.store.project.to_dict(), sort_keys=True).encode()
        return hashlib.sha1(blob).hexdigest()[:16]


S = Session()
app = FastAPI(title="vedit")


# --------------------------------------------------------------------------
# progetto
# --------------------------------------------------------------------------


class CreateBody(BaseModel):
    path: str
    name: str = "untitled"
    preset: str = "1080p"


class OpenBody(BaseModel):
    path: str


@app.get("/api/state")
def state() -> dict:
    info = hw.detect()
    return {
        "project": S.store.summary("full") if S.store else None,
        "path": S.store.path if S.store else None,
        "revision": S.revision(),
        "effects": fx.describe(),
        "transitions": list(TRANSITIONS),
        "library": presets.describe(),
        "presets": list(PRESETS),
        "chat": chat_available(),
        "system": {"ffmpeg": ffmpeg.version(), "encoders": info.encoders,
                   "hw": info.working},
    }


@app.post("/api/project/create")
def project_create(body: CreateBody) -> dict:
    S.store = Store.create(name=body.name, preset=body.preset, path=body.path)
    S.publish({"type": "project"})
    return {"path": S.store.path, "project": S.store.summary("full")}


@app.post("/api/project/open")
def project_open(body: OpenBody) -> dict:
    S.store = Store.open(body.path)
    S.publish({"type": "project"})
    return {"path": S.store.path, "project": S.store.summary("full")}


@app.post("/api/op/{name}")
def op(name: str, body: dict | None = None) -> dict:
    """Esegue un'operazione di editing e restituisce il progetto aggiornato."""
    if name not in OPS:
        raise HTTPException(404, f"operazione sconosciuta: {name}")
    store = S.need()
    args = dict(body or {})
    try:
        with S.lock:
            result = getattr(store, name)(**args)
    except TypeError as exc:
        raise HTTPException(400, f"argomenti non validi per {name}: {exc}") from exc
    except (EditError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc

    S.publish({"type": "project"})
    return {"result": _plain(result), "project": store.summary("full"),
            "revision": S.revision()}


def _plain(value: Any) -> Any:
    """Rende serializzabile qualunque cosa tornino i metodi di Store."""
    from dataclasses import is_dataclass

    from .model import to_dict

    if is_dataclass(value):
        return to_dict(value)
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------
# file system (dialogo di import)
# --------------------------------------------------------------------------


@app.get("/api/browse")
def browse(path: str | None = None) -> dict:
    from .model import AUDIO_EXTS, IMAGE_EXTS, VIDEO_EXTS

    # .json compreso: la stessa finestra serve per aprire i progetti
    known = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | {".json"}
    base = Path(path) if path else Path.home()
    if not base.exists():
        raise HTTPException(404, f"cartella inesistente: {base}")
    if base.is_file():
        base = base.parent

    dirs, files = [], []
    try:
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": str(entry)})
                elif entry.suffix.lower() in known:
                    files.append({"name": entry.name, "path": str(entry),
                                  "size": entry.stat().st_size})
            except OSError:
                continue
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc

    return {"path": str(base), "parent": str(base.parent) if base.parent != base else None,
            "dirs": dirs, "files": files}


@app.get("/api/media/{media_id}/waveform")
def waveform(media_id: str) -> dict:
    store = S.need()
    m = store.media_or_die(media_id)
    return {"peaks": proxy.waveform(m), "duration": m.duration}


@app.get("/api/media/{media_id}/strip")
def strip(media_id: str, height: int = 44) -> dict:
    """Striscia di fotogrammi usata come sfondo delle clip video in timeline."""
    store = S.need()
    m = store.media_or_die(media_id)
    info = proxy.filmstrip(m, height)
    if not info:
        return {}
    return {**info, "url": f"/api/file?path={quote(info['path'])}"}


@app.get("/api/media/{media_id}/stream")
def stream(media_id: str, request: Request):
    """Riproduce il file nel monitor sorgente: usa il proxy se disponibile."""
    store = S.need()
    m = store.media_or_die(media_id)
    src = m.proxy if (m.proxy and Path(m.proxy).exists()) else m.path
    p = Path(src)
    if not p.is_file():
        raise HTTPException(404, f"file non trovato: {src}")
    # FileResponse gestisce le richieste Range, indispensabili per il seek
    return FileResponse(p, media_type=mimetypes.guess_type(p.name)[0] or "video/mp4")


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), folder: str = Form("")) -> dict:
    """Riceve i file trascinati dal desktop.

    Il browser non passa il percorso di origine, quindi qui il file viene
    copiato accanto al progetto. Per file grandi conviene il pulsante di import,
    che li referenzia dove sono senza duplicarli.
    """
    store = S.need()
    if not store.path:
        raise HTTPException(400, "salva il progetto prima di trascinarci dentro dei file")
    dest_dir = Path(store.path).parent / "media"
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for f in files:
        name = Path(f.filename or "file").name
        target = dest_dir / name
        i = 1
        while target.exists():
            target = dest_dir / f"{Path(name).stem}_{i}{Path(name).suffix}"
            i += 1
        with target.open("wb") as out:
            while chunk := await f.read(1 << 20):
                out.write(chunk)
        saved.append(str(target))

    with S.lock:
        media = store.import_media(saved)
        if folder:
            for m in media:
                store.set_media(m.id, folder=folder)
    S.publish({"type": "project"})
    return {"importati": [m.id for m in media], "project": store.summary("full"),
            "revision": S.revision()}


@app.get("/api/file")
def raw_file(path: str):
    p = Path(path)
    if not p.is_file():
        raise HTTPException(404, "file inesistente")
    return FileResponse(p, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream")


# --------------------------------------------------------------------------
# anteprima
# --------------------------------------------------------------------------


def _preview_dir() -> Path:
    return proxy.cache_dir("preview")


# Un lock per chiave di cache: due richieste sullo stesso segmento non lo
# renderizzano due volte, la seconda aspetta ed usa il file della prima.
_render_locks: dict[str, threading.Lock] = {}
_render_guard = threading.Lock()


def _key_lock(key: str) -> threading.Lock:
    with _render_guard:
        if len(_render_locks) > 256:
            # le chiavi contengono la revisione: quelle vecchie non servono piu'
            for k, lock in list(_render_locks.items()):
                if not lock.locked():
                    del _render_locks[k]
        return _render_locks.setdefault(key, threading.Lock())


def _ready(path: Path) -> bool:
    """Vero solo se il file e' completo: quelli in corso di scrittura non contano."""
    try:
        return path.stat().st_size > 0
    except OSError:
        return False


def _temp_beside(out: Path) -> Path:
    """Nome temporaneo con la stessa estensione: ffmpeg sceglie il formato da li'."""
    return out.with_name(f"~{uuid.uuid4().hex[:8]}_{out.name}")


def _produce(out: Path, make) -> None:
    """Renderizza in un file temporaneo e lo sposta a destinazione solo a fine lavoro.

    Senza questo passaggio la cache espone il file mentre ffmpeg lo sta ancora
    scrivendo: il player riceve un mp4 senza atomo ``moov`` e la riproduzione
    non parte. ``os.replace`` e' atomico sullo stesso volume.
    """
    tmp = _temp_beside(out)
    try:
        with S.lock:
            make(tmp)
        os.replace(tmp, out)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


@app.get("/api/frame")
def frame(t: float = 0.0, width: int = 960):
    """Fotogramma della timeline: e' l'anteprima usata durante lo scrub."""
    store = S.need()
    if store.project.duration() <= 0:
        raise HTTPException(400, "timeline vuota")
    key = f"f_{S.revision()}_{t:.3f}_{width}"
    out = _preview_dir() / f"{key}.jpg"
    if not _ready(out):
        with _key_lock(key):
            if not _ready(out):
                try:
                    _produce(out, lambda tmp: render.render_frame(
                        store.project, t, str(tmp), width, use_proxy=True))
                except Exception as exc:
                    raise HTTPException(500, f"anteprima fallita: {exc}") from exc
    return FileResponse(out, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


def _segment(start: float, duration: float, height: int) -> tuple[Path, float, float]:
    """Percorso in cache del segmento; lo renderizza se manca."""
    store = S.need()
    total = store.project.duration()
    if total <= 0:
        raise HTTPException(400, "timeline vuota")
    start = max(0.0, min(start, max(0.0, total - 0.05)))
    duration = max(0.2, min(duration, total - start))

    key = f"p_{S.revision()}_{start:.3f}_{duration:.3f}_{height}"
    out = _preview_dir() / f"{key}.mp4"
    if _ready(out):
        return out, start, duration

    w = int(store.project.settings.width * height / max(1, store.project.settings.height))
    w += w % 2

    def make(tmp: Path) -> None:
        render.render(store.project, render.RenderOptions(
            output=str(tmp), quality="draft", start=start, end=start + duration,
            width=w, height=height, use_proxy=True, audio_bitrate="128k",
        ))

    with _key_lock(key):
        # potrebbe averlo appena finito il prefetch mentre aspettavamo il lock
        if not _ready(out):
            try:
                _produce(out, make)
            except Exception as exc:
                raise HTTPException(500, f"anteprima fallita: {exc}") from exc
    return out, start, duration


@app.get("/api/preview")
def preview(start: float = 0.0, duration: float = 10.0, height: int = 540):
    """Segmento riprodotto dal player: renderizzato in bozza e messo in cache."""
    out, _, _ = _segment(start, duration, height)
    return FileResponse(out, media_type="video/mp4",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/preview/prefetch")
def preview_prefetch(start: float = 0.0, duration: float = 10.0, height: int = 540) -> dict:
    """Prepara un segmento in sottofondo, cosi' e' pronto quando servira'.

    Il player lo chiama per il pezzo successivo appena inizia a riprodurre:
    la riproduzione prosegue senza attesa al cambio di segmento.
    """
    S.need()
    total = S.store.project.duration()
    if start >= total - 0.05:
        return {"skip": True}

    def work() -> None:
        try:
            _segment(start, duration, height)
            S.publish({"type": "prefetch", "start": start, "state": "done"})
        except Exception:
            pass  # un prefetch fallito non e' un errore per l'utente

    threading.Thread(target=work, daemon=True, name="prefetch").start()
    return {"avviato": True, "start": start, "duration": duration}


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------


class RenderBody(BaseModel):
    output: str
    quality: str = "high"
    codec: str = "h264"
    bitrate: str | None = None
    start: float | None = None
    end: float | None = None


@app.post("/api/render")
def render_start(body: RenderBody) -> dict:
    store = S.need()
    job_id = uuid.uuid4().hex[:8]
    S.jobs[job_id] = {"id": job_id, "state": "running", "percent": 0.0,
                      "output": body.output, "started": time.time()}

    project = store.project

    def work() -> None:
        def on_progress(p: dict) -> None:
            S.jobs[job_id].update(percent=p["percent"], seconds=p["seconds"],
                                  duration=p["duration"], elapsed=p["elapsed"])
            S.publish({"type": "render", "job": S.jobs[job_id]})

        try:
            opts = render.RenderOptions(
                output=body.output, quality=body.quality, codec=body.codec,
                bitrate=body.bitrate, start=body.start, end=body.end,
            )
            res = render.render(project, opts, on_progress=on_progress)
            S.jobs[job_id].update(state="done", percent=100.0, output=res.output,
                                  mb=round(res.size / 1e6, 2), encoder=res.encoder,
                                  seconds_total=res.seconds, warnings=res.warnings)
        except Exception as exc:
            S.jobs[job_id].update(state="error", error=str(exc))
        S.publish({"type": "render", "job": S.jobs[job_id]})

    threading.Thread(target=work, daemon=True, name=f"render-{job_id}").start()
    return S.jobs[job_id]


@app.get("/api/render/{job_id}")
def render_status(job_id: str) -> dict:
    job = S.jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job inesistente")
    return job


@app.post("/api/proxies")
def build_proxies(height: int = 540) -> dict:
    store = S.need()

    def work() -> None:
        try:
            proxy.ensure(store.project, height)
            store.save()
            S.publish({"type": "proxies", "state": "done"})
        except Exception as exc:
            S.publish({"type": "proxies", "state": "error", "error": str(exc)})

    threading.Thread(target=work, daemon=True, name="proxies").start()
    return {"avviato": True}


@app.post("/api/loudness")
def loudness() -> dict:
    store = S.need()
    with S.lock:
        measured = render.measure_loudness(store.project)
    return {"lufs": float(measured.get("input_i", 0)),
            "true_peak": float(measured.get("input_tp", 0)),
            "lra": float(measured.get("input_lra", 0)),
            "measured": measured}


# --------------------------------------------------------------------------
# libreria preset
# --------------------------------------------------------------------------


class PresetBody(BaseModel):
    preset_id: str
    clip_id: str | None = None


@app.post("/api/preset/apply")
def preset_apply(body: PresetBody) -> dict:
    """Applica un preset in un colpo solo: un'unica voce di undo, non una per effetto."""
    store = S.need()
    p = presets.find(body.preset_id)
    if p is None:
        raise HTTPException(404, f"preset sconosciuto: {body.preset_id}")
    try:
        with S.lock:
            store.add_effects(body.clip_id, p["effects"])
    except (EditError, ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
    S.publish({"type": "project"})
    return {"applicato": p["name"], "effetti": len(p["effects"]),
            "project": store.summary("full"), "revision": S.revision()}


# --------------------------------------------------------------------------
# assistente
# --------------------------------------------------------------------------


class ChatBody(BaseModel):
    message: str


def chat_available() -> dict:
    """La UI mostra la chat solo se qui c'e' davvero una credenziale utilizzabile."""
    try:
        chat_mod.client()
    except chat_mod.ChatUnavailable as exc:
        return {"ok": False, "motivo": str(exc)}
    except Exception as exc:
        return {"ok": False, "motivo": str(exc)}
    return {"ok": True, "model": chat_mod.MODEL}


@app.post("/api/chat/reset")
def chat_reset() -> dict:
    S.chat.clear()
    return {"ok": True}


@app.post("/api/chat")
def chat(body: ChatBody) -> StreamingResponse:
    """Un turno con l'assistente, in streaming (SSE).

    Gli strumenti passano dagli stessi metodi di ``Store`` usati dalla UI, sotto
    lo stesso lock: una modifica dell'assistente e una tua non possono
    intrecciarsi a meta'.
    """
    store = S.need()

    def run_op(name: str, args: dict) -> str:
        with S.lock:
            out = chat_mod.execute(store, name, args)
        S.publish({"type": "project"})
        return out

    def events():
        def send(obj: dict) -> str:
            return f"data: {json.dumps(obj, ensure_ascii=False, default=str)}\n\n"

        try:
            for ev in chat_mod.run(store, S.chat, body.message, run_op):
                yield send(ev)
        except chat_mod.ChatUnavailable as exc:
            yield send({"type": "error", "message": str(exc)})
        except Exception as exc:
            yield send({"type": "error", "message": str(exc)})
        # il progetto e' cambiato: la UI ricarica lo stato completo
        yield send({"type": "end", "project": store.summary("full"),
                    "revision": S.revision()})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------
# websocket
# --------------------------------------------------------------------------


@app.websocket("/ws")
async def ws(sock: WebSocket) -> None:
    await sock.accept()
    S.loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    S.listeners.add(queue)
    try:
        await sock.send_json({"type": "hello", "revision": S.revision()})
        while True:
            event = await queue.get()
            await sock.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        S.listeners.discard(queue)


# --------------------------------------------------------------------------
# frontend
# --------------------------------------------------------------------------


@app.exception_handler(EditError)
def _edit_error(_request, exc: EditError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


def mount_frontend() -> None:
    if FRONTEND.is_dir():
        app.mount("/", StaticFiles(directory=str(FRONTEND), html=True), name="ui")
    else:
        @app.get("/")
        def _missing() -> dict:
            return {"errore": "interfaccia non compilata",
                    "come": "cd frontend && npm install && npm run build"}


def serve(host: str = "127.0.0.1", port: int = 8760, project: str | None = None,
          open_browser: bool = True) -> None:
    import uvicorn

    if project:
        S.store = Store.open(project)
    mount_frontend()

    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.0, lambda: __import__("webbrowser").open(url)).start()
    print(f"vedit su {url}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
