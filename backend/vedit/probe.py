"""Lettura metadati dei file sorgente via ffprobe."""

from __future__ import annotations

import json
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

    v = next((s for s in streams if s.get("codec_type") == "video"), None)
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
