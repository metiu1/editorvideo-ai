"""Server MCP: espone l'editor come strumenti per un agente.

Filosofia degli strumenti:
- pochi strumenti, ognuno con un compito chiaro;
- risposte compatte (l'agente non deve leggere l'intero progetto a ogni mossa);
- errori con messaggio utile, che dicono cosa era ammesso;
- ``preview_frame`` restituisce un'immagine vera, cosi' l'agente puo' *vedere*
  il risultato di un montaggio invece di indovinarlo.

Avvio: ``vedit-mcp`` (stdio).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import Image, MCPServer

from . import effects as fx
from . import ffmpeg, hw, probe, proxy, render
from .model import TRANSITIONS
from .store import EditError, Store

mcp = MCPServer(
    name="vedit",
    version="0.1.0",
    instructions=(
        "Editor video non lineare. Flusso tipico: project_create -> import_media -> "
        "add_clip/add_text -> modifiche (split, set_speed, add_effect, set_transform) -> "
        "preview_frame per controllare il fotogramma -> render. "
        "I tempi sono in secondi. Ogni parametro animabile accetta anche "
        "{'kf':[{'t':0,'v':0},{'t':2,'v':1,'ease':'ease_in_out'}]} dove t e' il tempo "
        "relativo all'inizio della clip. Usa project_info per lo stato della timeline."
    ),
)

_stores: dict[str, Store] = {}
_current: list[str | None] = [None]


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------


def _store(project: str | None = None) -> Store:
    if project:
        key = str(Path(project).resolve())
        if key not in _stores:
            _stores[key] = Store.open(key)
        _current[0] = key
        return _stores[key]
    if _current[0] is None:
        raise EditError("nessun progetto aperto: usa project_create o project_open")
    return _stores[_current[0]]


def _clip_view(c) -> dict:
    out = {"id": c.id, "type": c.type, "start": round(c.start, 3),
           "duration": round(c.duration, 3), "end": round(c.end, 3)}
    if c.type == "media":
        out["media"] = c.media
        out["in"] = round(c.in_, 3)
    if abs(c.speed - 1.0) > 1e-6:
        out["speed"] = c.speed
    return out


async def _off(fn, *args, **kwargs):
    """Esegue lavoro bloccante (ffmpeg) fuori dal loop asincrono."""
    return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


# --------------------------------------------------------------------------
# progetto
# --------------------------------------------------------------------------


@mcp.tool()
def project_create(path: str, name: str = "untitled", preset: str = "1080p",
                   width: int | None = None, height: int | None = None,
                   fps: float | None = None) -> dict:
    """Crea un progetto e lo rende quello corrente.

    preset: 1080p, 1080p60, 4k, 720p, vertical (9:16 per reel/short), vertical60, square.
    """
    s = Store.create(name=name, preset=preset, path=path, width=width, height=height, fps=fps)
    key = str(Path(s.path).resolve())
    _stores[key] = s
    _current[0] = key
    return {"path": s.path, "settings": s.summary()["settings"], "tracks": ["V1", "A1"]}


@mcp.tool()
def project_open(path: str) -> dict:
    """Apre un progetto esistente (.json) e lo rende quello corrente."""
    return _store(path).summary()


@mcp.tool()
def project_info(detail: str = "normal", project: str | None = None) -> dict:
    """Stato completo della timeline: media, tracce, clip, effetti, durata.

    detail='full' aggiunge transform e audio di ogni clip.
    """
    return _store(project).summary(detail)


@mcp.tool()
def project_save(path: str | None = None, project: str | None = None) -> dict:
    """Salva il progetto (di norma non serve: il salvataggio e' automatico)."""
    return {"saved": _store(project).save(path)}


@mcp.tool()
def project_settings(width: int | None = None, height: int | None = None, fps: float | None = None,
                     background: str | None = None, sample_rate: int | None = None,
                     project: str | None = None) -> dict:
    """Cambia risoluzione, fps, colore di sfondo o sample rate del progetto."""
    s = _store(project)
    st = s.set_settings(width=width, height=height, fps=fps, background=background,
                        sample_rate=sample_rate)
    return {"width": st.width, "height": st.height, "fps": st.fps, "background": st.background}


@mcp.tool()
def undo(project: str | None = None) -> dict:
    """Annulla l'ultima modifica."""
    return {"undone": _store(project).undo()}


@mcp.tool()
def redo(project: str | None = None) -> dict:
    """Ripete la modifica annullata."""
    return {"redone": _store(project).redo()}


# --------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------


@mcp.tool()
async def import_media(paths: list[str], project: str | None = None) -> list[dict]:
    """Importa file video/audio/immagine nel progetto leggendone i metadati."""
    s = _store(project)
    media = await _off(s.import_media, paths)
    return [{"id": m.id, "name": m.name, "kind": m.kind, "duration": m.duration,
             "resolution": f"{m.width}x{m.height}" if m.width else None,
             "fps": m.fps or None, "audio": m.has_audio} for m in media]


@mcp.tool()
async def analyze_media(path: str) -> dict:
    """Legge i metadati di un file senza importarlo nel progetto."""
    m = await _off(probe.probe, path)
    return {"kind": m.kind, "duration": m.duration, "width": m.width, "height": m.height,
            "fps": m.fps, "has_audio": m.has_audio, "sample_rate": m.sample_rate,
            "channels": m.channels, "path": m.path}


@mcp.tool()
async def build_proxies(height: int = 540, project: str | None = None) -> dict:
    """Genera i proxy a bassa risoluzione: rende preview e frame molto piu' rapidi."""
    s = _store(project)
    done = await _off(proxy.ensure, s.project, height)
    s.save()
    return {"generati": len(done), "altezza": height}


# --------------------------------------------------------------------------
# tracce
# --------------------------------------------------------------------------


@mcp.tool()
def add_track(kind: str = "video", name: str | None = None, project: str | None = None) -> dict:
    """Aggiunge una traccia. Le tracce video successive stanno sopra le precedenti."""
    t = _store(project).add_track(kind, name)
    return {"id": t.id, "kind": t.kind, "name": t.name}


@mcp.tool()
def set_track(track: str, hidden: bool | None = None, muted: bool | None = None,
              volume: Any = None, name: str | None = None, locked: bool | None = None,
              solo: bool | None = None, project: str | None = None) -> dict:
    """Stato di una traccia.

    hidden nasconde il video, muted la silenzia, solo isola (le altre tacciono),
    locked la protegge dalle modifiche, volume 0..N e' animabile.
    E' anche l'unico modo di sbloccare una traccia bloccata.
    """
    t = _store(project).set_track(track, hidden=hidden, muted=muted, volume=volume,
                                  name=name, locked=locked, solo=solo)
    return {"id": t.id, "hidden": t.hidden, "muted": t.muted, "solo": t.solo,
            "locked": t.locked, "volume": t.volume}


@mcp.tool()
def move_track(track: str, index: int, project: str | None = None) -> dict:
    """Cambia l'ordine di una traccia tra quelle dello stesso tipo.

    Per il video l'ordine e' la sovrapposizione: 0 sta sotto, l'ultimo sopra tutti.
    """
    order = _store(project).move_track(track, index)
    return {"ordine": order}


@mcp.tool()
def remove_track(track: str, project: str | None = None) -> dict:
    """Elimina una traccia e tutte le sue clip."""
    _store(project).remove_track(track)
    return {"rimossa": track}


# --------------------------------------------------------------------------
# clip
# --------------------------------------------------------------------------


@mcp.tool()
def add_clip(media: str, track: str | None = None, start: float | None = None,
             in_point: float = 0.0, duration: float | None = None,
             project: str | None = None) -> dict:
    """Mette un media in timeline.

    start=None accoda alla fine della traccia. in_point/duration ritagliano la
    sorgente; duration=None usa tutto il resto del media (5s per le immagini).
    """
    c = _store(project).add_clip(media, track, start, in_point, duration)
    return _clip_view(c)


@mcp.tool()
def add_text(text: str, start: float = 0.0, duration: float = 3.0, track: str | None = None,
             font_size: int = 64, color: str = "white", align: str = "center",
             box: bool = False, box_color: str = "black", box_opacity: float = 0.5,
             border_width: int = 0, font_file: str | None = None,
             project: str | None = None) -> dict:
    """Aggiunge un titolo/sottotitolo in sovrimpressione.

    Il testo sta su tutto il canvas: per spostarlo usa set_transform (x, y),
    per animarlo in entrata usa keyframe su opacity o y.
    """
    c = _store(project).add_text(
        text, track, start, duration, font_size=font_size, color=color, align=align,
        box=box, box_color=box_color, box_opacity=box_opacity,
        border_width=border_width, font_file=font_file,
    )
    return _clip_view(c)


@mcp.tool()
def add_color(color: str = "black", start: float = 0.0, duration: float = 2.0,
              track: str | None = None, project: str | None = None) -> dict:
    """Aggiunge una clip di colore pieno (stacco, fondale, schermata finale)."""
    return _clip_view(_store(project).add_color(color, track, start, duration))


@mcp.tool()
def split(clip: str, at: float, project: str | None = None) -> dict:
    """Taglia una clip in due nel punto ``at`` (tempo di timeline)."""
    a, b = _store(project).split_clip(clip, at)
    return {"prima": _clip_view(a), "dopo": _clip_view(b)}


@mcp.tool()
def trim(clip: str, in_point: float | None = None, out_point: float | None = None,
         duration: float | None = None, project: str | None = None) -> dict:
    """Cambia il punto di attacco/stacco nella sorgente o la durata in timeline."""
    return _clip_view(_store(project).trim_clip(clip, in_point, duration, out_point))


@mcp.tool()
def move(clip: str, start: float | None = None, track: str | None = None,
         project: str | None = None) -> dict:
    """Sposta una clip nel tempo e/o su un'altra traccia."""
    return _clip_view(_store(project).move_clip(clip, start, track))


@mcp.tool()
def delete(clip: str, ripple: bool = False, project: str | None = None) -> dict:
    """Elimina una clip. ripple=True chiude il buco spostando indietro le successive."""
    _store(project).remove_clip(clip, ripple)
    return {"eliminata": clip, "ripple": ripple}


@mcp.tool()
def set_speed(clip: str, speed: float, keep_duration: bool = False,
              reverse: bool | None = None, project: str | None = None) -> dict:
    """Cambia velocita' (2.0 = doppia, 0.5 = slow motion) ed eventualmente inverte.

    keep_duration=True mantiene la durata in timeline consumando piu'/meno sorgente.
    """
    s = _store(project)
    c = s.set_speed(clip, speed, keep_duration)
    if reverse is not None:
        c = s.set_reverse(clip, reverse)
    return _clip_view(c)


@mcp.tool()
def set_clip(clip: str, enabled: bool | None = None, fit: str | None = None,
             name: str | None = None, color: str | None = None,
             project: str | None = None) -> dict:
    """Proprieta' semplici: attiva/disattiva, adattamento al canvas, nome, colore.

    fit: contain (tutto visibile, bande), cover (riempie tagliando), stretch, none.
    """
    c = _store(project).set_clip(clip, enabled=enabled, fit=fit, name=name, color=color)
    return _clip_view(c)


@mcp.tool()
def set_text(clip: str, text: str | None = None, font_size: int | None = None,
             color: str | None = None, align: str | None = None, box: bool | None = None,
             box_color: str | None = None, box_opacity: float | None = None,
             border_width: int | None = None, border_color: str | None = None,
             font_file: str | None = None, project: str | None = None) -> dict:
    """Modifica il contenuto o lo stile di una clip di testo."""
    c = _store(project).set_text(
        clip, text=text, font_size=font_size, color=color, align=align, box=box,
        box_color=box_color, box_opacity=box_opacity, border_width=border_width,
        border_color=border_color, font_file=font_file)
    return {"id": c.id, "text": c.text.text, "font_size": c.text.font_size}


@mcp.tool()
def set_transform(clip: str, x: Any = None, y: Any = None, scale: Any = None,
                  rotation: Any = None, opacity: Any = None, project: str | None = None) -> dict:
    """Posizione, dimensione, rotazione e opacita' della clip sul canvas.

    x/y sono offset in pixel dal centro (y negativo = verso l'alto), scale 1.0 =
    dimensione naturale, rotation in gradi, opacity 0..1. Tutti animabili con
    keyframe. Esempio zoom lento: scale={"kf":[{"t":0,"v":1},{"t":5,"v":1.2}]}.
    """
    c = _store(project).set_transform(clip, x=x, y=y, scale=scale, rotation=rotation,
                                      opacity=opacity)
    return {"id": c.id, "transform": vars(c.transform)}


@mcp.tool()
def set_audio(clip: str, gain_db: Any = None, mute: bool | None = None,
              fade_in: float | None = None, fade_out: float | None = None,
              pan: float | None = None, project: str | None = None) -> dict:
    """Volume (dB, animabile), silenziamento, dissolvenze audio e panning (-1..1)."""
    c = _store(project).set_audio(clip, gain_db=gain_db, mute=mute, fade_in=fade_in,
                                  fade_out=fade_out, pan=pan)
    return {"id": c.id, "audio": vars(c.audio)}


@mcp.tool()
def set_fades(clip: str, fade_in: float | None = None, fade_out: float | None = None,
              audio: bool = True, project: str | None = None) -> dict:
    """Dissolvenza video in entrata/uscita (in secondi), audio incluso di default."""
    c = _store(project).set_fades(clip, fade_in, fade_out, audio)
    return {"id": c.id, "fade_in": c.fade_in, "fade_out": c.fade_out}


# --------------------------------------------------------------------------
# montaggio
# --------------------------------------------------------------------------


@mcp.tool()
def crossfade(clip_a: str, clip_b: str, duration: float = 1.0, type: str = "dissolve",
              project: str | None = None) -> dict:
    """Transizione tra due clip consecutive della stessa traccia.

    B viene avvicinata ad A di ``duration`` secondi e tutto cio' che segue si sposta.
    type: dissolve, wipe_left/right/up/down (tendina), slide_left/right/up/down
    (la clip esce di scena), iris (cerchio). L'audio incrocia sempre in dissolvenza.
    """
    return _store(project).crossfade(clip_a, clip_b, duration, type)


@mcp.tool()
def set_transition(clip: str, type: str = "dissolve", duration: float = 1.0,
                   project: str | None = None) -> dict:
    """Cambia la transizione in uscita di una clip senza spostare nulla.

    Usalo per modificare una transizione gia' creata con crossfade, o quando le
    clip si sovrappongono gia'. duration=0 la toglie.
    """
    return _store(project).set_transition(clip, type, duration)


@mcp.tool()
def list_transitions() -> list[str]:
    """Tipi di transizione disponibili."""
    return list(TRANSITIONS)


@mcp.tool()
def append_sequence(media: list[str], track: str | None = None, crossfade: float = 0.0,
                    project: str | None = None) -> list[dict]:
    """Accoda piu' media in fila, con dissolvenza incrociata opzionale tra loro."""
    return [_clip_view(c) for c in _store(project).append_sequence(media, track, crossfade)]


@mcp.tool()
def close_gaps(track: str, project: str | None = None) -> dict:
    """Compatta la traccia eliminando i buchi tra le clip."""
    return {"clip_spostate": _store(project).close_gaps(track)}


# --------------------------------------------------------------------------
# effetti
# --------------------------------------------------------------------------


@mcp.tool()
def list_effects(kind: str | None = None) -> list[dict]:
    """Catalogo degli effetti disponibili con parametri, range e animabilita'.

    kind='video' o 'audio' per filtrare. Consultalo prima di usare add_effect.
    """
    return fx.describe(kind)


@mcp.tool()
def add_effect(type: str, clip: str | None = None, params: dict | None = None,
               project: str | None = None) -> dict:
    """Applica un effetto a una clip (clip=None lo applica al master).

    I parametri sono validati contro il catalogo: vedi list_effects.
    """
    e = _store(project).add_effect(clip, type, params)
    lst = _store(project)._effect_list(clip)
    return {"clip": clip, "index": len(lst) - 1, "type": e.type, "params": e.params}


@mcp.tool()
def update_effect(index: int, clip: str | None = None, params: dict | None = None,
                  enabled: bool | None = None, project: str | None = None) -> dict:
    """Modifica i parametri di un effetto gia' applicato (index da project_info)."""
    e = _store(project).update_effect(clip, index, params, enabled)
    return {"clip": clip, "index": index, "type": e.type, "params": e.params, "enabled": e.enabled}


@mcp.tool()
def remove_effect(index: int, clip: str | None = None, project: str | None = None) -> dict:
    """Rimuove un effetto dalla clip (o dal master se clip=None)."""
    _store(project).remove_effect(clip, index)
    return {"rimosso": index, "clip": clip}


# --------------------------------------------------------------------------
# audio master
# --------------------------------------------------------------------------


@mcp.tool()
async def normalize_audio(target_lufs: float = -14.0, measure: bool = True,
                          true_peak: float = -1.0, project: str | None = None) -> dict:
    """Normalizza il volume complessivo allo standard EBU R128.

    -14 LUFS = YouTube/Spotify, -16 = podcast, -23 = broadcast TV.
    measure=True fa il primo passaggio di analisi sul mix (piu' lento ma preciso:
    normalizzazione lineare senza pompaggio).
    """
    s = _store(project)
    measured = None
    if measure:
        measured = await _off(render.measure_loudness, s.project)
    return s.set_loudnorm(True, target_lufs, true_peak, measured=measured)


@mcp.tool()
async def audio_levels(clip: str | None = None, project: str | None = None) -> dict:
    """Misura il livello (LUFS integrato, true peak, range) del mix o di una clip."""
    s = _store(project)
    if clip is None:
        data = await _off(render.measure_loudness, s.project)
    else:
        _, c = s.clip_or_die(clip)
        m = s.media_or_die(c.media or "")
        data = await _off(probe.loudness, m.path, c.in_, c.source_duration())
    return {"lufs": float(data.get("input_i", 0)), "true_peak_db": float(data.get("input_tp", 0)),
            "lra": float(data.get("input_lra", 0)), "soglia": float(data.get("input_thresh", 0))}


# --------------------------------------------------------------------------
# preview e render
# --------------------------------------------------------------------------


@mcp.tool()
async def preview_frame(t: float, width: int = 640, path: str | None = None,
                        project: str | None = None) -> Image:
    """Renderizza il fotogramma della timeline al tempo ``t`` e lo restituisce.

    E' il modo per *vedere* il montaggio: posizione degli overlay, testo,
    correzione colore, inquadratura. Usa build_proxies per renderlo piu' rapido.
    """
    s = _store(project)
    out = path or str(Path(tempfile.gettempdir()) / f"vedit_preview_{os.getpid()}.jpg")
    p = await _off(render.render_frame, s.project, t, out, width, True)
    return Image(path=p)


@mcp.tool()
async def render_video(output: str, quality: str = "high", codec: str = "h264",
                       start: float | None = None, end: float | None = None,
                       preview: bool = False, bitrate: str | None = None,
                       project: str | None = None) -> dict:
    """Renderizza il progetto in un file.

    quality: draft (velocissimo, per controllare) | medium | high | max.
    codec: h264 (compatibile) | hevc | av1 | vp9. Usa l'accelerazione GPU se c'e'.
    preview=True rende a 960px con i proxy: utile per una verifica rapida.
    start/end limitano la porzione di timeline da rendere.
    L'estensione decide il contenitore: .mp4 .mov .mkv .webm .gif .mp3 .wav .m4a.
    """
    s = _store(project)
    opts = render.RenderOptions(
        output=output, quality="draft" if preview else quality, codec=codec,
        start=start, end=end, bitrate=bitrate,
        width=960 if preview else None, use_proxy=preview,
    )
    res = await _off(render.render, s.project, opts)
    return {"output": res.output, "durata": res.duration, "secondi_impiegati": res.seconds,
            "encoder": res.encoder, "mb": round(res.size / 1e6, 2), "avvisi": res.warnings}


@mcp.tool()
async def system_info() -> dict:
    """Versione di ffmpeg, encoder hardware disponibili, cartella di cache."""
    info = await _off(hw.detect)
    return {"ffmpeg": ffmpeg.version(), "encoder": info.encoders,
            "hardware_verificato": info.working,
            "cache": str(proxy.cache_dir())}


@mcp.tool()
async def clear_cache(kind: str | None = None) -> dict:
    """Svuota la cache di proxy/miniature/stabilizzazione."""
    freed = await _off(proxy.clear, kind)
    return {"liberati_mb": round(freed / 1e6, 2)}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
