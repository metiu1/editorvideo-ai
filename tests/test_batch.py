"""Modifiche in blocco: un undo solo, un salvataggio solo, tutto o niente."""

import pytest

from vedit import keyframes as kf
from vedit.store import EditError, Store


@pytest.fixture
def store(assets, tmp_path):
    s = Store.create("batch", "1080p", path=str(tmp_path / "p.json"))
    s.import_media([assets["red"], assets["blue"]])
    return s


def _ids(store):
    return [m.id for m in store.project.media]


# ---------------------------------------------------------------- add_clips
def test_add_clips_mette_tutto_in_una_modifica(store):
    a, b = _ids(store)
    passi = len(store._undo)
    clips = store.add_clips([
        {"media": a, "start": 0.0, "in": 1.0, "duration": 1.5},
        {"media": b, "start": 1.5, "in": 0.5, "duration": 2.0},
        {"media": a, "start": 3.5, "in": 3.0, "duration": 1.0},
    ])
    assert len(clips) == 3
    assert len(store._undo) == passi + 1, "tre clip devono costare un undo solo"

    store.undo()
    assert store.project.tracks[0].clips == []


def test_add_clips_rispetta_in_e_durata(store):
    a = _ids(store)[0]
    clips = store.add_clips([{"media": a, "start": 2.0, "in": 1.25, "duration": 0.75}])
    c = clips[0]
    assert c.start == 2.0 and c.in_ == 1.25 and c.duration == 0.75


def test_add_clips_accoda_senza_start(store):
    a, b = _ids(store)
    clips = store.add_clips([
        {"media": a, "duration": 1.0},
        {"media": b, "duration": 2.0},
        {"media": a, "duration": 0.5},
    ])
    assert [c.start for c in clips] == [0.0, 1.0, 3.0]


def test_add_clips_atomico_se_una_voce_e_sbagliata(store):
    """A meta' strada non si resta: o entra tutto o non cambia niente."""
    a = _ids(store)[0]
    prima = store.project.to_dict()
    with pytest.raises(EditError):
        store.add_clips([
            {"media": a, "duration": 1.0},
            {"media": "inesistente", "duration": 1.0},
        ])
    assert store.project.tracks[0].clips == []
    assert store.project.to_dict() == prima


def test_add_clips_voce_senza_media(store):
    with pytest.raises(EditError, match="manca 'media'"):
        store.add_clips([{"start": 0.0, "duration": 1.0}])


def test_add_clips_vuoto_non_fa_niente(store):
    passi = len(store._undo)
    assert store.add_clips([]) == []
    assert len(store._undo) == passi


def test_add_clips_su_piu_tracce(store):
    a = _ids(store)[0]
    clips = store.add_clips([
        {"media": a, "start": 0.0, "duration": 1.0},
        {"media": a, "start": 0.0, "duration": 1.0, "track": "V1"},
    ])
    assert len({c.id for c in clips}) == 2


# ---------------------------------------------------------------- batch()
def test_batch_salva_una_volta_sola(store, monkeypatch):
    a = _ids(store)[0]
    salvataggi = []
    monkeypatch.setattr(type(store), "save", lambda self: salvataggi.append(1))

    with store.batch():
        for i in range(5):
            store.add_clip(a, start=float(i), duration=0.5)
    assert len(salvataggi) == 1, "un blocco = un salvataggio"


def test_batch_annidato_resta_una_modifica(store):
    a = _ids(store)[0]
    passi = len(store._undo)
    with store.batch():
        store.add_clip(a, duration=1.0)
        with store.batch():
            store.add_clip(a, duration=1.0)
        store.add_clip(a, duration=1.0)
    assert len(store._undo) == passi + 1
    assert len(store.project.tracks[0].clips) == 3


def test_batch_ripristina_se_qualcosa_esplode(store):
    a = _ids(store)[0]
    store.add_clip(a, duration=1.0)
    prima = store.project.to_dict()
    with pytest.raises(RuntimeError):
        with store.batch():
            store.add_clip(a, start=5.0, duration=1.0)
            raise RuntimeError("boom")
    assert store.project.to_dict() == prima


# ---------------------------------------------------------------- move_effect
def test_move_effect_riordina_la_catena(store):
    store.add_effect(None, "sharpen", {"amount": 1.0})
    store.add_effect(None, "vignette", {})
    store.add_effect(None, "denoise", {"strength": 3})

    catena = store.move_effect(None, 2, 0)
    assert [e.type for e in catena] == ["denoise", "sharpen", "vignette"]


def test_move_effect_su_una_clip(store):
    a = _ids(store)[0]
    c = store.add_clip(a, duration=1.0)
    store.add_effect(c.id, "blur", {"sigma": 4})
    store.add_effect(c.id, "color", {"contrast": 1.2})
    catena = store.move_effect(c.id, 0, 1)
    assert [e.type for e in catena] == ["color", "blur"]


def test_move_effect_indice_fuori_range(store):
    store.add_effect(None, "grain", {})
    with pytest.raises(EditError, match="fuori range"):
        store.move_effect(None, 3, 0)


def test_move_effect_destinazione_viene_limitata(store):
    store.add_effect(None, "grain", {})
    store.add_effect(None, "blur", {})
    catena = store.move_effect(None, 0, 99)     # oltre la fine = in fondo
    assert [e.type for e in catena] == ["blur", "grain"]


def test_move_effect_fermo_non_tocca_la_cronologia(store):
    store.add_effect(None, "grain", {})
    passi = len(store._undo)
    store.move_effect(None, 0, 0)
    assert len(store._undo) == passi


# ---------------------------------------------------------------- coerce
def test_valori_animabili_arrivano_come_numeri(store):
    """Un client che manda "-3" non deve lasciare una stringa nel progetto."""
    a = _ids(store)[0]
    c = store.add_clip(a, duration=1.0)
    store.set_audio(c.id, gain_db="-3")
    assert c.audio.gain_db == -3.0
    assert isinstance(c.audio.gain_db, float)

    store.set_transform(c.id, scale="1.5")
    assert c.transform.scale == 1.5


def test_coerce_dentro_i_keyframe():
    v = kf.coerce({"kf": [{"t": "0", "v": "0"}, {"t": 2, "v": "1.5", "ease": "ease_in_out"}]})
    assert v["kf"][0]["t"] == 0.0 and v["kf"][0]["v"] == 0.0
    assert v["kf"][1]["v"] == 1.5
    assert v["kf"][1]["ease"] == "ease_in_out"


def test_coerce_lascia_stare_quello_che_non_e_numero():
    assert kf.coerce("rosso") == "rosso"
    assert kf.coerce(None) is None
    assert kf.coerce(True) is True
