"""Analisi del materiale: *cosa* c'e' dentro una clip, non come renderizzarla.

Il montaggio automatico ha bisogno di sapere dove si taglia, dove si parla, dove
il girato e' inutilizzabile. Qui ci sono le misure grezze; il giudizio ("questa
clip non serve", "taglia i primi 2 secondi") sta in :func:`report`, che le
combina e resta l'unico punto dove cambiare le soglie.

Ogni misura e' cache-ata su disco per (file, dimensione, mtime, parametri):
analizzare una cartella di girato si paga una volta sola.

Note pratiche:
- passare il proxy 540p invece dell'originale rende l'analisi video 5-10x piu'
  rapida e i tempi restano identici (stesso timecode);
- la trascrizione richiede ``faster-whisper``; senza quello tutto il resto
  funziona lo stesso, ``transcript`` resta ``None``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from . import ffmpeg, proxy

# --------------------------------------------------------------------------
# soglie: i numeri stanno tutti qui, cosi' si tarano in un posto solo
# --------------------------------------------------------------------------

SCENE_THRESHOLD = 0.30      # 0..1, differenza tra fotogrammi che vale un taglio
SILENCE_DB = -32.0          # sotto questo livello e' silenzio
SILENCE_MIN = 0.40          # secondi: sotto e' una pausa di respiro, non silenzio
DARK_LEVEL = 0.06           # luminanza media normalizzata: sotto e' nero
BRIGHT_LEVEL = 0.94         # sopra e' bruciato
FOCUS_FLOOR = 0.25          # fuoco < 25% della mediana della clip = sfocato
STATS_FPS = 2.0             # campioni al secondo per luminanza/fuoco


class AnalysisError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# cache
# --------------------------------------------------------------------------


def _sig(path: str, tag: str) -> str:
    import hashlib
    try:
        st = Path(path).stat()
        raw = f"{Path(path).resolve()}|{st.st_size}|{int(st.st_mtime)}|{tag}"
    except OSError:
        raw = f"{path}|{tag}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _cached(path: str, tag: str, build, force: bool = False):
    f = proxy.cache_dir("analysis") / f"{_sig(path, tag)}.json"
    if f.exists() and not force:
        try:
            return json.loads(f.read_text("utf-8"))
        except (OSError, ValueError):
            pass
    data = build()
    try:
        f.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    except OSError:
        pass
    return data


# --------------------------------------------------------------------------
# misure video
# --------------------------------------------------------------------------


def _run_detect(args: list[str], timeout: float = 3600) -> str:
    proc = ffmpeg.run(args, check=False, timeout=timeout)
    return (proc.stderr or "") + (proc.stdout or "")


def scenes(path: str, threshold: float = SCENE_THRESHOLD, min_len: float = 0.5,
           force: bool = False) -> list[float]:
    """Istanti (s) in cui l'inquadratura cambia. Il primo taglio e' sempre 0."""

    def build() -> list[float]:
        log = _run_detect([
            ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "info",
            "-i", str(path),
            "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
            "-an", "-sn", "-f", "null", "-",
        ])
        cuts: list[float] = []
        for m in re.finditer(r"pts_time:([0-9.]+)", log):
            t = round(float(m.group(1)), 3)
            if not cuts or t - cuts[-1] >= min_len:
                cuts.append(t)
        return [0.0] + [t for t in cuts if t >= min_len]

    return _cached(path, f"scenes{threshold}x{min_len}", build, force)


def dead_ranges(path: str, force: bool = False) -> dict:
    """Tratti neri e tratti congelati (girato inutile per definizione)."""

    def build() -> dict:
        log = _run_detect([
            ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "info",
            "-i", str(path),
            "-vf", "blackdetect=d=0.25:pix_th=0.10,freezedetect=n=-60dB:d=1.0",
            "-an", "-sn", "-f", "null", "-",
        ])
        black = [[round(float(a), 3), round(float(b), 3)]
                 for a, b in re.findall(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)", log)]
        fs = [float(x) for x in re.findall(r"freeze_start:\s*([0-9.]+)", log)]
        fe = [float(x) for x in re.findall(r"freeze_end:\s*([0-9.]+)", log)]
        freeze = [[round(a, 3), round(b, 3)] for a, b in zip(fs, fe)]
        return {"black": black, "freeze": freeze}

    return _cached(path, "dead", build, force)


def frame_stats(path: str, fps: float = STATS_FPS, width: int = 160,
                force: bool = False) -> list[dict]:
    """Luminanza, contrasto e nitidezza campionati nel tempo.

    Serve a riconoscere il materiale inutilizzabile: buio, bruciato, fuori fuoco.
    Il fuoco e' la varianza del laplaciano, la misura classica: alta = dettaglio
    a fuoco, bassa = sfocato o piatto.
    """

    def build() -> list[dict]:
        try:
            import numpy as np
        except ImportError as e:  # pragma: no cover - numpy e' una dipendenza
            raise AnalysisError("numpy richiesto per frame_stats") from e

        h = 90 if width == 160 else max(2, int(width * 9 / 16) // 2 * 2)
        args = [
            ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
            "-i", str(path), "-an", "-sn",
            "-vf", f"fps={fps},scale={width}:{h},format=gray",
            "-f", "rawvideo", "-",
        ]
        proc = subprocess.run(args, capture_output=True, timeout=3600)
        raw = proc.stdout or b""
        size = width * h
        n = len(raw) // size
        if n == 0:
            return []
        buf = np.frombuffer(raw[: n * size], dtype=np.uint8).reshape(n, h, width)
        out = []
        for i in range(n):
            g = buf[i].astype(np.float32) / 255.0
            lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
                   - 4.0 * g[1:-1, 1:-1])
            out.append({
                "t": round(i / fps, 3),
                "brightness": round(float(g.mean()), 4),
                "contrast": round(float(g.std()), 4),
                "focus": round(float(lap.var()), 6),
            })
        return out

    return _cached(path, f"stats{fps}x{width}", build, force)


# --------------------------------------------------------------------------
# misure audio
# --------------------------------------------------------------------------


def silences(path: str, noise_db: float = SILENCE_DB, min_dur: float = SILENCE_MIN,
             force: bool = False) -> list[list[float]]:
    """Intervalli [inizio, fine] sotto la soglia di rumore."""

    def build() -> list[list[float]]:
        log = _run_detect([
            ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "info",
            "-i", str(path), "-vn",
            "-af", f"silencedetect=n={noise_db}dB:d={min_dur}",
            "-f", "null", "-",
        ])
        out: list[list[float]] = []
        start = None
        for m in re.finditer(r"silence_(start|end):\s*(-?[0-9.]+)", log):
            kind, v = m.group(1), float(m.group(2))
            if kind == "start":
                start = max(0.0, v)
            elif start is not None:
                out.append([round(start, 3), round(v, 3)])
                start = None
        if start is not None:
            out.append([round(start, 3), -1.0])   # silenzio fino a fine file
        return out

    return _cached(path, f"sil{noise_db}x{min_dur}", build, force)


def transcribe(path: str, model_size: str = "small", language: str | None = None,
               force: bool = False) -> dict:
    """Trascrizione con timestamp per parola (faster-whisper).

    I timestamp per parola sono il punto: permettono di tagliare sulla pausa
    giusta, togliere gli "ehm", censurare una singola parola.
    """

    def build() -> dict:
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise AnalysisError(
                "faster-whisper non installato: pip install faster-whisper"
            ) from e
        device, compute = "cpu", "int8"
        try:
            import torch
            if torch.cuda.is_available():
                device, compute = "cuda", "int8_float16"
        except ImportError:
            pass

        model = WhisperModel(model_size, device=device, compute_type=compute)
        segments, info = model.transcribe(
            str(path), language=language, word_timestamps=True,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 400},
        )
        segs = []
        for s in segments:
            segs.append({
                "start": round(s.start, 3), "end": round(s.end, 3),
                "text": s.text.strip(),
                "words": [{"t": round(w.start, 3), "e": round(w.end, 3),
                           "w": w.word.strip(), "p": round(float(w.probability), 3)}
                          for w in (s.words or [])],
            })
        words = [w for s in segs for w in s["words"]]
        speech = sum(s["end"] - s["start"] for s in segs)
        return {
            "language": info.language,
            "language_prob": round(float(info.language_probability or 0), 3),
            "duration": round(float(info.duration or 0), 3),
            "speech_seconds": round(speech, 3),
            "words_per_minute": round(60 * len(words) / speech, 1) if speech > 0 else 0.0,
            "text": " ".join(s["text"] for s in segs).strip(),
            "segments": segs,
            "model": model_size, "device": device,
        }

    return _cached(path, f"asr{model_size}x{language or 'auto'}", build, force)


# --------------------------------------------------------------------------
# analisi completa + giudizio
# --------------------------------------------------------------------------


def analyze(path: str, deep: bool = False, model_size: str = "small",
            language: str | None = None, force: bool = False) -> dict:
    """Tutte le misure di un file. ``deep=True`` aggiunge la trascrizione."""
    from . import probe as _probe

    m = _probe.probe(path)
    out: dict = {
        "path": str(Path(path).resolve()),
        "kind": m.kind,
        "duration": m.duration,
        "width": m.width, "height": m.height, "fps": m.fps,
        "has_audio": m.has_audio,
    }
    if m.has_video and m.kind == "video":
        out["scenes"] = scenes(path, force=force)
        out["dead"] = dead_ranges(path, force=force)
        out["stats"] = frame_stats(path, force=force)
    if m.has_audio:
        out["silences"] = silences(path, force=force)
        if deep:
            out["transcript"] = transcribe(path, model_size, language, force=force)
    return out


def _cover(ranges, a: float, b: float) -> float:
    """Secondi di [a,b] coperti dagli intervalli."""
    tot = 0.0
    for r in ranges or []:
        s, e = float(r[0]), float(r[1])
        if e < 0:
            e = b
        tot += max(0.0, min(e, b) - max(s, a))
    return tot


def report(path: str, deep: bool = False, **kw) -> dict:
    """Verdetto su una clip: tenerla, accorciarla o scartarla, e perche'.

    Il verdetto non e' un oracolo: e' la somma di misure verificabili, ognuna
    riportata in ``issues`` con il suo peso, cosi' si puo' contestare.
    """
    a = analyze(path, deep=deep, **kw)
    dur = float(a["duration"]) or 0.0
    stats = a.get("stats") or []
    issues: list[str] = []

    dark = bright = blurry = 0.0
    if stats:
        focus = sorted(s["focus"] for s in stats)
        med = focus[len(focus) // 2]
        step = dur / len(stats) if dur else 0.0
        for s in stats:
            if s["brightness"] < DARK_LEVEL:
                dark += step
            elif s["brightness"] > BRIGHT_LEVEL:
                bright += step
            if med > 0 and s["focus"] < med * FOCUS_FLOOR:
                blurry += step

    black = _cover(a.get("dead", {}).get("black"), 0, dur)
    freeze = _cover(a.get("dead", {}).get("freeze"), 0, dur)
    silence = _cover(a.get("silences"), 0, dur)
    speech = float((a.get("transcript") or {}).get("speech_seconds") or 0.0)

    def frac(x: float) -> float:
        return round(x / dur, 3) if dur > 0 else 0.0

    # taglio suggerito: via il silenzio/nero in testa e in coda, il resto resta
    head = tail = 0.0
    for r in sorted(list(a.get("silences") or []) + list(a.get("dead", {}).get("black") or [])):
        s, e = float(r[0]), (float(r[1]) if float(r[1]) >= 0 else dur)
        if s <= head + 0.05:
            head = max(head, e)
        if e >= dur - 0.05:
            tail = max(tail, dur - s)
    head = min(head, dur)
    tail = min(tail, max(0.0, dur - head))

    if frac(black) > 0.5:
        issues.append(f"nero per il {frac(black) * 100:.0f}% della durata")
    if frac(freeze) > 0.5:
        issues.append(f"immagine congelata per il {frac(freeze) * 100:.0f}%")
    if frac(blurry) > 0.4:
        issues.append(f"fuori fuoco per il {frac(blurry) * 100:.0f}%")
    if frac(dark) > 0.4:
        issues.append(f"sottoesposta per il {frac(dark) * 100:.0f}%")
    if frac(bright) > 0.4:
        issues.append(f"bruciata per il {frac(bright) * 100:.0f}%")
    if a.get("has_audio") and dur > 2 and frac(silence) > 0.9:
        issues.append("audio praticamente muto")
    if dur < 0.5:
        issues.append("troppo corta per essere usata")
    if head + tail > 0.3:
        issues.append(f"da accorciare: {head:.1f}s in testa, {tail:.1f}s in coda")

    unusable = frac(black + freeze) > 0.6 or frac(blurry) > 0.7 or dur < 0.5
    verdict = "drop" if unusable else ("trim" if head + tail > 0.3 else "keep")

    return {
        "path": a["path"],
        "duration": round(dur, 3),
        "verdict": verdict,
        "issues": issues,
        "suggested_in": round(head, 3),
        "suggested_out": round(max(head, dur - tail), 3),
        "measures": {
            "black": frac(black), "freeze": frac(freeze), "blurry": frac(blurry),
            "dark": frac(dark), "bright": frac(bright), "silence": frac(silence),
            "speech": frac(speech), "cuts": len(a.get("scenes") or []),
        },
        "transcript": (a.get("transcript") or {}).get("text"),
    }


# --------------------------------------------------------------------------
# censura
# --------------------------------------------------------------------------

# lista minima: si estende con l'argomento ``words``. Volutamente corta e
# esplicita, non un filtro morale: serve a dimostrare il meccanismo.
PROFANITY = (
    "cazzo", "stronzo", "merda", "vaffanculo", "puttana", "coglione", "porco dio",
    "fuck", "fucking", "shit", "bitch", "asshole", "cunt",
)


def censor_spans(path: str, words: tuple[str, ...] = (), pad: float = 0.08,
                 model_size: str = "small", language: str | None = None) -> list[dict]:
    """Intervalli da coprire: parole della lista trovate nel parlato.

    Ritorna ``[{"start":…, "end":…, "word":…}]``, gia' con un margine ``pad``
    perche' il riconoscimento tende a tagliare corto sull'attacco della parola.
    """
    target = {w.lower() for w in (tuple(words) + PROFANITY) if w}
    tr = transcribe(path, model_size, language)
    out = []
    for seg in tr["segments"]:
        for w in seg["words"]:
            clean = re.sub(r"[^\w' ]", "", w["w"]).lower()
            if clean and any(clean == t or t in clean for t in target):
                out.append({"start": round(max(0.0, w["t"] - pad), 3),
                            "end": round(w["e"] + pad, 3), "word": w["w"]})
    return out


# Solo esitazioni pure: "tipo", "cioe'", "allora" sono parole vere e toglierle
# alla cieca rovina il senso. Chi le vuole fuori le passa in ``extra``.
FILLERS = (
    "ehm", "eh", "ehh", "uhm", "uh", "um", "umm", "mm", "mmm", "hmm", "ah", "er", "err",
    # whisper trascrive spesso l'esitazione italiana "ehm" come una "m" isolata
    "m", "mh", "eeh", "ehmm",
)


def filler_spans(path: str, extra: tuple[str, ...] = (), pad: float = 0.02,
                 model_size: str = "small", language: str | None = None) -> list[dict]:
    """Intervalli occupati da esitazioni ("ehm", "uh", ...) nel parlato."""
    target = {w.lower() for w in (FILLERS + tuple(extra)) if w}
    tr = transcribe(path, model_size, language)
    out = []
    for seg in tr["segments"]:
        for w in seg["words"]:
            clean = re.sub(r"[^\w']", "", w["w"]).lower()
            if clean in target:
                out.append({"start": round(max(0.0, w["t"] - pad), 3),
                            "end": round(w["e"] + pad, 3), "word": w["w"]})
    return out


def ranges_expr(spans) -> str:
    """Intervalli -> stringa ``a-b;c-d`` per gli effetti di censura."""
    return ";".join(f"{float(s['start'] if isinstance(s, dict) else s[0]):.3f}-"
                    f"{float(s['end'] if isinstance(s, dict) else s[1]):.3f}"
                    for s in spans)
