"""Procurarsi ffmpeg quando il sistema non ce l'ha.

ffmpeg e' l'unica dipendenza davvero obbligatoria di vedit, ed e' anche l'unica
che ``pip`` non sa installare: e' un programma, non un pacchetto Python. Chi
arriva da ``uvx vedit-mcp`` non ha una repo sotto mano, quindi non ha nemmeno
``scripts/setup.py --install-ffmpeg``: senza una via d'uscita dentro il
pacchetto si ritroverebbe con un editor che non renderizza niente.

Qui c'e' quella via d'uscita: scarica una build statica ufficiale e la mette
nella cache di vedit (``~/.vedit/bin``). Non tocca il sistema, non serve
amministratore, e si disinstalla cancellando la cartella.

Perche' non un pacchetto pip con dentro il binario: quelli in circolazione
portano ``ffmpeg`` ma non ``ffprobe``, e senza ffprobe non si leggono i
metadati dei sorgenti — meta' editor. Le build usate qui hanno tutti e due.

Resta comunque preferibile l'ffmpeg di sistema (di solito con piu' encoder
hardware): :func:`vedit.ffmpeg.binary` guarda prima nel PATH e solo dopo qui.
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

from .proxy import cache_dir

NAMES = ("ffmpeg", "ffprobe")

# Build statiche di BtbN: un solo archivio con ffmpeg e ffprobe dentro.
_BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/"
_ARCHIVI = {
    ("Windows", "x86_64"): _BTBN + "ffmpeg-master-latest-win64-gpl.zip",
    ("Windows", "arm64"): _BTBN + "ffmpeg-master-latest-winarm64-gpl.zip",
    ("Linux", "x86_64"): _BTBN + "ffmpeg-master-latest-linux64-gpl.tar.xz",
    ("Linux", "arm64"): _BTBN + "ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
}
# macOS non e' coperto da BtbN: evermeet pubblica i due binari separati.
_EVERMEET = {name: f"https://evermeet.cx/ffmpeg/getrelease/{name}/zip" for name in NAMES}


def _arch() -> str:
    m = platform.machine().lower()
    if m in ("amd64", "x86_64"):
        return "x86_64"
    if m in ("arm64", "aarch64"):
        return "arm64"
    return m


def bin_dir() -> Path:
    return cache_dir("bin")


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def local(name: str = "ffmpeg") -> str | None:
    """Percorso del binario gia' scaricato, se c'e'."""
    p = bin_dir() / _exe(name)
    return str(p) if p.is_file() else None


def installed() -> dict[str, str | None]:
    return {n: local(n) for n in NAMES}


def _scarica(url: str, dest: Path, progress=None) -> None:
    req = Request(url, headers={"User-Agent": "vedit"})
    with urlopen(req, timeout=60) as r:  # noqa: S310 - URL fissi, non arrivano dall'utente
        totale = int(r.headers.get("Content-Length") or 0)
        fatto = 0
        with dest.open("wb") as f:
            while True:
                blocco = r.read(1 << 16)
                if not blocco:
                    break
                f.write(blocco)
                fatto += len(blocco)
                if progress and totale:
                    progress(fatto / totale)


def _estrai(archivio: Path, dove: Path) -> list[str]:
    """Tira fuori solo ffmpeg/ffprobe, ovunque siano dentro l'archivio."""
    cercati = {_exe(n) for n in NAMES}
    presi: list[str] = []
    # il formato si guarda dal contenuto, non dal nome: l'estensione arriva
    # dall'URL e un giorno l'archivio puo' cambiare tipo senza cambiare indirizzo
    apri = zipfile.ZipFile if zipfile.is_zipfile(archivio) else tarfile.open
    with apri(archivio) as arc:  # type: ignore[operator]
        nomi = arc.namelist() if isinstance(arc, zipfile.ZipFile) else arc.getnames()
        for membro in nomi:
            base = membro.rsplit("/", 1)[-1]
            if base not in cercati:
                continue
            target = dove / base
            if isinstance(arc, zipfile.ZipFile):
                dati = arc.read(membro)
            else:
                f = arc.extractfile(membro)
                if f is None:
                    continue
                dati = f.read()
            target.write_bytes(dati)
            target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
            presi.append(base)
    return presi


def install(progress=None, force: bool = False) -> dict:
    """Scarica ffmpeg e ffprobe nella cache di vedit.

    ``progress`` riceve una frazione fra 0 e 1 (puo' essere chiamata piu' volte
    per ogni file scaricato).
    """
    dove = bin_dir()
    if not force and all(local(n) for n in NAMES):
        return {"stato": "gia_presente", "cartella": str(dove), **installed()}

    sistema = platform.system()
    if sistema == "Darwin":
        urls = list(_EVERMEET.values())
    else:
        url = _ARCHIVI.get((sistema, _arch()))
        if not url:
            raise RuntimeError(
                f"nessuna build pronta per {sistema}/{_arch()}: installa ffmpeg con il gestore "
                "pacchetti del sistema, oppure indica i binari con VEDIT_FFMPEG / VEDIT_FFPROBE"
            )
        urls = [url]

    presi: list[str] = []
    with tempfile.TemporaryDirectory(prefix="vedit-ffmpeg-") as tmp:
        for i, url in enumerate(urls):
            suffisso = ".zip" if url.endswith("zip") else ".tar.xz"
            archivio = Path(tmp) / f"ff{i}{suffisso}"
            _scarica(url, archivio, (lambda f, i=i: progress((i + f) / len(urls))) if progress else None)
            presi += _estrai(archivio, dove)

    mancanti = [n for n in NAMES if not local(n)]
    if mancanti:
        raise RuntimeError(
            f"scaricato ma senza {', '.join(mancanti)}: l'archivio non conteneva il binario atteso"
        )
    return {"stato": "installato", "cartella": str(dove), "estratti": presi, **installed()}


def remove() -> bool:
    """Cancella i binari scaricati (torna a usare solo quelli di sistema)."""
    d = bin_dir()
    if not any(local(n) for n in NAMES):
        return False
    shutil.rmtree(d, ignore_errors=True)
    return True
