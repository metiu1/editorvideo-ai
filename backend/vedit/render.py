"""Esecuzione del render: dal progetto al file finale.

Il filtergraph viene scritto su file e passato con ``-filter_complex_script``:
su timeline lunghe supera facilmente il limite di 32k caratteri della riga di
comando di Windows.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

from . import effects as fx
from . import ffmpeg, hw, probe
from .graph import CompileOptions, compile_project
from .model import Project

Progress = Callable[[dict], None]

CONTAINER_DEFAULTS = {
    ".mp4": ("h264", "aac"),
    ".mov": ("h264", "aac"),
    ".mkv": ("h264", "aac"),
    ".webm": ("vp9", "libopus"),
    ".gif": ("gif", None),
    ".mp3": (None, "libmp3lame"),
    ".wav": (None, "pcm_s16le"),
    ".m4a": (None, "aac"),
    ".flac": (None, "flac"),
}


@dataclass
class RenderOptions:
    output: str = ""
    codec: str = "h264"  # h264 | hevc | av1 | vp9
    quality: str = "high"  # draft | medium | high | max
    bitrate: str | None = None
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    start: float | None = None
    end: float | None = None
    use_proxy: bool = False
    prefer_hw: bool = True
    # Decodifica accelerata: si spegne da sola al primo ripiego, tenendo pero'
    # l'encoder GPU. Sono due meta' separabili e non valgono lo stesso.
    hwaccel_decode: bool = True
    video: bool = True
    audio: bool = True
    threads: int | None = None
    keep_workdir: bool = False


@dataclass
class RenderResult:
    output: str
    duration: float
    seconds: float
    encoder: str
    size: int
    warnings: list[str] = field(default_factory=list)
    command: list[str] = field(default_factory=list)


def _cache_dir() -> Path:
    base = Path(os.environ.get("VEDIT_CACHE") or (Path.home() / ".vedit"))
    base.mkdir(parents=True, exist_ok=True)
    return base


# --------------------------------------------------------------------------
# analisi preliminari
# --------------------------------------------------------------------------


def analyze_stabilization(project: Project, force: bool = False) -> dict:
    """Primo passaggio vidstab per ogni clip con l'effetto ``stabilize``."""
    out: dict[str, str] = {}
    if "vidstabdetect" not in ffmpeg.filters():
        return out
    stab_dir = _cache_dir() / "stab"
    stab_dir.mkdir(parents=True, exist_ok=True)

    for track in project.video_tracks():
        for clip in track.clips:
            if not clip.enabled or not any(e.type == "stabilize" and e.enabled for e in clip.effects):
                continue
            media = project.media_by_id(clip.media)
            if media is None:
                continue
            trf = stab_dir / f"{clip.id}_{abs(hash((media.path, clip.in_, clip.duration))) & 0xFFFFFFFF:x}.trf"
            if trf.exists() and not force:
                out[clip.id] = str(trf)
                continue
            args = ffmpeg.base_cmd()
            if clip.in_:
                args += ["-ss", str(clip.in_)]
            args += ["-t", str(clip.source_duration()), "-i", media.path,
                     "-vf", f"vidstabdetect=shakiness=6:accuracy=15:result='{fx.esc_path(str(trf))}'",
                     "-f", "null", "NUL" if os.name == "nt" else "/dev/null"]
            ffmpeg.run(args, timeout=3600)
            out[clip.id] = str(trf)
    return out


def measure_loudness(project: Project) -> dict:
    """Misura il mix completo per la normalizzazione lineare a due passaggi."""
    work = Path(tempfile.mkdtemp(prefix="vedit_ln_"))
    try:
        ln = project.master.loudnorm
        was = ln.enabled
        ln.enabled = False  # il primo passaggio misura il mix grezzo
        try:
            c = compile_project(project, CompileOptions(video=False, audio=True, workdir=str(work)))
        finally:
            ln.enabled = was
        if not c.audio_label:
            raise RuntimeError("il progetto non ha audio da misurare")

        script = work / "fg.txt"
        graph = c.filtergraph + f";[{c.audio_label}]loudnorm=I={ln.i}:TP={ln.tp}:LRA={ln.lra}:print_format=json[lnout]"
        script.write_text(graph, encoding="utf-8")

        args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-y"]
        args += c.inputs
        args += ["-filter_complex_script", str(script), "-map", "[lnout]",
                 "-f", "null", "NUL" if os.name == "nt" else "/dev/null"]
        proc = ffmpeg.run(args, check=False, timeout=7200)
        log = (proc.stderr or "") + (proc.stdout or "")
        i, j = log.rfind("{"), log.rfind("}")
        if i == -1 or j == -1:
            raise RuntimeError("misura loudness fallita:\n" + log[-1000:])
        import json

        return json.loads(log[i : j + 1])
    finally:
        shutil.rmtree(work, ignore_errors=True)


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------


def build_command(project: Project, opts: RenderOptions, workdir: Path) -> tuple[list[str], float, list[str], str]:
    out_path = Path(opts.output)
    ext = out_path.suffix.lower()
    def_v, def_a = CONTAINER_DEFAULTS.get(ext, ("h264", "aac"))
    want_video = opts.video and def_v is not None
    want_audio = opts.audio and def_a is not None

    info = hw.detect()
    enc = "libx264"
    if want_video:
        if opts.codec in ("vp9", "gif") or def_v in ("vp9", "gif"):
            enc = {"vp9": "libvpx-vp9", "gif": "gif"}.get(opts.codec if opts.codec in ("vp9", "gif") else def_v, "libvpx-vp9")
        else:
            enc = info.encoder_for(opts.codec, opts.prefer_hw)

    stab = analyze_stabilization(project)
    copts = CompileOptions(
        width=opts.width, height=opts.height, fps=opts.fps,
        use_proxy=opts.use_proxy, audio=want_audio, video=want_video,
        start=opts.start, end=opts.end, workdir=str(workdir),
        hwaccel=info.hwaccel if (opts.prefer_hw and opts.hwaccel_decode and info.is_hw(enc)) else "",
        stab_files=stab,
    )
    c = compile_project(project, copts)

    script = workdir / "filtergraph.txt"
    script.write_text(c.filtergraph, encoding="utf-8")

    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
    if opts.threads:
        args += ["-threads", str(opts.threads)]
    args += c.inputs
    args += ["-filter_complex_script", str(script)]

    if c.video_label:
        args += ["-map", f"[{c.video_label}]"]
    if c.audio_label:
        args += ["-map", f"[{c.audio_label}]"]

    if c.video_label:
        if enc == "gif":
            args += ["-loop", "0"]
        else:
            args += hw.encoder_args(enc, opts.quality, opts.bitrate)
            args += ["-pix_fmt", "yuv420p", "-fps_mode", "cfr", "-r", str(opts.fps or project.settings.fps)]
    if c.audio_label:
        acodec = opts.audio_codec if opts.audio_codec else def_a
        if ext in (".wav", ".flac"):
            acodec = def_a
        args += ["-c:a", acodec]
        if acodec not in ("pcm_s16le", "flac"):
            args += ["-b:a", opts.audio_bitrate]
        args += ["-ar", str(project.settings.sample_rate)]

    args += ["-t", f"{c.duration:.6f}"]
    if ext in (".mp4", ".mov", ".m4a"):
        args += ["-movflags", "+faststart"]
    args += ["-progress", "pipe:1", "-nostats", str(out_path)]
    return args, c.duration, c.warnings, enc


_TIME_RE = re.compile(r"out_time_us=(\d+)")


def _run_pass(args: list[str], duration: float, on_progress: Progress | None,
              t0: float) -> tuple[int, list[str]]:
    """Esegue ffmpeg riportando l'avanzamento. Ritorna (codice, righe di log)."""
    proc = ffmpeg.popen(args)
    log_lines: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        m = _TIME_RE.match(line)
        if m and on_progress:
            done = int(m.group(1)) / 1e6
            on_progress({
                "seconds": round(done, 3),
                "duration": round(duration, 3),
                "percent": round(min(100.0, done / duration * 100), 2) if duration else 0.0,
                "elapsed": round(time.time() - t0, 2),
            })
        elif not line.startswith(("frame=", "fps=", "bitrate=", "total_size=", "out_time",
                                  "dup_frames=", "drop_frames=", "speed=", "progress=", "stream_")):
            log_lines.append(line)
    return proc.wait(), log_lines


# Righe di contorno: dicono che qualcosa e' andato storto, non che cosa.
_RUMORE = ("Error sending frames", "Task finished with error", "Terminating thread",
           "Could not open encoder before EOF", "Nothing was written into output",
           "Conversion failed", "Error while filtering")


def _perche(log_lines: list[str]) -> str:
    """La riga di ffmpeg che spiega davvero il fallimento, per il messaggio.

    Senza questo il ripiego era muto: si sapeva che la GPU non era stata usata,
    mai perche'. Una diagnosi come ``no encode device`` cambia cosa si va a
    guardare, quindi va portata a galla invece di finire nel niente.
    """
    utile = [r for r in log_lines if r.strip() and not any(n in r for n in _RUMORE)]
    if not utile:
        return ""
    riga = re.sub(r"@ [0-9a-fx]+ ", "", utile[0]).strip()
    return f" ({riga[:160]})"


def render(project: Project, opts: RenderOptions, on_progress: Progress | None = None) -> RenderResult:
    if not opts.output:
        raise ValueError("percorso di output mancante")
    out_path = Path(opts.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    workdir = Path(tempfile.mkdtemp(prefix="vedit_"))
    t0 = time.time()
    try:
        args, duration, warnings, enc = build_command(project, opts, workdir)
        code, log_lines = _run_pass(args, duration, on_progress, t0)
        warnings = list(warnings)

        # L'accelerazione hardware e' un'ottimizzazione: non vale un render
        # perso. La GPU puo' mancare al momento giusto — device che non nasce,
        # sessioni dell'encoder gia' tutte occupate da altri processi, driver
        # che cede sotto carico — e ffmpeg non se ne accorge con grazia: esce
        # di schianto.
        #
        # Si ripiega pero' a gradini, non tutto in una volta: le due meta'
        # dell'accelerazione non valgono lo stesso e non falliscono insieme. Il
        # caso tipico e' la coppia che non regge — decodifica accelerata che
        # crea il device sull'adattatore sbagliato e ne fa morire l'encoder —
        # dove basta togliere la decodifica per riavere il render su GPU.
        # Buttare subito anche l'encoder e' quello che trasformava trenta
        # secondi di render in tre minuti, senza dirlo.
        if code != 0 and opts.prefer_hw and "-hwaccel" in args:
            warnings.append(
                "decodifica accelerata fallita: rifatto senza, encoder GPU mantenuto"
                + _perche(log_lines))
            args, duration, _, enc = build_command(
                project, replace(opts, hwaccel_decode=False), workdir)
            code, log_lines = _run_pass(args, duration, on_progress, t0)

        if code != 0 and opts.prefer_hw and hw.detect().is_hw(enc):
            warnings.append(
                "accelerazione hardware fallita: rifatto in software (piu' lento)"
                + _perche(log_lines))
            args, duration, _, enc = build_command(
                project, replace(opts, prefer_hw=False, hwaccel_decode=False), workdir)
            code, log_lines = _run_pass(args, duration, on_progress, t0)

        if code != 0:
            raise ffmpeg.FFmpegError(args, code, "\n".join(log_lines[-40:]))

        size = out_path.stat().st_size if out_path.exists() else 0
        if size == 0:
            raise RuntimeError(f"render terminato ma il file e' vuoto: {out_path}")
        return RenderResult(
            output=str(out_path.resolve()), duration=duration, seconds=round(time.time() - t0, 2),
            encoder=enc, size=size, warnings=warnings, command=args,
        )
    finally:
        if opts.keep_workdir:
            print(f"workdir conservata: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


def render_frame(project: Project, t: float, output: str, width: int | None = None,
                 use_proxy: bool = True) -> str:
    """Estrae un singolo frame della timeline al tempo ``t`` (thumbnail/ispezione)."""
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="vedit_frame_"))
    try:
        fps = project.settings.fps
        w = width or project.settings.width
        h = int(round(w * project.settings.height / project.settings.width))
        h += h % 2
        copts = CompileOptions(
            width=w, height=h, fps=fps, use_proxy=use_proxy, audio=False, video=True,
            start=max(0.0, t), end=max(0.0, t) + max(2.0 / fps, 0.05), workdir=str(workdir),
        )
        c = compile_project(project, copts)
        script = workdir / "fg.txt"
        script.write_text(c.filtergraph, encoding="utf-8")
        args = ffmpeg.base_cmd() + c.inputs + [
            "-filter_complex_script", str(script), "-map", f"[{c.video_label}]",
            "-frames:v", "1", "-q:v", "3", str(out),
        ]
        ffmpeg.run(args, timeout=600)
        return str(out.resolve())
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def probe_output(path: str) -> dict:
    """Riepilogo del file prodotto (per verificare il risultato)."""
    m = probe.probe(path)
    return {
        "path": m.path, "duration": m.duration, "width": m.width, "height": m.height,
        "fps": m.fps, "has_audio": m.has_audio,
        "size_mb": round(Path(path).stat().st_size / 1e6, 2),
    }
