"""Sottotitoli: raggruppamento, formati, karaoke, burn-in."""

import subprocess

import pytest

from vedit import captions
from vedit import effects as fx
from vedit import ffmpeg


def _tr(*parole) -> dict:
    """Trascrizione finta: (testo, inizio, fine) -> struttura di analyze."""
    words = [{"w": w, "t": t, "e": e, "p": 0.9} for w, t, e in parole]
    return {"language": "it", "segments": [{
        "start": words[0]["t"], "end": words[-1]["e"],
        "text": " ".join(w["w"] for w in words), "words": words,
    }]}


# --------------------------------------------------------------------------
# raggruppamento
# --------------------------------------------------------------------------


def test_group_words_una_riga_corta():
    righe = captions.group_words(_tr(("ciao", 0, 0.4), ("mondo", 0.4, 0.9)))
    assert len(righe) == 1
    assert righe[0]["text"] == "ciao mondo"
    assert righe[0]["start"] == 0 and righe[0]["end"] == 0.9


def test_group_words_spezza_sui_caratteri():
    parole = [(f"parola{i}", i * 0.3, i * 0.3 + 0.25) for i in range(10)]
    righe = captions.group_words(_tr(*parole), max_chars=20)
    assert len(righe) > 1
    assert all(len(r["text"]) <= 20 for r in righe)


def test_group_words_spezza_sulla_pausa():
    righe = captions.group_words(_tr(("prima", 0, 0.5), ("dopo", 3.0, 3.4)), max_gap=0.7)
    assert len(righe) == 2


def test_group_words_spezza_sulla_durata():
    parole = [(f"p{i}", i * 1.0, i * 1.0 + 0.5) for i in range(8)]
    righe = captions.group_words(_tr(*parole), max_dur=2.0, max_chars=999, max_gap=99)
    assert len(righe) > 1
    assert all(r["end"] - r["start"] <= 2.6 for r in righe)


def test_group_words_offset_sposta_i_tempi():
    righe = captions.group_words(_tr(("tardi", 10.0, 10.5)), offset=9.0)
    assert righe[0]["start"] == 1.0 and righe[0]["end"] == 1.5


def test_group_words_segmento_senza_parole():
    tr = {"segments": [{"start": 0, "end": 2, "text": "senza timestamp", "words": []}]}
    righe = captions.group_words(tr)
    assert righe[0]["text"] == "senza timestamp"


# --------------------------------------------------------------------------
# formati
# --------------------------------------------------------------------------


def test_srt_ben_formato():
    righe = captions.group_words(_tr(("ciao", 1.5, 2.25)))
    srt = captions.to_srt(righe)
    assert srt.startswith("1\n")
    assert "00:00:01,500 --> 00:00:02,250" in srt


def test_srt_arrotonda_senza_saltare_il_secondo():
    assert captions._ts_srt(0.9999) == "00:00:01,000"
    assert captions._ts_srt(59.9996) == "00:01:00,000"


def test_vtt_ha_intestazione():
    vtt = captions.to_vtt(captions.group_words(_tr(("a", 0, 1))))
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.000 --> 00:00:01.000" in vtt


def test_ass_colori_invertiti():
    assert captions._ass_color("#FFE100") == "&H0000E1FF"
    with pytest.raises(ValueError):
        captions._ass_color("#FFF")


def test_ass_ha_stile_e_dialoghi():
    righe = captions.group_words(_tr(("ciao", 0, 0.5), ("mondo", 0.5, 1.0)))
    ass = captions.to_ass(righe, width=1080, height=1920)
    assert "[V4+ Styles]" in ass and "Style: vedit," in ass
    assert "PlayResX: 1080" in ass
    assert ass.count("Dialogue:") == 1


def test_ass_karaoke_una_k_per_parola():
    righe = captions.group_words(_tr(("uno", 0, 0.5), ("due", 0.5, 1.0), ("tre", 1.0, 1.4)))
    ass = captions.to_ass(righe, karaoke=True)
    riga = [l for l in ass.splitlines() if l.startswith("Dialogue:")][0]
    assert riga.count("\\k") == 3
    assert "{\\k50}uno" in riga and "{\\k40}tre" in riga


def test_ass_senza_karaoke_niente_tag():
    righe = captions.group_words(_tr(("uno", 0, 0.5)))
    ass = captions.to_ass(righe, karaoke=False)
    assert "\\k" not in ass


def test_ass_maiuscolo_e_stile():
    st = captions.CaptionStyle(uppercase=True, size=90, primary="#FF0000")
    ass = captions.to_ass(captions.group_words(_tr(("ciao", 0, 1))), st)
    assert "CIAO" in ass
    assert ",90," in ass


def test_ass_escape_delle_graffe():
    ass = captions.to_ass(captions.group_words(_tr(("{strano}", 0, 1))), karaoke=False)
    assert "\\{strano\\}" in ass


def test_write_rifiuta_formato_sconosciuto(tmp_path):
    with pytest.raises(ValueError, match="sconosciuto"):
        captions.write(str(tmp_path / "x.foo"), [], "foo")


@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass"])
def test_write_scrive_utf8(tmp_path, fmt):
    righe = captions.group_words(_tr(("perche'", 0, 0.5), ("citta'", 0.5, 1.0)))
    p = captions.write(str(tmp_path / f"c.{fmt}"), righe, fmt)
    testo = open(p, encoding="utf-8").read()
    assert "citta'" in testo
    assert not testo.startswith("﻿"), "il BOM manda in errore ffmpeg"


# --------------------------------------------------------------------------
# burn-in: ffmpeg deve accettarli davvero
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["srt", "ass"])
def test_burn_in_con_ffmpeg(tmp_path, fmt):
    righe = captions.group_words(_tr(("ciao", 0, 0.4), ("mondo", 0.4, 0.9)))
    f = captions.write(str(tmp_path / f"sub.{fmt}"), righe, fmt)
    chain = fx.EFFECTS["subtitles"].build({"file": f}, fx.Ctx(width=320, height=180))
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=25:d=1",
        "-vf", ",".join(chain), "-frames:v", "5", "-f", "null", "-",
    ], check=True, capture_output=True, timeout=120)


def test_subtitles_senza_file_non_fa_nulla():
    assert fx.EFFECTS["subtitles"].build({"file": ""}, fx.Ctx()) == []


def test_subtitles_in_preview_scala_il_font():
    chain = fx.EFFECTS["subtitles"].build({"file": "x.ass"},
                                          fx.Ctx(width=640, height=360, scale=0.5))
    assert "original_size=1280x720" in chain[0]


def test_subtitles_nel_registro():
    assert "subtitles" in {d["name"] for d in fx.describe("video")}
