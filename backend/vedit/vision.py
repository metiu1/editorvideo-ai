"""Dove sta il soggetto nel fotogramma.

Senza queste coordinate l'editor lavora alla cieca: non puo' mettere una
maschera su un volto, non puo' tenere una persona al centro quando si passa a
9:16, non puo' evitare di coprire chi parla con il testo.

Il rilevamento e' YOLO (ultralytics, modello nano: piccolo e veloce), applicato
a fotogrammi campionati - non a tutti: a 2 campioni al secondo il soggetto non
sparisce, e il costo scende di dieci volte.

Le posizioni grezze **non** si usano mai direttamente: saltano di qualche pixel
a ogni fotogramma e l'inquadratura risulterebbe nervosa. Passano prima per
:func:`smooth`, che e' quello che distingue un reframe guardabile da uno che fa
venire il mal di mare.
"""

from __future__ import annotations

import subprocess
import urllib.request
from pathlib import Path

from . import ffmpeg, probe, proxy

MODEL_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/"
DEFAULT_MODEL = "yolo11n.pt"
SAMPLE_FPS = 2.0
CONF = 0.35
SMOOTH_WINDOW = 5          # campioni: a 2 fps sono 2.5 secondi di memoria


class VisionError(RuntimeError):
    pass


def model_path(name: str = DEFAULT_MODEL) -> str:
    """Percorso del modello nella cache, scaricandolo al primo uso."""
    dst = proxy.cache_dir("models") / name
    if dst.exists() and dst.stat().st_size > 0:
        return str(dst)
    tmp = dst.with_name("~" + name)
    try:
        urllib.request.urlretrieve(MODEL_URL + name, tmp)
        tmp.replace(dst)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise VisionError(f"impossibile scaricare il modello {name}: {e}") from e
    return str(dst)


def _frames(path: str, fps: float, width: int):
    """Fotogrammi campionati come array BGR (la convenzione che YOLO si aspetta)."""
    import numpy as np

    m = probe.probe(path)
    if not m.has_video:
        raise VisionError(f"{path} non ha video")
    h = max(2, int(width * (m.height or 9) / (m.width or 16)) // 2 * 2)
    proc = subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(path), "-an", "-sn",
        "-vf", f"fps={fps},scale={width}:{h},format=bgr24",
        "-f", "rawvideo", "-",
    ], capture_output=True, timeout=3600)
    raw = proc.stdout or b""
    size = width * h * 3
    n = len(raw) // size
    if n == 0:
        raise VisionError(f"nessun fotogramma leggibile in {path}")
    buf = np.frombuffer(raw[: n * size], dtype=np.uint8).reshape(n, h, width, 3)
    return buf, (m.width or width, m.height or h), (width, h)


def detect(path: str, classes: tuple[str, ...] = ("person",), fps: float = SAMPLE_FPS,
           conf: float = CONF, width: int = 480, model: str = DEFAULT_MODEL,
           max_frames: int = 900) -> dict:
    """Rilevamenti per fotogramma, in coordinate del video originale."""
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise VisionError("ultralytics non installato: pip install ultralytics") from e

    buf, (ow, oh), (pw, ph) = _frames(path, fps, width)
    if len(buf) > max_frames:
        buf = buf[:max_frames]
    net = YOLO(model_path(model))
    nomi = net.names
    voluti = {c.lower() for c in classes} if classes else None
    kx, ky = ow / pw, oh / ph

    out = []
    for i, frame in enumerate(buf):
        res = net.predict(frame, conf=conf, verbose=False)[0]
        box = []
        for b in res.boxes:
            etichetta = str(nomi[int(b.cls)]).lower()
            if voluti and etichetta not in voluti:
                continue
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            box.append({
                "classe": etichetta, "conf": round(float(b.conf), 3),
                "x": round(x1 * kx, 1), "y": round(y1 * ky, 1),
                "w": round((x2 - x1) * kx, 1), "h": round((y2 - y1) * ky, 1),
            })
        out.append({"t": round(i / fps, 3), "box": box})
    return {"fps": fps, "larghezza": ow, "altezza": oh, "fotogrammi": out,
            "classi": sorted({b["classe"] for f in out for b in f["box"]})}


# --------------------------------------------------------------------------
# dal rilevamento al movimento di camera
# --------------------------------------------------------------------------


def main_subject(frames: list[dict]) -> list[dict]:
    """Un solo soggetto per fotogramma: il piu' grande tra i piu' sicuri.

    Area per confidenza: un rilevamento incerto ma enorme di solito e' lo sfondo,
    uno sicuro e minuscolo e' un passante.
    """
    out = []
    for f in frames:
        if not f["box"]:
            out.append({"t": f["t"], "cx": None, "cy": None, "box": None})
            continue
        b = max(f["box"], key=lambda x: x["w"] * x["h"] * x["conf"])
        out.append({"t": f["t"], "cx": b["x"] + b["w"] / 2,
                    "cy": b["y"] + b["h"] / 2, "box": b})
    return out


def fill_gaps(track: list[dict]) -> list[dict]:
    """Riempie i fotogrammi senza rilevamento tenendo l'ultima posizione nota."""
    out = [dict(p) for p in track]
    ultimo = None
    for p in out:
        if p["cx"] is None:
            if ultimo is not None:
                p["cx"], p["cy"] = ultimo
        else:
            ultimo = (p["cx"], p["cy"])
    # i primi fotogrammi senza rilevamento prendono il primo valore utile
    primo = next((p for p in out if p["cx"] is not None), None)
    if primo:
        for p in out:
            if p["cx"] is None:
                p["cx"], p["cy"] = primo["cx"], primo["cy"]
    return out


def smooth(track: list[dict], window: int = SMOOTH_WINDOW) -> list[dict]:
    """Media mobile centrata: toglie il tremolio senza inseguire ogni scatto."""
    if window <= 1 or not track:
        return [dict(p) for p in track]
    out = []
    meta = window // 2
    for i, p in enumerate(track):
        a, b = max(0, i - meta), min(len(track), i + meta + 1)
        finestra = [q for q in track[a:b] if q["cx"] is not None]
        if not finestra or p["cx"] is None:
            out.append(dict(p))
            continue
        q = dict(p)
        q["cx"] = round(sum(x["cx"] for x in finestra) / len(finestra), 2)
        q["cy"] = round(sum(x["cy"] for x in finestra) / len(finestra), 2)
        out.append(q)
    return out


def reframe_keyframes(track: list[dict], src_w: int, src_h: int,
                      out_w: int, out_h: int) -> dict:
    """Scala e panoramica per tenere il soggetto al centro nel nuovo formato.

    ``scale`` copre il canvas di destinazione; ``x``/``y`` sono offset in pixel
    dal centro (la convenzione di Transform) e vengono limitati perche' non
    compaia mai il vuoto oltre il bordo dell'immagine.
    """
    scale = max(out_w / src_w, out_h / src_h)
    vis_w, vis_h = src_w * scale, src_h * scale
    max_x = max(0.0, (vis_w - out_w) / 2)
    max_y = max(0.0, (vis_h - out_h) / 2)

    kx, ky = [], []
    for p in track:
        if p["cx"] is None:
            continue
        dx = -(p["cx"] - src_w / 2) * scale
        dy = -(p["cy"] - src_h / 2) * scale
        kx.append({"t": p["t"], "v": round(max(-max_x, min(max_x, dx)), 1)})
        ky.append({"t": p["t"], "v": round(max(-max_y, min(max_y, dy)), 1)})
    return {"scale": round(scale, 4), "x": {"kf": kx}, "y": {"kf": ky},
            "limite_x": round(max_x, 1), "limite_y": round(max_y, 1)}


def mask_keyframes(track: list[dict], padding: float = 1.25) -> dict:
    """Riquadro che segue il soggetto: parametri pronti per mask_blur/mask_box."""
    utili = [p for p in track if p["box"]]
    if not utili:
        raise VisionError("nessun soggetto rilevato: niente da mascherare")
    w = max(p["box"]["w"] for p in utili) * padding
    h = max(p["box"]["h"] for p in utili) * padding
    kx = [{"t": p["t"], "v": round(p["cx"] - w / 2, 1)} for p in track if p["cx"] is not None]
    ky = [{"t": p["t"], "v": round(p["cy"] - h / 2, 1)} for p in track if p["cy"] is not None]
    return {"w": int(w), "h": int(h), "x": {"kf": kx}, "y": {"kf": ky}}


def follow(path: str, classes: tuple[str, ...] = ("person",), fps: float = SAMPLE_FPS,
           conf: float = CONF, window: int = SMOOTH_WINDOW, **kw) -> dict:
    """Rileva, sceglie il soggetto, riempie i buchi e leviga: la catena completa."""
    det = detect(path, classes, fps, conf, **kw)
    track = smooth(fill_gaps(main_subject(det["fotogrammi"])), window)
    visti = sum(1 for p in det["fotogrammi"] if p["box"])
    return {"larghezza": det["larghezza"], "altezza": det["altezza"],
            "fps": fps, "traccia": track,
            "copertura": round(visti / max(1, len(det["fotogrammi"])), 3),
            "classi": det["classi"]}
