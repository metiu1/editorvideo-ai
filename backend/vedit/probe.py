"""Lettura metadati dei file sorgente via ffprobe."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import ffmpeg
from .model import AUDIO_EXTS, IMAGE_EXTS, VIDEO_EXTS, Media, new_id


def _fps(rate: str | None) -> float:
    if not rate or rate == "0/0":
        return 0.0
    try:
        if "/" in rate:
            n, d = rate.split("/")
            return float(n) / float(d) if float(d) else 0.0
        return float(rate)
    except ValueError:
        return 0.0


def kind_from_ext(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    return "video"


def probe_raw(path: str) -> dict:
    args = [
        ffmpeg.binary("ffprobe"), "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    return json.loads(ffmpeg.run(args, timeout=60).stdout or "{}")


def probe(path: str, media_id: str | None = None) -> Media:
    """Ritorna un Media popolato. Solleva FileNotFoundError se il file manca."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"file non trovato: {path}")

    data = probe_raw(str(p))
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    # La copertina di un mp3 e' uno stream video a tutti gli effetti: presa per
    # buona, il brano diventa un "video" 360x360 senza fotogrammi, finisce su
    # una traccia video e la striscia in timeline resta vuota. ffprobe la marca
    # con attached_pic, ed e' l'unico modo per distinguerla.
    def copertina(s: dict) -> bool:
        return bool(s.get("disposition", {}).get("attached_pic"))

    v = next((s for s in streams
              if s.get("codec_type") == "video" and not copertina(s)), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    kind = kind_from_ext(str(p))
    if v is None and a is not None:
        kind = "audio"
    elif v is not None and kind != "image":
        # un "video" senza durata e con 1 solo frame e' di fatto un'immagine
        if v.get("nb_frames") == "1" and not fmt.get("duration"):
            kind = "image"
        else:
            kind = "video"

    duration = 0.0
    if kind != "image":
        for src in (fmt.get("duration"), (v or {}).get("duration"), (a or {}).get("duration")):
            try:
                duration = float(src)
                if duration > 0:
                    break
            except (TypeError, ValueError):
                continue

    rot = 0
    for sd in (v or {}).get("side_data_list", []) or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"])) % 360
            except (TypeError, ValueError):
                rot = 0

    w = int((v or {}).get("width") or 0)
    h = int((v or {}).get("height") or 0)
    if rot in (90, 270, -90):  # ffmpeg applica gia' la rotazione ai filtri
        w, h = h, w

    return Media(
        id=media_id or new_id("m"),
        path=str(p.resolve()),
        kind=kind,
        duration=round(duration, 6),
        width=w,
        height=h,
        fps=round(_fps((v or {}).get("avg_frame_rate")) or _fps((v or {}).get("r_frame_rate")), 6),
        has_video=v is not None,
        has_audio=a is not None,
        sample_rate=int((a or {}).get("sample_rate") or 0),
        channels=int((a or {}).get("channels") or 0),
        name=p.name,
    )


def recorded_at(path: str) -> dict:
    """Quando e' stato girato, e con cosa.

    L'ordine cronologico di una cartella non si deduce dai nomi dei file:
    ``IMG_9987`` puo' essere di ieri e ``IMG_0001`` di stamattina. I tag del
    contenitore lo dicono; quando mancano resta la data del file, che e' una
    approssimazione onesta purche' dichiarata (``fonte``).
    """
    data = probe_raw(path)
    fmt_tags = {k.lower(): v for k, v in (data.get("format", {}).get("tags") or {}).items()}
    stream_tags: dict = {}
    for s in data.get("streams", []):
        for k, v in (s.get("tags") or {}).items():
            stream_tags.setdefault(k.lower(), v)

    quando = fonte = None
    for chiave in ("creation_time", "date", "com.apple.quicktime.creationdate",
                   "date_eng", "originaldatetime"):
        val = fmt_tags.get(chiave) or stream_tags.get(chiave)
        if val:
            quando, fonte = str(val), f"tag:{chiave}"
            break
    if quando is None:
        try:
            quando = datetime.fromtimestamp(Path(path).stat().st_mtime).isoformat(
                timespec="seconds")
            fonte = "file:mtime"
        except OSError:
            fonte = "sconosciuta"

    return {
        "quando": quando,
        "fonte": fonte,
        "camera": fmt_tags.get("make") or stream_tags.get("make"),
        "modello": fmt_tags.get("model") or stream_tags.get("model"),
        "timecode": fmt_tags.get("timecode") or stream_tags.get("timecode"),
    }


def sort_key(path: str) -> tuple:
    """Chiave di ordinamento cronologico, con il nome come spareggio."""
    info = recorded_at(path)
    quando = info.get("quando") or ""
    # le date ISO si ordinano bene da stringhe; la Z finale non disturba
    return (quando or "9999", Path(path).name.lower())


def loudness(path: str, start: float = 0.0, duration: float | None = None) -> dict:
    """Misura EBU R128 (primo passaggio di loudnorm)."""
    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin"]
    if start:
        args += ["-ss", str(start)]
    args += ["-i", str(path)]
    if duration:
        args += ["-t", str(duration)]
    args += ["-af", "loudnorm=print_format=json", "-f", "null", "-"]
    proc = ffmpeg.run(args, check=False, timeout=900)
    log = (proc.stderr or "") + (proc.stdout or "")
    start_idx = log.rfind("{")
    end_idx = log.rfind("}")
    if start_idx == -1 or end_idx == -1:
        raise RuntimeError("impossibile misurare il loudness:\n" + log[-800:])
    return json.loads(log[start_idx : end_idx + 1])
