"""Color matching: le statistiche devono avvicinarsi davvero dopo la correzione."""

import subprocess

import pytest

from vedit import colormatch
from vedit import effects as fx
from vedit import ffmpeg


def _gen(path, filtro=None, sorgente="testsrc2=s=320x180:r=25:d=1"):
    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", sorgente]
    if filtro:
        args += ["-vf", filtro]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(args, check=True, capture_output=True)
    return str(path)


@pytest.fixture
def coppia(tmp_path):
    """Stessa immagine, una scura e fredda: il caso "due camere diverse"."""
    rif = _gen(tmp_path / "rif.mp4")
    storta = _gen(tmp_path / "storta.mp4",
                  "eq=brightness=-0.18:contrast=0.75,colorbalance=bs=0.3:rs=-0.2")
    return storta, rif


def _applica(src, params, out):
    chain = fx.EFFECTS["colormatch"].build(params, fx.Ctx(width=320, height=180))
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-i", src, "-vf", ",".join(chain),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out),
    ], check=True, capture_output=True)
    return str(out)


# --------------------------------------------------------------------------
# misure
# --------------------------------------------------------------------------


def test_stats_su_un_colore_noto(tmp_path):
    rosso = _gen(tmp_path / "rosso.mp4", sorgente="color=c=red:s=320x180:r=25:d=1")
    s = colormatch.stats(rosso)
    assert s["mean"][0] > 0.8 and s["mean"][1] < 0.2 and s["mean"][2] < 0.2
    assert s["frames"] > 0


def test_stats_file_vuoto(tmp_path):
    vuoto = tmp_path / "vuoto.mp4"
    vuoto.write_bytes(b"")
    with pytest.raises(Exception):
        colormatch.stats(str(vuoto))


def test_distance_zero_su_se_stessa(coppia):
    storta, _ = coppia
    s = colormatch.stats(storta)
    assert colormatch.distance(s, s) == 0.0


# --------------------------------------------------------------------------
# parametri
# --------------------------------------------------------------------------


def test_match_params_identita_se_uguali():
    s = {"mean": [0.5, 0.5, 0.5], "std": [0.2, 0.2, 0.2]}
    p = colormatch.match_params(s, s)
    assert all(abs(p[f"{ch}_gain"] - 1.0) < 1e-6 for ch in "rgb")
    assert all(abs(p[f"{ch}_off"]) < 1e-6 for ch in "rgb")


def test_match_params_strength_zero_non_cambia_nulla():
    a = {"mean": [0.2, 0.2, 0.2], "std": [0.1, 0.1, 0.1]}
    b = {"mean": [0.7, 0.6, 0.5], "std": [0.3, 0.3, 0.3]}
    p = colormatch.match_params(a, b, strength=0.0)
    assert all(abs(p[f"{ch}_gain"] - 1.0) < 1e-6 and abs(p[f"{ch}_off"]) < 1e-6
               for ch in "rgb")


def test_match_params_clip_piatta_non_esplode():
    piatta = {"mean": [0.5, 0.5, 0.5], "std": [0.0, 0.0, 0.0]}
    rif = {"mean": [0.5, 0.5, 0.5], "std": [0.25, 0.25, 0.25]}
    p = colormatch.match_params(piatta, rif)
    assert all(p[f"{ch}_gain"] <= colormatch.GAIN_MAX for ch in "rgb")


def test_match_params_alza_una_clip_scura():
    scura = {"mean": [0.2, 0.2, 0.2], "std": [0.1, 0.1, 0.1]}
    chiara = {"mean": [0.6, 0.6, 0.6], "std": [0.2, 0.2, 0.2]}
    p = colormatch.match_params(scura, chiara)
    assert p["r_gain"] > 1.0 and p["r_off"] > 0.0


# --------------------------------------------------------------------------
# il test che conta: dopo la correzione la distanza deve scendere
# --------------------------------------------------------------------------


def test_correzione_avvicina_le_due_clip(coppia, tmp_path):
    storta, rif = coppia
    res = colormatch.match(storta, rif)
    corretta = _applica(storta, res["params"], tmp_path / "corretta.mp4")

    dopo = colormatch.distance(colormatch.stats(corretta), colormatch.stats(rif))
    assert dopo < res["distanza_prima"] * 0.5, (
        f"prima {res['distanza_prima']}, dopo {dopo}: la correzione non ha aiutato")


def test_strength_parziale_corregge_meno(coppia, tmp_path):
    storta, rif = coppia
    piena = colormatch.match(storta, rif, strength=1.0)
    meta = colormatch.match(storta, rif, strength=0.5)
    d_piena = colormatch.distance(
        colormatch.stats(_applica(storta, piena["params"], tmp_path / "p.mp4")),
        colormatch.stats(rif))
    d_meta = colormatch.distance(
        colormatch.stats(_applica(storta, meta["params"], tmp_path / "m.mp4")),
        colormatch.stats(rif))
    assert d_piena < d_meta < piena["distanza_prima"]


def test_effetto_colormatch_e_un_filtro_valido():
    chain = fx.EFFECTS["colormatch"].build(
        {"r_gain": 1.2, "r_off": 0.05, "g_gain": 1.0, "g_off": 0.0,
         "b_gain": 0.8, "b_off": -0.03}, fx.Ctx())
    assert chain[0].startswith("lutrgb=")
    assert "val*0.8-7.65" in chain[0], "offset negativo scritto male"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=0.2",
        "-vf", chain[0], "-frames:v", "3", "-f", "null", "-",
    ], check=True, capture_output=True, timeout=120)


def test_colormatch_nel_registro():
    d = fx.EFFECTS["colormatch"]
    assert {p.name for p in d.params} == {f"{ch}_{k}" for ch in "rgb"
                                          for k in ("gain", "off")}
