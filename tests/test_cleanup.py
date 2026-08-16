"""Taglio di silenzi ed esitazioni sulla timeline."""

import subprocess

import pytest

from vedit import cleanup, ffmpeg
from vedit.store import Store


@pytest.fixture(autouse=True)
def cache_isolata(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))


@pytest.fixture
def parlato(tmp_path):
    """Tono 0-1s, silenzio 1-3s, tono 3-4s: una pausa lunga in mezzo."""
    out = tmp_path / "parlato.mp4"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=320x180:r=25:d=4",
        "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1,apad=pad_dur=2[s1];"
        "sine=frequency=440:duration=1[s2];[s1][s2]concat=n=2:v=0:a=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(out),
    ], check=True, capture_output=True)
    return str(out)


@pytest.fixture
def progetto(tmp_path, parlato):
    s = Store.create("pulizia", "1080p", path=str(tmp_path / "p.json"))
    m = s.import_media([parlato])[0]
    c = s.add_clip(m.id, duration=4.0)
    return s, c.id


# --------------------------------------------------------------------------
# utilita' sugli intervalli
# --------------------------------------------------------------------------


def test_merge_spans_unisce_e_ordina():
    assert cleanup.merge_spans([(2, 3), (0, 1), (0.98, 1.5)]) == [(0.0, 1.5), (2.0, 3.0)]


def test_merge_spans_scarta_i_vuoti():
    assert cleanup.merge_spans([(1, 1), (2, 1.5)]) == []


def test_invert_spans():
    assert cleanup.invert_spans([(1, 2)], 4) == [(0.0, 1.0), (2.0, 4.0)]
    assert cleanup.invert_spans([], 3) == [(0.0, 3.0)]
    assert cleanup.invert_spans([(0, 3)], 3) == []


# --------------------------------------------------------------------------
# taglio sulla timeline
# --------------------------------------------------------------------------


def test_cut_interno_spezza_la_clip(progetto):
    s, cid = progetto
    res = cleanup.cut_ranges(s, cid, [(1.0, 2.0)])
    assert res["tagli"] == 1
    assert abs(res["secondi_tolti"] - 1.0) < 0.01
    clips = s.project.tracks[0].clips
    assert len(clips) == 2
    assert abs(sum(c.duration for c in clips) - 3.0) < 0.01


def test_cut_con_ripple_non_lascia_buchi(progetto):
    s, cid = progetto
    cleanup.cut_ranges(s, cid, [(1.0, 2.0)], ripple=True)
    clips = sorted(s.project.tracks[0].clips, key=lambda c: c.start)
    assert abs(clips[0].start) < 1e-6
    assert abs(clips[1].start - clips[0].end) < 1e-6


def test_cut_senza_ripple_lascia_il_buco(progetto):
    s, cid = progetto
    cleanup.cut_ranges(s, cid, [(1.0, 2.0)], ripple=False)
    clips = sorted(s.project.tracks[0].clips, key=lambda c: c.start)
    assert clips[1].start > clips[0].end + 0.5


def test_cut_in_testa_sposta_il_punto_di_attacco(progetto):
    s, cid = progetto
    cleanup.cut_ranges(s, cid, [(0.0, 1.0)])
    _, c = s.clip_or_die(cid)
    assert abs(c.in_ - 1.0) < 0.01
    assert abs(c.duration - 3.0) < 0.01


def test_cut_in_coda_accorcia(progetto):
    s, cid = progetto
    cleanup.cut_ranges(s, cid, [(3.0, 4.0)])
    _, c = s.clip_or_die(cid)
    assert abs(c.in_) < 1e-6
    assert abs(c.duration - 3.0) < 0.01


def test_cut_multipli_restano_coerenti(progetto):
    s, cid = progetto
    res = cleanup.cut_ranges(s, cid, [(0.5, 1.0), (2.0, 2.5), (3.0, 3.4)])
    assert res["tagli"] == 3
    clips = s.project.tracks[0].clips
    totale = sum(c.duration for c in clips)
    assert abs(totale - (4.0 - 1.4)) < 0.05
    # nessuna sovrapposizione
    ordinate = sorted(clips, key=lambda c: c.start)
    for a, b in zip(ordinate, ordinate[1:]):
        assert b.start >= a.end - 1e-6


def test_cut_che_copre_tutto_rimuove_la_clip(progetto):
    s, cid = progetto
    res = cleanup.cut_ranges(s, cid, [(0.0, 4.0)])
    assert res["clip"] == []
    assert s.project.tracks[0].clips == []


def test_cut_ignora_intervalli_troppo_corti(progetto):
    s, cid = progetto
    res = cleanup.cut_ranges(s, cid, [(1.0, 1.01)])
    assert res["tagli"] == 0
    assert len(s.project.tracks[0].clips) == 1


def test_cut_si_annulla_con_undo(progetto):
    s, cid = progetto
    cleanup.cut_ranges(s, cid, [(1.0, 2.0)])
    assert len(s.project.tracks[0].clips) == 2
    while len(s.project.tracks[0].clips) > 1:
        s.undo()
    _, c = s.clip_or_die(cid)
    assert abs(c.duration - 4.0) < 0.01


# --------------------------------------------------------------------------
# calcolo degli intervalli dal parlato
# --------------------------------------------------------------------------


def test_speech_spans_trova_la_pausa(progetto, parlato):
    s, cid = progetto
    _, c = s.clip_or_die(cid)
    spans = cleanup.speech_spans_to_cut(parlato, c, min_silence=0.5, fillers=False)
    assert spans, "la pausa di 2s non e' stata trovata"
    a, b = spans[0]
    assert 0.9 < a < 1.5 and 2.5 < b < 3.2, spans


def test_speech_spans_rispetta_pad(progetto, parlato):
    s, cid = progetto
    _, c = s.clip_or_die(cid)
    stretto = cleanup.speech_spans_to_cut(parlato, c, pad=0.05, fillers=False)
    largo = cleanup.speech_spans_to_cut(parlato, c, pad=0.4, fillers=False)
    assert (stretto[0][1] - stretto[0][0]) > (largo[0][1] - largo[0][0])


def test_tighten_accorcia_davvero(progetto, parlato):
    s, cid = progetto
    res = cleanup.tighten(s, cid, min_silence=0.5, fillers=False)
    assert res["secondi_tolti"] > 1.0
    assert res["durata_dopo"] < res["durata_prima"]
    assert abs(sum(c.duration for c in s.project.tracks[0].clips)
               - res["durata_dopo"]) < 0.1


def test_tighten_rifiuta_una_clip_di_testo(tmp_path):
    s = Store.create("t", "1080p", path=str(tmp_path / "p.json"))
    c = s.add_text("ciao", duration=2)
    with pytest.raises(ValueError, match="sorgente"):
        cleanup.tighten(s, c.id)


def test_fillers_solo_esitazioni_pure():
    from vedit import analyze
    assert "ehm" in analyze.FILLERS
    # whisper rende spesso "ehm" come una "m" isolata: verificato su parlato vero
    assert "m" in analyze.FILLERS and "um" in analyze.FILLERS
    # parole vere: non devono stare nella lista predefinita
    assert not {"tipo", "cioe", "allora", "insomma"} & set(analyze.FILLERS)


def test_filler_match_ignora_la_punteggiatura(monkeypatch):
    """Whisper restituisce "Um," con la virgola: deve comunque essere trovata."""
    from vedit import analyze
    finta = {"segments": [{"start": 0, "end": 2, "text": "Um, ciao", "words": [
        {"w": "Um,", "t": 0.1, "e": 0.4, "p": 0.9},
        {"w": "ciao", "t": 0.5, "e": 0.9, "p": 0.9},
    ]}]}
    monkeypatch.setattr(analyze, "transcribe", lambda *a, **k: finta)
    spans = analyze.filler_spans("x.wav")
    assert len(spans) == 1 and spans[0]["word"] == "Um,"
