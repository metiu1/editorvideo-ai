"""Proxy a bassa risoluzione, forme d'onda e miniature.

Montare direttamente su file 4K o H.265 rende ogni preview lentissima. I proxy
sono H.264 all-intra a 540p: decodifica quasi istantanea e seek preciso su
qualsiasi frame. Il render finale usa sempre le sorgenti originali.
"""

from __future__ import annotations

import array
import hashlib
import os
from pathlib import Path

from . import ffmpeg, hw
from .model import Media, Project


def cache_dir(sub: str = "") -> Path:
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    p = base / sub if sub else base
    p.mkdir(parents=True, exist_ok=True)
    return p


def _key(path: str, tag: str) -> str:
    try:
        st = Path(path).stat()
        sig = f"{path}|{st.st_size}|{int(st.st_mtime)}|{tag}"
    except OSError:
        sig = f"{path}|{tag}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def proxy_path(media: Media, height: int = 540) -> Path:
    ext = ".m4a" if media.kind == "audio" else ".mp4"
    return cache_dir("proxy") / f"{_key(media.path, f'p{height}')}{ext}"


def generate(media: Media, height: int = 540, force: bool = False) -> str:
    """Crea il proxy se manca e ritorna il percorso."""
    if media.kind == "image":
        return media.path
    dst = proxy_path(media, height)
    if dst.exists() and not force and dst.stat().st_size > 0:
        return str(dst)

    args = ffmpeg.base_cmd() + ["-i", media.path]
    if media.kind == "audio" or not media.has_video:
        args += ["-vn", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
    else:
        info = hw.detect()
        enc = info.encoder_for("h264", prefer_hw=True)
        args += [
            "-vf", f"scale=-2:{height}:flags=fast_bilinear",
            *hw.encoder_args(enc, "draft"),
            "-g", "12", "-pix_fmt", "yuv420p",
        ]
        if media.has_audio:
            args += ["-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2"]
        else:
            args += ["-an"]
    args += [str(dst)]
    ffmpeg.run(args, timeout=7200)
    return str(dst)


def ensure(project: Project, height: int = 540, force: bool = False) -> dict:
    """Genera i proxy mancanti per tutti i media del progetto."""
    done = {}
    for m in project.media:
        if m.kind == "image":
            continue
        p = generate(m, height, force)
        m.proxy = p
        done[m.id] = p
    return done


def waveform(media: Media, points_per_second: int = 40, max_points: int = 40000) -> list[float]:
    """Picchi audio normalizzati 0..1, per disegnare la traccia in timeline."""
    if not media.has_audio:
        return []
    rate = 8000
    args = [
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-i", media.path, "-vn", "-ac", "1", "-ar", str(rate),
        "-f", "s16le", "-acodec", "pcm_s16le", "-",
    ]
    import subprocess

    proc = subprocess.run(args, capture_output=True, timeout=1800,
                          creationflags=0x08000000 if os.name == "nt" else 0)
    raw = proc.stdout
    if not raw:
        return []
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) - (len(raw) % 2)])

    total_points = min(max_points, max(1, int((len(samples) / rate) * points_per_second)))
    block = max(1, len(samples) // total_points)
    peaks = []
    for i in range(0, len(samples), block):
        chunk = samples[i : i + block]
        if not chunk:
            break
        peaks.append(round(max(abs(min(chunk)), abs(max(chunk))) / 32768.0, 4))
    return peaks


def thumbnails(media: Media, count: int = 10, height: int = 90) -> list[str]:
    """Strip di miniature per la traccia video."""
    if not media.has_video or media.duration <= 0:
        return []
    out_dir = cache_dir("thumbs") / _key(media.path, f"t{count}x{height}")
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(out_dir.glob("*.jpg"))
    if len(existing) >= count:
        return [str(p) for p in existing[:count]]

    step = media.duration / count
    paths = []
    for i in range(count):
        dst = out_dir / f"{i:04d}.jpg"
        if not dst.exists():
            args = ffmpeg.base_cmd() + [
                "-ss", f"{i * step:.3f}", "-i", media.path, "-frames:v", "1",
                "-vf", f"scale=-2:{height}", "-q:v", "5", str(dst),
            ]
            ffmpeg.run(args, check=False, timeout=120)
        if dst.exists():
            paths.append(str(dst))
    return paths


def filmstrip(media: Media, height: int = 44, max_tiles: int = 240) -> dict:
    """Striscia unica con un fotogramma ogni N secondi, per il fondo delle clip.

    Una sola immagine invece di decine di richieste: la timeline la usa come
    background-image e sposta la finestra in base al punto di attacco e allo zoom.
    """
    if not media.has_video or media.duration <= 0:
        return {}
    tiles = max(1, min(max_tiles, int(media.duration)))
    interval = media.duration / tiles
    tile_w = max(2, int(round(height * (media.width or 16) / (media.height or 9))))
    tile_w += tile_w % 2

    dst = cache_dir("strip") / f"{_key(media.path, f's{height}x{tiles}')}.jpg"
    if not dst.exists() or dst.stat().st_size == 0:
        src = media.proxy if media.proxy and Path(media.proxy).exists() else media.path
        args = ffmpeg.base_cmd() + [
            "-i", src,
            "-vf", f"fps=1/{interval:.6f},scale={tile_w}:{height},tile={tiles}x1",
            "-frames:v", "1", "-q:v", "6", str(dst),
        ]
        ffmpeg.run(args, timeout=1800, check=False)
        if not dst.exists():
            return {}
    return {"path": str(dst), "tiles": tiles, "interval": round(interval, 6),
            "tile_width": tile_w, "tile_height": height}


def clear(kind: str | None = None) -> int:
    """Svuota la cache (proxy/thumbs/stab). Ritorna i byte liberati."""
    import shutil

    freed = 0
    targets = [kind] if kind else ["proxy", "thumbs", "strip", "preview", "stab"]
    for t in targets:
        d = cache_dir(t)
        for f in d.rglob("*"):
            if f.is_file():
                freed += f.stat().st_size
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)
    return freed
