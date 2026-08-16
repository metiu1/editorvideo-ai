"""Marker e snapshot: la memoria del montaggio."""

import subprocess

import pytest

from vedit import ffmpeg, versions
from vedit.store import Store


def _video(path, colore="red", durata=3.0):
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"color=c={colore}:s=320x180:r=25:d={durata}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(path),
    ], check=True, capture_output=True)
    return str(path)


@pytest.fixture
def progetto(tmp_path):
    s = Store.create("ver", "720p", path=str(tmp_path / "p.json"))
    m = s.import_media([_video(tmp_path / "a.mp4")])[0]
    s.add_clip(m.id, start=0.0, duration=2.0)
    return s, m


# --------------------------------------------------------------------------
# marker
# --------------------------------------------------------------------------


def test_marker_si_aggiunge_e_si_rilegge(progetto):
    s, _ = progetto
    versions.add_marker(s, 1.5, "qui manca il b-roll", "da_fare")
    tutti = versions.markers(s)
    assert len(tutti) == 1
    assert tutti[0]["t"] == 1.5 and tutti[0]["kind"] == "da_fare"
    assert "b-roll" in tutti[0]["note"]


def test_marker_sopravvive_al_salvataggio(progetto, tmp_path):
    s, _ = progetto
    versions.add_marker(s, 0.8, "controllare il colore", "problema")
    riaperto = Store.open(s.path)
    assert versions.markers(riaperto)[0]["note"] == "controllare il colore"


def test_marker_ordinati_per_tempo(progetto):
    s, _ = progetto
    versions.add_marker(s, 2.0, "secondo")
    versions.add_marker(s, 0.5, "primo")
    assert [m["note"] for m in versions.markers(s)] == ["primo", "secondo"]


def test_marker_filtro_per_tipo_e_tratto(progetto):
    s, _ = progetto
    versions.add_marker(s, 0.5, "a", "nota")
    versions.add_marker(s, 2.5, "b", "problema")
    assert [m["note"] for m in versions.markers(s, kind="problema")] == ["b"]
    assert [m["note"] for m in versions.markers(s, start=2.0)] == ["b"]
    assert [m["note"] for m in versions.markers(s, end=1.0)] == ["a"]


def test_marker_regione(progetto):
    s, _ = progetto
    m = versions.add_marker(s, 1.0, "tratto da rifare", "da_fare", duration=0.8)
    assert m["duration"] == 0.8
    # una regione che comincia prima dell'intervallo ma lo tocca deve comparire
    assert versions.markers(s, start=1.5)


def test_marker_kind_sbagliato(progetto):
    s, _ = progetto
    with pytest.raises(ValueError, match="sconosciuto"):
        versions.add_marker(s, 1.0, "x", "boh")


def test_marker_si_toglie_e_si_annulla(progetto):
    s, _ = progetto
    m = versions.add_marker(s, 1.0, "da togliere")
    versions.remove_marker(s, m["id"])
    assert versions.markers(s) == []
    s.undo()
    assert len(versions.markers(s)) == 1


def test_remove_marker_inesistente(progetto):
    s, _ = progetto
    with pytest.raises(ValueError, match="inesistente"):
        versions.remove_marker(s, "mk_nope")


# --------------------------------------------------------------------------
# snapshot
# --------------------------------------------------------------------------


def test_snapshot_non_tocca_il_montaggio(progetto):
    s, _ = progetto
    prima = s.project.to_dict()
    versions.snapshot(s, "versione A", "prima prova")
    assert s.project.to_dict() == prima


def test_snapshot_compare_nella_lista(progetto):
    s, _ = progetto
    versions.snapshot(s, "corta")
    versions.snapshot(s, "lunga", "con i titoli")
    nomi = {v["nome"] for v in versions.snapshots(s)}
    assert nomi == {"corta", "lunga"}
    lunga = next(v for v in versions.snapshots(s) if v["nome"] == "lunga")
    assert lunga["nota"] == "con i titoli" and lunga["clip"] == 1


def test_restore_riporta_indietro(progetto, tmp_path):
    s, m = progetto
    versions.snapshot(s, "A")
    s.add_clip(m.id, start=2.0, duration=1.0)
    assert len(s.project.tracks[0].clips) == 2

    versions.restore(s, "A")
    assert len(s.project.tracks[0].clips) == 1


def test_restore_si_annulla(progetto, tmp_path):
    s, m = progetto
    versions.snapshot(s, "A")
    s.add_clip(m.id, start=2.0, duration=1.0)
    versions.restore(s, "A")
    s.undo()
    assert len(s.project.tracks[0].clips) == 2, "il ripristino deve essere annullabile"


def test_restore_inesistente(progetto):
    s, _ = progetto
    with pytest.raises(ValueError, match="inesistente"):
        versions.restore(s, "mai_salvata")


def test_compare_vede_la_clip_aggiunta(progetto):
    s, m = progetto
    versions.snapshot(s, "A")
    s.add_clip(m.id, start=2.0, duration=1.0)
    d = versions.compare(s, "A")
    assert d["aggiunte"] == 1 and d["tolte"] == 0
    assert d["uguali"] is False
    assert d["durata"]["A"] == 2.0 and d["durata"]["corrente"] == 3.0


def test_compare_vede_lo_spostamento(progetto):
    s, _ = progetto
    versions.snapshot(s, "A")
    c = s.project.tracks[0].clips[0]
    s.move_clip(c.id, start=1.0)
    d = versions.compare(s, "A")
    assert d["modificate"] == 1
    dettaglio = d["dettaglio"]["modificate"][0]
    assert dettaglio["prima"]["start"] == 0.0 and dettaglio["dopo"]["start"] == 1.0


def test_compare_due_snapshot(progetto, tmp_path):
    s, m = progetto
    versions.snapshot(s, "A")
    s.add_clip(m.id, start=2.0, duration=1.0)
    versions.snapshot(s, "B")
    d = versions.compare(s, "A", "B")
    assert d["b"] == "B" and d["aggiunte"] == 1


def test_compare_identiche(progetto):
    s, _ = progetto
    versions.snapshot(s, "A")
    d = versions.compare(s, "A")
    assert d["uguali"] is True
    assert d["aggiunte"] == d["tolte"] == d["modificate"] == 0


def test_snapshot_nome_con_caratteri_strani(progetto):
    s, _ = progetto
    versions.snapshot(s, "prova/2: finale?")
    assert versions.snapshots(s)[0]["nome"] == "prova/2: finale?"


def test_snapshot_nome_vuoto(progetto):
    s, _ = progetto
    with pytest.raises(ValueError, match="vuoto"):
        versions.snapshot(s, "   ")


def test_snapshot_senza_progetto_su_disco():
    s = Store.create("in_memoria", "720p")
    with pytest.raises(ValueError, match="salvalo prima"):
        versions.snapshot(s, "A")
