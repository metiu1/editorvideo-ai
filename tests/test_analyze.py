"""Analisi del materiale e maschere di censura."""

import subprocess

import pytest

from vedit import analyze
from vedit import effects as fx
from vedit import ffmpeg


@pytest.fixture(autouse=True)
def cache_isolata(tmp_path, monkeypatch):
    """L'analisi e' cache-ata su disco: ogni test parte da una cache vuota."""
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))


def _gen(path, args):
    subprocess.run([ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    *args, str(path)], check=True, capture_output=True)
    return str(path)


@pytest.fixture
def con_stacco(tmp_path):
    """Due secondi di nero poi due di testsrc: uno stacco netto a 2s."""
    return _gen(tmp_path / "stacco.mp4", [
        "-f", "lavfi", "-i",
        "color=c=black:s=320x180:r=25:d=2,setpts=PTS-STARTPTS[a];"
        "testsrc2=s=320x180:r=25:d=2[b];[a][b]concat=n=2:v=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    ])


@pytest.fixture
def con_silenzio(tmp_path):
    """Silenzio 0-2s, tono 2-4s."""
    return _gen(tmp_path / "sil.m4a", [
        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=2",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
        "-c:a", "aac",
    ])


# --------------------------------------------------------------------------
# misure
# --------------------------------------------------------------------------


def test_scenes_trova_lo_stacco(con_stacco):
    cuts = analyze.scenes(con_stacco)
    assert cuts[0] == 0.0
    assert any(1.5 < t < 2.5 for t in cuts), cuts


def test_scenes_usa_la_cache(con_stacco):
    primo = analyze.scenes(con_stacco)
    assert analyze.scenes(con_stacco) == primo


def test_silences_trova_il_muto(con_silenzio):
    sil = analyze.silences(con_silenzio)
    assert sil, "nessun silenzio rilevato"
    inizio, fine = sil[0]
    assert inizio < 0.5 and 1.5 < fine < 2.5, sil


def test_frame_stats_luminanza_e_fuoco(con_stacco):
    st = analyze.frame_stats(con_stacco)
    assert st, "nessun campione"
    nero = [s for s in st if s["t"] < 1.5]
    dopo = [s for s in st if s["t"] > 2.5]
    assert all(s["brightness"] < analyze.DARK_LEVEL for s in nero)
    # testsrc2 e' pieno di dettaglio: il fuoco deve essere molto piu' alto
    assert max(s["focus"] for s in dopo) > max(s["focus"] for s in nero)


def test_dead_ranges_trova_il_nero(con_stacco):
    dead = analyze.dead_ranges(con_stacco)
    assert any(a < 0.5 and b > 1.0 for a, b in dead["black"]), dead


# --------------------------------------------------------------------------
# giudizio
# --------------------------------------------------------------------------


def test_report_scarta_una_clip_tutta_nera(tmp_path):
    nero = _gen(tmp_path / "nero.mp4", [
        "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=3",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
    ])
    r = analyze.report(nero)
    assert r["verdict"] == "drop"
    assert r["issues"]


def test_report_tiene_una_clip_buona(assets):
    r = analyze.report(assets["blue"])
    assert r["verdict"] in ("keep", "trim")
    assert r["measures"]["black"] < 0.2


def test_report_suggerisce_il_taglio_in_testa(con_stacco):
    r = analyze.report(con_stacco)
    assert r["suggested_in"] > 1.0, r
    assert r["suggested_out"] > r["suggested_in"]


# --------------------------------------------------------------------------
# maschere e censura
# --------------------------------------------------------------------------


def test_parse_ranges():
    assert fx.parse_ranges("1.2-1.8;4-4.5") == [(1.2, 1.8), (4.0, 4.5)]
    assert fx.parse_ranges("") == []
    assert fx.parse_ranges("3-2") == []          # intervallo vuoto, scartato
    assert fx.parse_ranges("bad;1-2") == [(1.0, 2.0)]


def test_enable_solo_con_intervalli():
    c = fx.Ctx()
    assert fx.enable_expr({}, c) == ""
    e = fx.enable_expr({"ranges": "1-2"}, c)
    assert e.startswith(":enable='between(t,1,2)")


def _render_chain(chain: list[str], durata: float = 0.2) -> None:
    """Passa la catena a ffmpeg per davvero: se il filtro e' malformato, esplode."""
    vf = ",".join(chain)
    ffmpeg.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=s=320x180:r=25:d={durata}",
        "-vf", vf, "-frames:v", "3", "-f", "null", "-",
    ], timeout=120)


@pytest.mark.parametrize("effetto,params", [
    ("mask_blur", {"x": 40, "y": 20, "w": 100, "h": 80, "sigma": 12}),
    ("mask_pixelate", {"x": 10, "y": 10, "w": 64, "h": 64, "size": 8}),
    ("mask_box", {"x": 0, "y": 0, "w": 120, "h": 40, "color": "black"}),
])
def test_maschere_sono_filtri_validi(effetto, params):
    chain = fx.EFFECTS[effetto].build(params, fx.Ctx(width=320, height=180))
    _render_chain(chain)


def test_maschera_animata_segue_i_keyframe():
    kf = {"kf": [{"t": 0, "v": 0}, {"t": 1, "v": 200, "ease": "ease_in_out"}]}
    chain = fx.EFFECTS["mask_blur"].build(
        {"x": kf, "y": 20, "w": 80, "h": 80}, fx.Ctx(width=320, height=180))
    assert "t" in chain[0]          # l'espressione dipende dal tempo
    _render_chain(chain, 1.0)


def test_maschera_solo_negli_intervalli():
    chain = fx.EFFECTS["mask_box"].build(
        {"x": 0, "y": 0, "w": 100, "h": 50, "ranges": "0.05-0.1"},
        fx.Ctx(width=320, height=180))
    assert "enable=" in chain[0]
    _render_chain(chain)


def test_censura_audio_e_un_filtro_valido():
    for mode in ("mute", "scramble"):
        chain = fx.EFFECTS["censor"].build({"ranges": "0.1-0.3", "mode": mode}, fx.Ctx())
        assert chain
        ffmpeg.run([
            ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
            "-af", ",".join(chain), "-f", "null", "-",
        ], timeout=120)


def test_censura_senza_intervalli_non_fa_nulla():
    assert fx.EFFECTS["censor"].build({"ranges": ""}, fx.Ctx()) == []


def test_maschere_dichiarate_nel_registro():
    nomi = {d["name"] for d in fx.describe()}
    assert {"mask_blur", "mask_pixelate", "mask_box", "censor"} <= nomi
    # i parametri animabili devono essere dichiarati tali, altrimenti la
    # validazione rifiuta i keyframe
    mb = fx.EFFECTS["mask_blur"]
    assert mb.param("x").anim and mb.param("y").anim


def test_ranges_expr():
    spans = [{"start": 1.234, "end": 1.9}, {"start": 4, "end": 4.5}]
    assert analyze.ranges_expr(spans) == "1.234-1.900;4.000-4.500"


def test_censor_spans_richiede_whisper(monkeypatch, assets):
    """Senza faster-whisper l'errore deve dire cosa installare."""
    import builtins
    reale = builtins.__import__

    def finto(name, *a, **k):
        if name.startswith("faster_whisper"):
            raise ImportError("no")
        return reale(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", finto)
    with pytest.raises(analyze.AnalysisError, match="faster-whisper"):
        analyze.transcribe(assets["red"])
