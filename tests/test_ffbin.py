"""ffmpeg procurato da vedit stesso.

Nessun test scarica davvero: la rete non deve entrare nella suite. Si verifica
la parte che puo' rompersi in silenzio — dove si cercano i binari, in che
ordine, e che dall'archivio escano *tutti e due* (ffprobe compreso, che e'
proprio quello che manca ai pacchetti pip in giro).
"""

import platform
import tarfile
import zipfile
from pathlib import Path

import pytest

from vedit import ffbin, ffmpeg


@pytest.fixture
def cache(tmp_path, monkeypatch):
    """Cache dei binari isolata: i test non toccano ~/.vedit dell'utente."""
    d = tmp_path / "bin"
    d.mkdir()
    monkeypatch.setattr(ffbin, "bin_dir", lambda: d)
    return d


def _finto(d: Path, nome: str) -> Path:
    p = d / ffbin._exe(nome)
    p.write_bytes(b"#!/bin/sh\n")
    return p


def test_local_trova_solo_se_ce(cache):
    assert ffbin.local("ffmpeg") is None
    p = _finto(cache, "ffmpeg")
    assert ffbin.local("ffmpeg") == str(p)
    assert ffbin.local("ffprobe") is None


def test_install_non_riscarica_se_gia_presenti(cache, monkeypatch):
    for n in ffbin.NAMES:
        _finto(cache, n)
    monkeypatch.setattr(ffbin, "_scarica", lambda *a, **k: pytest.fail("non doveva scaricare"))
    assert ffbin.install()["stato"] == "gia_presente"


def test_estrae_ffmpeg_e_ffprobe_da_zip(cache, tmp_path):
    arch = tmp_path / "build.zip"
    with zipfile.ZipFile(arch, "w") as z:
        # i binari stanno in sottocartelle, come nelle build vere
        z.writestr("ffmpeg-master/bin/" + ffbin._exe("ffmpeg"), b"x")
        z.writestr("ffmpeg-master/bin/" + ffbin._exe("ffprobe"), b"y")
        z.writestr("ffmpeg-master/README.txt", b"niente")
    presi = ffbin._estrai(arch, cache)
    assert sorted(presi) == sorted(ffbin._exe(n) for n in ffbin.NAMES)
    assert all(ffbin.local(n) for n in ffbin.NAMES)


def test_estrae_da_tar(cache, tmp_path):
    dentro = tmp_path / "src"
    dentro.mkdir()
    for n in ffbin.NAMES:
        (dentro / ffbin._exe(n)).write_bytes(b"x")
    arch = tmp_path / "build.tar.xz"
    with tarfile.open(arch, "w:xz") as t:
        for n in ffbin.NAMES:
            t.add(dentro / ffbin._exe(n), arcname=f"ffmpeg-master/bin/{ffbin._exe(n)}")
    ffbin._estrai(arch, cache)
    assert all(ffbin.local(n) for n in ffbin.NAMES)


def test_install_scarica_ed_estrae(cache, tmp_path, monkeypatch):
    sorgente = tmp_path / "finta.zip"
    with zipfile.ZipFile(sorgente, "w") as z:
        for n in ffbin.NAMES:
            z.writestr(f"bin/{ffbin._exe(n)}", b"x")

    def finto_scarica(url, dest, progress=None):
        dest.write_bytes(sorgente.read_bytes())
        if progress:
            progress(1.0)

    monkeypatch.setattr(ffbin, "_scarica", finto_scarica)
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    visto: list[float] = []
    esito = ffbin.install(progress=visto.append)
    assert esito["stato"] == "installato"
    assert all(ffbin.local(n) for n in ffbin.NAMES)
    assert visto and visto[-1] == pytest.approx(1.0)


def test_piattaforma_sconosciuta_spiega_cosa_fare(cache, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Plan9")
    monkeypatch.setattr(platform, "machine", lambda: "sparc")
    with pytest.raises(RuntimeError, match="VEDIT_FFMPEG"):
        ffbin.install()


def test_archivio_senza_binari_non_passa_per_buono(cache, tmp_path, monkeypatch):
    vuoto = tmp_path / "vuoto.zip"
    with zipfile.ZipFile(vuoto, "w") as z:
        z.writestr("README", b"niente")
    monkeypatch.setattr(ffbin, "_scarica",
                        lambda url, dest, progress=None: dest.write_bytes(vuoto.read_bytes()))
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    with pytest.raises(RuntimeError, match="ffmpeg"):
        ffbin.install()


def test_ordine_di_ricerca(cache, monkeypatch):
    """Sistema prima, copia scaricata dopo: la build di sistema ha piu' encoder."""
    monkeypatch.delenv("VEDIT_FFMPEG", raising=False)
    scaricato = _finto(cache, "ffmpeg")

    monkeypatch.setattr(ffmpeg.shutil, "which", lambda n: "/usr/bin/ffmpeg")
    ffmpeg.forget()
    assert ffmpeg.binary("ffmpeg") == "/usr/bin/ffmpeg"

    monkeypatch.setattr(ffmpeg.shutil, "which", lambda n: None)
    ffmpeg.forget()
    assert ffmpeg.binary("ffmpeg") == str(scaricato)

    ffmpeg.forget()


def test_errore_dice_come_rimediare(cache, monkeypatch):
    monkeypatch.delenv("VEDIT_FFPROBE", raising=False)
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda n: None)
    ffmpeg.forget()
    with pytest.raises(FileNotFoundError, match="vedit install-ffmpeg"):
        ffmpeg.binary("ffprobe")
    ffmpeg.forget()
