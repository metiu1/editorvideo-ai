"""Battito e struttura della musica: BPM, fase, griglia su cui montare."""

import subprocess

import pytest

from vedit import analyze, ffmpeg


@pytest.fixture(autouse=True)
def cache_isolata(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))


def _clic(path, bpm: float, durata: float = 20.0, offset: float = 0.0):
    """Traccia con un colpo secco a ogni battito: BPM noto per costruzione."""
    periodo = 60.0 / bpm
    # impulso corto e ripetuto: aphasher no, basta un seno spento in fretta
    espressione = (f"sin(2*PI*880*t)*exp(-40*mod(t+{offset:.6f},{periodo:.6f}))")
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"aevalsrc='{espressione}':s=44100:d={durata}",
        "-c:a", "pcm_s16le", str(path),
    ], check=True, capture_output=True)
    return str(path)


def test_bpm_riconosciuto(tmp_path):
    f = _clic(tmp_path / "clic120.wav", 120.0)
    b = analyze.beats(f)
    assert b["bpm"] == pytest.approx(120.0, abs=2.0)
    assert b["beat"] == pytest.approx(0.5, abs=0.01)
    assert b["bar"] == pytest.approx(2.0, abs=0.04)


def test_bpm_distingue_due_tempi(tmp_path):
    lento = analyze.beats(_clic(tmp_path / "a.wav", 90.0))
    veloce = analyze.beats(_clic(tmp_path / "b.wav", 150.0))
    assert lento["bpm"] < veloce["bpm"]
    assert lento["bpm"] == pytest.approx(90.0, abs=3.0)
    assert veloce["bpm"] == pytest.approx(150.0, abs=3.0)


def test_la_fase_trova_il_primo_battito(tmp_path):
    """Il tempo giusto nel posto sbagliato e' comunque una griglia sbagliata."""
    f = _clic(tmp_path / "sfasato.wav", 120.0, offset=0.25)
    b = analyze.beats(f)
    periodo = b["beat"]
    # i colpi cadono a 0.25, 0.75, ...: l'offset trovato deve coincidere a meno
    # di un battito intero
    scarto = min(abs(b["offset"] - 0.25), abs(b["offset"] - 0.25 + periodo),
                 abs(b["offset"] - 0.25 - periodo))
    assert scarto < 0.08, f"fase sbagliata: offset={b['offset']}"


def test_griglia_cade_sui_battiti(tmp_path):
    f = _clic(tmp_path / "griglia.wav", 120.0)
    b = analyze.beats(f)
    g = analyze.beat_grid(f, 0, 10)
    assert len(g) > 15
    passi = [round(y - x, 3) for x, y in zip(g, g[1:])]
    assert all(abs(p - b["beat"]) < 1e-3 for p in passi)


def test_griglia_ogni_misura(tmp_path):
    f = _clic(tmp_path / "misure.wav", 120.0)
    b = analyze.beats(f)
    misure = analyze.beat_grid(f, 0, 10, every=4)
    passi = [round(y - x, 3) for x, y in zip(misure, misure[1:])]
    assert all(abs(p - b["bar"]) < 1e-3 for p in passi)


def test_griglia_parte_dall_intervallo_chiesto(tmp_path):
    f = _clic(tmp_path / "intervallo.wav", 120.0)
    g = analyze.beat_grid(f, 5.0, 8.0)
    assert g[0] >= 5.0 - 1e-6
    assert g[-1] <= 8.0 + 1e-6
    assert g, "l'intervallo non deve uscire vuoto"


def test_profilo_segue_l_energia(tmp_path):
    """Il profilo serve a trovare lo stacco: deve vedere il silenzio."""
    f = tmp_path / "dinamica.wav"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi",
        "-i", "aevalsrc='sin(2*PI*440*t)*if(gt(mod(t,16),8),1,0.05)':s=44100:d=32",
        "-c:a", "pcm_s16le", str(f),
    ], check=True, capture_output=True)

    b = analyze.beats(str(f), block=4.0)
    prof = {p["t"]: p["energia"] for p in b["profilo"]}
    assert prof[0.0] < 0.3, "il tratto piano deve risultare piano"
    assert prof[12.0] > 0.8, "il tratto forte deve risultare forte"
    assert max(prof.values()) == pytest.approx(1.0)


def test_traccia_muta_lo_dice(tmp_path):
    f = tmp_path / "corta.wav"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "anullsrc=r=44100:d=0.2", "-c:a", "pcm_s16le", str(f),
    ], check=True, capture_output=True)
    with pytest.raises(analyze.AnalysisError):
        analyze.beats(str(f))


def test_la_misura_va_in_cache(tmp_path, monkeypatch):
    f = _clic(tmp_path / "cache.wav", 128.0)
    primo = analyze.beats(f)

    def esplodi(*a, **k):
        raise AssertionError("la seconda chiamata deve leggere dalla cache")

    monkeypatch.setattr(analyze.subprocess, "run", esplodi)
    assert analyze.beats(f) == primo
