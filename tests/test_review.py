"""Vedere il montaggio: contact sheet, forma d'onda, verifica del render."""

import subprocess

import pytest

from vedit import ffmpeg, review
from vedit.store import Store


@pytest.fixture(autouse=True)
def cache_isolata(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))


def _clip(path, colore, durata=2.0, audio=True):
    args = [ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={colore}:s=320x180:r=25:d={durata}"]
    if audio:
        args += ["-f", "lavfi", "-i",
                 f"sine=frequency=440:sample_rate=48000:duration={durata}"]
    args += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    if audio:
        args += ["-c:a", "aac", "-shortest"]
    subprocess.run(args + [str(path)], check=True, capture_output=True)
    return str(path)


@pytest.fixture
def montaggio(tmp_path):
    """Due clip di colore diverso attaccate: uno stacco netto a 2s."""
    s = Store.create("rev", "720p", path=str(tmp_path / "p.json"))
    s.set_settings(width=320, height=180)
    rosso = s.import_media([_clip(tmp_path / "rosso.mp4", "red")])[0]
    blu = s.import_media([_clip(tmp_path / "blu.mp4", "blue")])[0]
    s.add_clip(rosso.id, start=0.0, duration=2.0)
    s.add_clip(blu.id, start=2.0, duration=2.0)
    return s


# --------------------------------------------------------------------------
# campionamento
# --------------------------------------------------------------------------


def test_sample_times_evita_i_bordi(montaggio):
    t = review.sample_times(montaggio.project, 4)
    assert len(t) == 4
    assert t[0] > 0 and t[-1] < montaggio.project.duration()
    # nessun campione esattamente sullo stacco a 2.0
    assert all(abs(x - 2.0) > 1e-6 for x in t)


def test_sample_times_su_un_intervallo(montaggio):
    t = review.sample_times(montaggio.project, 3, start=2.0, end=4.0)
    assert all(2.0 <= x <= 4.0 for x in t)


def test_intervallo_vuoto(montaggio):
    with pytest.raises(ValueError, match="intervallo vuoto"):
        review.sample_times(montaggio.project, 3, start=3.0, end=1.0)


# --------------------------------------------------------------------------
# contact sheet
# --------------------------------------------------------------------------


def test_contact_sheet_genera_la_griglia(montaggio, tmp_path):
    from PIL import Image

    res = review.contact_sheet(montaggio.project, str(tmp_path / "sheet.jpg"),
                               count=6, width=160, cols=3)
    assert res["fotogrammi"] == 6
    assert res["griglia"] == [3, 2]
    img = Image.open(res["file"])
    assert img.size[0] == 160 * 3
    assert img.size[1] > 0


def test_contact_sheet_mostra_i_due_colori(montaggio, tmp_path):
    """La griglia deve contenere sia il rosso sia il blu: e' il senso del colpo d'occhio."""
    from PIL import Image

    res = review.contact_sheet(montaggio.project, str(tmp_path / "s.jpg"),
                               count=4, width=160, cols=4)
    img = Image.open(res["file"]).convert("RGB")
    w, h = img.size
    sinistra = img.crop((0, h // 2, w // 4, h // 2 + 1)).resize((1, 1)).getpixel((0, 0))
    destra = img.crop((w * 3 // 4, h // 2, w, h // 2 + 1)).resize((1, 1)).getpixel((0, 0))
    assert sinistra[0] > sinistra[2], f"primo riquadro non rosso: {sinistra}"
    assert destra[2] > destra[0], f"ultimo riquadro non blu: {destra}"


def test_contact_sheet_su_un_tratto(montaggio, tmp_path):
    res = review.contact_sheet(montaggio.project, str(tmp_path / "s.jpg"),
                               count=3, width=120, start=2.0, end=4.0)
    assert all(2.0 <= t <= 4.0 for t in res["tempi"])


# --------------------------------------------------------------------------
# anteprima guardabile
# --------------------------------------------------------------------------


def test_preview_clip_lascia_il_file(montaggio, tmp_path):
    res = review.preview_clip(montaggio.project, str(tmp_path / "prev.mp4"), height=120)
    from pathlib import Path
    assert Path(res["file"]).exists(), "l'anteprima deve restare: serve a guardarla"
    assert res["byte"] > 0
    assert abs(res["durata"] - 4.0) < 0.2
    assert res["troncata"] is False


def test_preview_clip_tronca_le_richieste_lunghe(montaggio, tmp_path):
    res = review.preview_clip(montaggio.project, str(tmp_path / "p.mp4"),
                              height=120, max_seconds=1.0)
    assert res["troncata"] is True
    assert abs(res["durata"] - 1.0) < 0.05
    assert "render_video" in res["nota"]


def test_preview_clip_su_un_tratto(montaggio, tmp_path):
    res = review.preview_clip(montaggio.project, str(tmp_path / "p.mp4"),
                              start=2.0, end=3.5, height=120)
    assert res["inizio"] == 2.0 and abs(res["durata"] - 1.5) < 0.05


# --------------------------------------------------------------------------
# scopes
# --------------------------------------------------------------------------


def test_scopes_riconosce_il_nero(tmp_path):
    s = Store.create("sc", "720p", path=str(tmp_path / "n.json"))
    s.set_settings(width=320, height=180)
    m = s.import_media([_clip(tmp_path / "nero.mp4", "black", audio=False)])[0]
    s.add_clip(m.id, duration=1.0)
    sc = review.scopes(s.project, 0.5)
    assert sc["luma"]["mediana"] < 20
    assert any("sottoesposta" in a for a in sc["avvisi"])
    assert sc["ok"] is False


def test_scopes_riconosce_il_bianco_bruciato(tmp_path):
    s = Store.create("sc", "720p", path=str(tmp_path / "b.json"))
    s.set_settings(width=320, height=180)
    m = s.import_media([_clip(tmp_path / "bianco.mp4", "white", audio=False)])[0]
    s.add_clip(m.id, duration=1.0)
    sc = review.scopes(s.project, 0.5)
    assert sc["clipping"]["alte_luci"] > 0.5
    assert any("bruciate" in a for a in sc["avvisi"])


def test_scopes_riconosce_la_dominante(tmp_path):
    s = Store.create("sc", "720p", path=str(tmp_path / "r.json"))
    s.set_settings(width=320, height=180)
    m = s.import_media([_clip(tmp_path / "rosso.mp4", "red", audio=False)])[0]
    s.add_clip(m.id, duration=1.0)
    sc = review.scopes(s.project, 0.5)
    assert sc["dominante"]["r"] > sc["dominante"]["b"]
    assert any("dominante rossa" in a for a in sc["avvisi"])


def test_scopes_immagine_piatta(tmp_path):
    s = Store.create("sc", "720p", path=str(tmp_path / "g.json"))
    s.set_settings(width=320, height=180)
    m = s.import_media([_clip(tmp_path / "grigio.mp4", "gray", audio=False)])[0]
    s.add_clip(m.id, duration=1.0)
    sc = review.scopes(s.project, 0.5)
    assert sc["luma"]["contrasto"] < 10
    assert any("piatta" in a for a in sc["avvisi"])


# --------------------------------------------------------------------------
# forma d'onda
# --------------------------------------------------------------------------


def test_waveform_legge_i_picchi(montaggio):
    w = review.waveform(montaggio.project, points=40)
    assert w["picchi"], "nessun picco letto"
    assert len(w["picchi"]) <= 40
    assert all(0.0 <= p <= 1.0 for p in w["picchi"])
    assert w["picco_db"] is not None and w["picco_db"] < 0.1


def test_waveform_riconosce_il_silenzio(montaggio, tmp_path):
    """Una clip senza audio deve risultare muta, non "forte"."""
    muta = montaggio.import_media([_clip(tmp_path / "muta.mp4", "green", audio=False)])[0]
    s2 = Store.create("muto", "720p", path=str(tmp_path / "p2.json"))
    m = s2.import_media([muta.path])[0]
    s2.add_clip(m.id, duration=2.0)
    w = review.waveform(s2.project, points=20)
    assert w["silenzio_ratio"] > 0.9 or not w["picchi"]


def test_waveform_su_un_intervallo(montaggio):
    w = review.waveform(montaggio.project, start=1.0, end=3.0, points=30)
    assert abs(w["durata"] - 2.0) < 0.05
    assert w["inizio"] == 1.0


# --------------------------------------------------------------------------
# verifica del render
# --------------------------------------------------------------------------


def test_expected_cuts_sono_i_bordi_delle_clip(montaggio):
    tagli = review.expected_cuts(montaggio.project, 0.0, 4.0)
    assert tagli == [2.0]


def test_expected_cuts_relativi_all_intervallo(montaggio):
    tagli = review.expected_cuts(montaggio.project, 1.0, 4.0)
    assert tagli == [1.0]          # lo stacco a 2.0 visto da 1.0 cade a 1.0


def test_verify_conferma_lo_stacco(montaggio):
    res = review.verify(montaggio.project)
    assert res["stacchi_attesi"] == [2.0]
    assert res["stacchi_confermati"], f"stacco non ritrovato nel render: {res}"
    assert abs(res["stacchi_confermati"][0]["scarto"]) <= review.CUT_TOLERANCE
    assert res["stacchi_mancanti"] == []
    assert abs(res["durata_misurata"] - res["durata_attesa"]) < 0.3


def test_verify_segnala_il_buco_nero(montaggio, tmp_path):
    """Una clip spostata lascia un buco: il render lo mostra come nero."""
    clips = sorted(montaggio.project.tracks[0].clips, key=lambda c: c.start)
    montaggio.move_clip(clips[1].id, start=3.0)     # buco tra 2 e 3
    res = review.verify(montaggio.project)
    assert res["nero"] > 0.1
    assert any("nero" in a for a in res["avvisi"])
    assert res["ok"] is False


def test_verify_su_un_tratto_senza_stacchi(montaggio):
    res = review.verify(montaggio.project, start=0.0, end=1.8)
    assert res["stacchi_attesi"] == []
    assert res["ok"] is True, res["avvisi"]
