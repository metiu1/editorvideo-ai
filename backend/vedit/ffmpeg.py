"""Localizzazione dei binari ffmpeg/ffprobe e wrapper di esecuzione."""

from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache

_NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


class FFmpegError(RuntimeError):
    def __init__(self, cmd: list[str], code: int, log: str):
        self.cmd = cmd
        self.code = code
        self.log = log
        tail = "\n".join(log.strip().splitlines()[-25:])
        super().__init__(f"ffmpeg uscito con codice {code}\n{tail}")


@lru_cache(maxsize=None)
def binary(name: str = "ffmpeg") -> str:
    env = os.environ.get(f"VEDIT_{name.upper()}")
    if env and os.path.isfile(env):
        return env
    found = shutil.which(name)
    if found:
        return found
    # ultimo posto dove guardare: la copia scaricata da vedit stesso. L'ffmpeg
    # di sistema resta preferito perche' di solito ha piu' encoder hardware.
    from . import ffbin

    scaricato = ffbin.local(name)
    if scaricato:
        return scaricato
    raise FileNotFoundError(
        f"{name} non trovato nel PATH. Scaricalo con `vedit install-ffmpeg` (nessun permesso di "
        f"amministratore, finisce in {ffbin.bin_dir()}), installalo col gestore pacchetti del "
        f"sistema, oppure imposta VEDIT_{name.upper()} sul percorso del binario."
    )


def forget() -> None:
    """Dimentica i percorsi trovati: da chiamare dopo aver installato ffmpeg."""
    binary.cache_clear()
    version.cache_clear()
    filters.cache_clear()
    encoders.cache_clear()


def run(args: list[str], *, timeout: float | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Esegue un comando catturando stdout/stderr come testo."""
    proc = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
    )
    if check and proc.returncode != 0:
        raise FFmpegError(args, proc.returncode, (proc.stderr or "") + (proc.stdout or ""))
    return proc


def popen(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )


def base_cmd(overwrite: bool = True) -> list[str]:
    cmd = [binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error"]
    cmd.append("-y" if overwrite else "-n")
    return cmd


@lru_cache(maxsize=1)
def version() -> str:
    out = run([binary("ffmpeg"), "-version"], check=False).stdout or ""
    return out.splitlines()[0] if out else "sconosciuta"


@lru_cache(maxsize=1)
def filters() -> frozenset[str]:
    out = run([binary("ffmpeg"), "-hide_banner", "-filters"], check=False).stdout or ""
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and not line.startswith("Filters"):
            names.add(parts[1])
    return frozenset(names)


@lru_cache(maxsize=1)
def encoders() -> frozenset[str]:
    out = run([binary("ffmpeg"), "-hide_banner", "-encoders"], check=False).stdout or ""
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0][:1] in "VAS" and len(parts[0]) == 6:
            names.add(parts[1])
    return frozenset(names)
