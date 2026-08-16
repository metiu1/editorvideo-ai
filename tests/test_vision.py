"""Rilevamento del soggetto e movimenti di camera derivati."""

import subprocess

import pytest

from vedit import ffmpeg, vision


@pytest.fixture(autouse=True)
def cache_isolata(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))


def _traccia(*punti) -> list[dict]:
    """(t, cx, cy) -> traccia; cx None = soggetto non visto."""
    return [{"t": t, "cx": cx, "cy": cy,
             "box": None if cx is None else {"x": cx - 50, "y": cy - 100,
                                             "w": 100, "h": 200, "conf": 0.9,
                                             "classe": "person"}}
            for t, cx, cy in punti]


# --------------------------------------------------------------------------
# scelta del soggetto
# --------------------------------------------------------------------------


def test_main_subject_prende_il_piu_grande():
    frames = [{"t": 0.0, "box": [
        {"classe": "person", "conf": 0.9, "x": 0, "y": 0, "w": 20, "h": 20},
        {"classe": "person", "conf": 0.8, "x": 100, "y": 100, "w": 200, "h": 200},
    ]}]
    out = vision.main_subject(frames)
    assert out[0]["cx"] == 200 and out[0]["cy"] == 200


def test_main_subject_senza_rilevamenti():
    out = vision.main_subject([{"t": 0.5, "box": []}])
    assert out[0]["cx"] is None and out[0]["box"] is None


def test_fill_gaps_tiene_l_ultima_posizione():
    t = vision.fill_gaps(_traccia((0, 100, 50), (0.5, None, None), (1, 200, 60)))
    assert t[1]["cx"] == 100


def test_fill_gaps_riempie_anche_l_inizio():
    t = vision.fill_gaps(_traccia((0, None, None), (0.5, 300, 90)))
    assert t[0]["cx"] == 300


def test_fill_gaps_tutto_vuoto_resta_vuoto():
    t = vision.fill_gaps(_traccia((0, None, None), (0.5, None, None)))
    assert all(p["cx"] is None for p in t)


# --------------------------------------------------------------------------
# levigatura: e' quella che rende guardabile il reframe
# --------------------------------------------------------------------------


def test_smooth_toglie_il_tremolio():
    ballerina = _traccia((0, 100, 50), (0.5, 160, 50), (1.0, 100, 50),
                         (1.5, 160, 50), (2.0, 100, 50))
    liscia = vision.smooth(ballerina, window=5)
    escursione_prima = max(p["cx"] for p in ballerina) - min(p["cx"] for p in ballerina)
    escursione_dopo = max(p["cx"] for p in liscia) - min(p["cx"] for p in liscia)
    assert escursione_dopo < escursione_prima / 2


def test_smooth_segue_comunque_il_movimento_vero():
    corsa = _traccia(*[(i * 0.5, 100 + i * 100, 50) for i in range(8)])
    liscia = vision.smooth(corsa, window=3)
    assert liscia[-1]["cx"] > liscia[0]["cx"] + 500


def test_smooth_window_1_non_cambia_nulla():
    t = _traccia((0, 100, 50), (0.5, 200, 60))
    assert [p["cx"] for p in vision.smooth(t, window=1)] == [100, 200]


# --------------------------------------------------------------------------
# reframe
# --------------------------------------------------------------------------


def test_reframe_scala_per_coprire_il_verticale():
    kf = vision.reframe_keyframes(_traccia((0, 960, 540)), 1920, 1080, 1080, 1920)
    assert kf["scale"] == pytest.approx(1920 / 1080, abs=1e-3)
    # soggetto gia' al centro: nessuna panoramica
    assert abs(kf["x"]["kf"][0]["v"]) < 1e-6


def test_reframe_segue_il_soggetto():
    kf = vision.reframe_keyframes(_traccia((0, 1500, 540)), 1920, 1080, 1080, 1920)
    assert kf["x"]["kf"][0]["v"] < 0, "il soggetto a destra va riportato al centro"


def test_reframe_non_esce_dai_bordi():
    kf = vision.reframe_keyframes(
        _traccia((0, 0, 540), (0.5, 1920, 540)), 1920, 1080, 1080, 1920)
    limite = kf["limite_x"]
    assert all(abs(p["v"]) <= limite + 1e-6 for p in kf["x"]["kf"])
    assert limite > 0


def test_reframe_verticale_verso_orizzontale():
    kf = vision.reframe_keyframes(_traccia((0, 540, 960)), 1080, 1920, 1920, 1080)
    assert kf["scale"] > 1.0
    assert kf["limite_y"] > 0      # qui la panoramica utile e' verticale


def test_reframe_salta_i_punti_senza_soggetto():
    kf = vision.reframe_keyframes(_traccia((0, None, None), (0.5, 960, 540)),
                                  1920, 1080, 1080, 1920)
    assert len(kf["x"]["kf"]) == 1


# --------------------------------------------------------------------------
# maschera che segue
# --------------------------------------------------------------------------


def test_mask_keyframes_riquadro_con_margine():
    m = vision.mask_keyframes(_traccia((0, 500, 300), (0.5, 600, 300)), padding=1.5)
    assert m["w"] == 150 and m["h"] == 300
    # x e' l'angolo, non il centro
    assert m["x"]["kf"][0]["v"] == pytest.approx(500 - 75, abs=0.1)


def test_mask_keyframes_senza_soggetto():
    with pytest.raises(vision.VisionError, match="nessun soggetto"):
        vision.mask_keyframes(_traccia((0, None, None)))


# --------------------------------------------------------------------------
# integrazione: YOLO su un'immagine con persone vere
# --------------------------------------------------------------------------


@pytest.fixture
def video_con_persone(tmp_path):
    """L'asset di ultralytics (una fermata dell'autobus con passanti) come video."""
    from ultralytics.utils import ASSETS

    out = tmp_path / "persone.mp4"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-i", str(ASSETS / "bus.jpg"), "-t", "2",
        "-vf", "scale=640:-2,fps=25", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    return str(out)


@pytest.mark.slow
def test_detect_trova_le_persone(video_con_persone):
    res = vision.detect(video_con_persone, fps=1.0, width=480)
    assert res["fotogrammi"], "nessun fotogramma analizzato"
    assert "person" in res["classi"], res["classi"]
    box = res["fotogrammi"][0]["box"]
    assert box and all(b["classe"] == "person" for b in box)
    # coordinate riportate al video originale, non a quelle di analisi
    assert all(0 <= b["x"] <= res["larghezza"] for b in box)
    assert all(b["w"] <= res["larghezza"] for b in box)


@pytest.mark.slow
def test_follow_da_una_traccia_utilizzabile(video_con_persone):
    res = vision.follow(video_con_persone, fps=1.0, width=480)
    assert res["copertura"] > 0.5
    assert all(p["cx"] is not None for p in res["traccia"])
    kf = vision.reframe_keyframes(res["traccia"], res["larghezza"], res["altezza"],
                                  1080, 1920)
    assert kf["x"]["kf"], "nessun keyframe di panoramica"


@pytest.mark.slow
def test_detect_filtra_le_classi(video_con_persone):
    res = vision.detect(video_con_persone, classes=("bus",), fps=1.0, width=480)
    assert all(b["classe"] == "bus" for f in res["fotogrammi"] for b in f["box"])


def test_modello_finisce_nella_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "c"))
    p = vision.model_path()
    assert p.endswith("yolo11n.pt")
    assert (tmp_path / "c" / "models" / "yolo11n.pt").exists()
