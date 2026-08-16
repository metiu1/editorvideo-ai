"""Uniformare il colore tra clip girate in condizioni diverse.

Il metodo e' quello classico del *color transfer* statistico: per ogni canale si
misurano media e deviazione standard della clip da correggere e di quella di
riferimento, poi si applica la trasformazione lineare che porta la prima ad
avere le statistiche della seconda.

    out = (in - media_sorgente) * (dev_rif / dev_sorgente) + media_rif

E' una correzione onesta e prevedibile: allinea esposizione e dominante, non
inventa un look. Se le due clip hanno contenuto molto diverso (un cielo contro
un primo piano) le statistiche mentono, ed e' per questo che ``strength``
esiste: si applica al 50-70% e si guarda.
"""

from __future__ import annotations

import subprocess

from . import ffmpeg, probe

GAIN_MIN, GAIN_MAX = 0.4, 2.5
OFF_MIN, OFF_MAX = -0.5, 0.5
SAMPLES = 12


def stats(path: str, samples: int = SAMPLES, width: int = 128) -> dict:
    """Media e deviazione standard per canale (0..1), campionando il video."""
    import numpy as np

    m = probe.probe(path)
    dur = m.duration or 1.0
    fps = max(0.2, min(float(samples) / dur, 10.0))
    h = max(2, int(width * (m.height or 9) / (m.width or 16)) // 2 * 2)

    proc = subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(path), "-an", "-sn",
        "-vf", f"fps={fps},scale={width}:{h},format=rgb24",
        "-f", "rawvideo", "-",
    ], capture_output=True, timeout=1800)
    raw = proc.stdout or b""
    size = width * h * 3
    n = len(raw) // size
    if n == 0:
        raise ValueError(f"nessun fotogramma leggibile in {path}")
    buf = np.frombuffer(raw[: n * size], dtype=np.uint8).reshape(n * h * width, 3)
    buf = buf.astype(np.float32) / 255.0
    return {
        "mean": [round(float(x), 5) for x in buf.mean(axis=0)],
        "std": [round(float(x), 5) for x in buf.std(axis=0)],
        "frames": n,
    }


def match_params(src: dict, ref: dict, strength: float = 1.0) -> dict:
    """Parametri dell'effetto ``colormatch`` per portare ``src`` su ``ref``."""
    s = max(0.0, min(1.0, float(strength)))
    out = {}
    for i, ch in enumerate("rgb"):
        sd_s = max(src["std"][i], 1e-3)      # una clip piatta non deve esplodere
        gain = ref["std"][i] / sd_s
        gain = max(GAIN_MIN, min(GAIN_MAX, gain))
        off = ref["mean"][i] - src["mean"][i] * gain
        gain = 1.0 + (gain - 1.0) * s
        off = max(OFF_MIN, min(OFF_MAX, off * s))
        out[f"{ch}_gain"] = round(gain, 4)
        out[f"{ch}_off"] = round(off, 4)
    return out


def match(src_path: str, ref_path: str, strength: float = 1.0,
          samples: int = SAMPLES) -> dict:
    """Misura entrambe le clip e ritorna i parametri di correzione."""
    a = stats(src_path, samples)
    b = stats(ref_path, samples)
    params = match_params(a, b, strength)
    return {"params": params, "sorgente": a, "riferimento": b,
            "distanza_prima": distance(a, b)}


def distance(a: dict, b: dict) -> float:
    """Quanto sono lontane due clip: 0 = identiche. Serve a misurare i risultati."""
    d = sum(abs(a["mean"][i] - b["mean"][i]) + abs(a["std"][i] - b["std"][i])
            for i in range(3))
    return round(d / 6.0, 5)
