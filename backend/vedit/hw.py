"""Rilevamento accelerazione hardware.

La presenza dell'encoder nella build non basta: NVENC compila sempre ma fallisce
a runtime se driver/GPU non ci sono. Facciamo una prova reale di 1 frame e la
mettiamo in cache su disco.

Codifica e decodifica accelerate sono due cose distinte e vanno provate
separatamente: NVENC puo' codificare benissimo su una macchina dove il
decodificatore DXVA2 non riesce nemmeno a creare il device Direct3D. Dare per
buona la decodifica perche' funziona la codifica e' proprio come si arriva a un
ffmpeg che esce con 0xC0000005 a meta' render.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import ffmpeg

CACHE_TTL = 7 * 24 * 3600

# Preferenza per codec: il primo che passa la prova vince.
CANDIDATES = {
    "h264": ["h264_nvenc", "h264_qsv", "h264_amf", "libx264"],
    "hevc": ["hevc_nvenc", "hevc_qsv", "hevc_amf", "libx265"],
    "av1": ["av1_nvenc", "av1_qsv", "libsvtav1"],
}

# Metodi di decodifica accelerata, in ordine di preferenza. Niente "auto": e'
# ffmpeg a scegliere, e su Windows sceglie spesso proprio quello che non regge
# piu' contesti aperti insieme.
DECODERS = (
    ["d3d11va", "cuda", "qsv", "dxva2"] if os.name == "nt"
    else ["cuda", "vaapi", "qsv", "videotoolbox"]
)


@dataclass
class HWInfo:
    encoders: dict  # codec -> encoder scelto
    working: list  # encoder hw verificati
    checked_at: float = 0.0
    # metodo di decodifica accelerata verificato ("" = nessuno utilizzabile)
    hwaccel: str = ""

    def encoder_for(self, codec: str, prefer_hw: bool = True) -> str:
        if not prefer_hw:
            return {"h264": "libx264", "hevc": "libx265", "av1": "libsvtav1"}.get(codec, "libx264")
        return self.encoders.get(codec, "libx264")

    def is_hw(self, enc: str) -> bool:
        return enc in self.working


def _cache_file() -> Path:
    base = os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p / "hw.json"


def _test_encoder(enc: str) -> bool:
    """Codifica 1 frame di test; se esce 0 l'encoder e' realmente usabile."""
    null = "NUL" if os.name == "nt" else "/dev/null"
    args = [
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25:d=0.1",
        "-c:v", enc, "-frames:v", "1", "-f", "null", null,
    ]
    try:
        return ffmpeg.run(args, timeout=30, check=False).returncode == 0
    except Exception:
        return False


def _probe_file() -> Path | None:
    """File h264 minimo su cui provare la decodifica accelerata."""
    f = _cache_file().with_name("hwprobe.mp4")
    if f.exists() and f.stat().st_size > 0:
        return f
    args = [
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(f),
    ]
    try:
        if ffmpeg.run(args, timeout=60, check=False).returncode == 0 and f.stat().st_size > 0:
            return f
    except Exception:
        pass
    return None


def _test_hwaccel(method: str, probe: Path) -> bool:
    """Prova la decodifica accelerata come la usa il render: piu' ingressi insieme.

    Con un ingresso solo passano anche metodi che poi cedono: il render apre un
    contesto per clip (video e audio separati), e il limite lo si trova li'. Due
    ingressi sono il minimo che riproduca quella condizione.
    """
    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
    for _ in range(2):
        args += ["-hwaccel", method, "-i", str(probe)]
    args += ["-f", "null", "NUL" if os.name == "nt" else "/dev/null"]
    try:
        return ffmpeg.run(args, timeout=60, check=False).returncode == 0
    except Exception:
        return False


def detect(force: bool = False) -> HWInfo:
    cache = _cache_file()
    if not force and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            # "hwaccel" assente = cache scritta prima che la decodifica venisse
            # verificata: va rifatta, altrimenti resta il comportamento vecchio
            if time.time() - data.get("checked_at", 0) < CACHE_TTL and "hwaccel" in data:
                return HWInfo(**data)
        except Exception:
            pass

    available = ffmpeg.encoders()
    chosen: dict[str, str] = {}
    working: list[str] = []
    for codec, cands in CANDIDATES.items():
        for enc in cands:
            if enc not in available:
                continue
            if enc.startswith(("lib", "libsvt")):
                chosen.setdefault(codec, enc)
                break
            if _test_encoder(enc):
                chosen[codec] = enc
                working.append(enc)
                break

    hwaccel = ""
    probe = _probe_file() if working else None
    if probe is not None:
        hwaccel = next((m for m in DECODERS if _test_hwaccel(m, probe)), "")

    info = HWInfo(encoders=chosen, working=working, checked_at=time.time(), hwaccel=hwaccel)
    try:
        cache.write_text(json.dumps(asdict(info), indent=2), encoding="utf-8")
    except OSError:
        pass
    return info


def encoder_args(enc: str, quality: str = "high", bitrate: str | None = None) -> list[str]:
    """Argomenti di codifica tarati per encoder e livello qualita'."""
    q = {"draft": 0, "medium": 1, "high": 2, "max": 3}.get(quality, 2)

    if "nvenc" in enc:
        preset = ["p1", "p4", "p5", "p7"][q]
        cq = [34, 26, 21, 17][q]
        args = ["-c:v", enc, "-preset", preset, "-tune", "hq", "-rc", "vbr", "-cq", str(cq),
                "-b:v", "0", "-spatial-aq", "1", "-temporal-aq", "1", "-rc-lookahead", "20"]
        if bitrate:
            args = ["-c:v", enc, "-preset", preset, "-b:v", bitrate, "-maxrate", bitrate,
                    "-bufsize", _bufsize(bitrate)]
        return args
    if "qsv" in enc:
        gq = [32, 26, 22, 18][q]
        return ["-c:v", enc, "-global_quality", str(gq), "-preset", ["veryfast", "medium", "slow", "veryslow"][q]]
    if "amf" in enc:
        return ["-c:v", enc, "-quality", ["speed", "balanced", "quality", "quality"][q],
                "-rc", "cqp", "-qp_i", str([32, 26, 22, 18][q]), "-qp_p", str([34, 28, 24, 20][q])]
    if enc == "libx265":
        return ["-c:v", enc, "-preset", ["ultrafast", "medium", "slow", "slower"][q],
                "-crf", str([32, 26, 22, 18][q]), "-tag:v", "hvc1"]
    if enc == "libsvtav1":
        return ["-c:v", enc, "-preset", str([10, 8, 6, 4][q]), "-crf", str([40, 34, 30, 26][q])]
    # libx264 e fallback
    return ["-c:v", enc, "-preset", ["ultrafast", "medium", "slow", "slower"][q],
            "-crf", str([28, 23, 19, 16][q])]


def _bufsize(bitrate: str) -> str:
    try:
        n = float(bitrate.rstrip("kKmM"))
        unit = bitrate[-1] if bitrate[-1].isalpha() else ""
        return f"{n * 2:.0f}{unit}"
    except (ValueError, IndexError):
        return bitrate
