"""Insert, micro-dissolvenze, ducking, J/L cut."""

import subprocess

import pytest

from vedit import ffmpeg, ops
from vedit.store import Store


@pytest.fixture(autouse=True)
def cache_isolata(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))


def _video(path, colore="red", durata=4.0, audio=True):
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
def progetto(tmp_path):
    s = Store.create("ops", "720p", path=str(tmp_path / "p.json"))
    s.set_settings(width=320, height=180)
    a = s.import_media([_video(tmp_path / "a.mp4", "red")])[0]
    b = s.import_media([_video(tmp_path / "b.mp4", "blue")])[0]
    s.add_clip(a.id, start=0.0, duration=2.0)
    s.add_clip(b.id, start=2.0, duration=2.0)
    return s, a, b


# --------------------------------------------------------------------------
# insert
# --------------------------------------------------------------------------


def test_insert_spinge_a_destra(progetto, tmp_path):
    s, a, b = progetto
    c = s.import_media([_video(tmp_path / "c.mp4", "green", 2.0)])[0]
    res = ops.insert_clip(s, c.id, at=2.0, duration=1.0)
    clips = sorted(s.project.tracks[0].clips, key=lambda x: x.start)
    assert [round(x.start, 2) for x in clips] == [0.0, 2.0, 3.0]
    assert res["clip"] == clips[1].id
    assert clips[2].media == b.id, "la clip blu doveva spostarsi, non essere coperta"


def test_insert_divide_la_clip_a_cavallo(progetto, tmp_path):
    s, a, b = progetto
    c = s.import_media([_video(tmp_path / "c.mp4", "green", 2.0)])[0]
    ops.insert_clip(s, c.id, at=1.0, duration=1.0)
    clips = sorted(s.project.tracks[0].clips, key=lambda x: x.start)
    assert len(clips) == 4                       # rossa spezzata + verde + blu
    assert [round(x.start, 2) for x in clips] == [0.0, 1.0, 2.0, 3.0]


def test_insert_in_coda_non_sposta_nulla(progetto, tmp_path):
    s, a, b = progetto
    c = s.import_media([_video(tmp_path / "c.mp4", "green", 2.0)])[0]
    ops.insert_clip(s, c.id, at=4.0, duration=1.0)
    clips = sorted(s.project.tracks[0].clips, key=lambda x: x.start)
    assert [round(x.start, 2) for x in clips] == [0.0, 2.0, 4.0]


def test_insert_non_lascia_sovrapposizioni(progetto, tmp_path):
    s, a, b = progetto
    c = s.import_media([_video(tmp_path / "c.mp4", "green", 2.0)])[0]
    ops.insert_clip(s, c.id, at=0.0, duration=1.5)
    clips = sorted(s.project.tracks[0].clips, key=lambda x: x.start)
    for x, y in zip(clips, clips[1:]):
        assert y.start >= x.end - 1e-6


# --------------------------------------------------------------------------
# micro-dissolvenze
# --------------------------------------------------------------------------


def test_smooth_cuts_sfuma_solo_le_giunzioni(progetto):
    s, _, _ = progetto
    res = ops.smooth_cuts(s, duration=0.06)
    assert res["clip_sfumate"] == 2
    prima, dopo = sorted(s.project.tracks[0].clips, key=lambda c: c.start)
    assert prima.audio.fade_out == pytest.approx(0.06)
    assert dopo.audio.fade_in == pytest.approx(0.06)
    # la giunzione esterna non si tocca: l'inizio del montaggio resta netto
    assert prima.audio.fade_in == 0.0
    assert dopo.audio.fade_out == 0.0


def test_smooth_cuts_non_tocca_il_video(progetto):
    s, _, _ = progetto
    ops.smooth_cuts(s)
    assert all(c.fade_in == 0.0 and c.fade_out == 0.0
               for c in s.project.tracks[0].clips), "lo stacco video deve restare netto"


def test_smooth_cuts_limita_su_clip_cortissime(progetto, tmp_path):
    s, a, _ = progetto
    s.set_clip(sorted(s.project.tracks[0].clips, key=lambda c: c.start)[0].id,
               duration=0.09)
    ops.smooth_cuts(s, duration=0.5)
    c = sorted(s.project.tracks[0].clips, key=lambda x: x.start)[0]
    assert c.audio.fade_out <= c.duration / 3 + 1e-6


def test_smooth_cuts_clip_isolate_con_flag(progetto):
    s, _, _ = progetto
    ops.smooth_cuts(s, only_touching=False)
    prima = sorted(s.project.tracks[0].clips, key=lambda c: c.start)[0]
    assert prima.audio.fade_in > 0


# --------------------------------------------------------------------------
# ducking
# --------------------------------------------------------------------------


def test_duck_keyframes_forma_della_rampa():
    kfs = ops.duck_keyframes([(2.0, 4.0)], clip_start=0.0, clip_duration=8.0,
                             amount_db=-12, attack=0.25, release=0.6)
    tempi = [k["t"] for k in kfs]
    valori = dict((k["t"], k["v"]) for k in kfs)
    assert tempi == sorted(tempi), "i keyframe devono essere in ordine di tempo"
    assert valori[1.75] == 0.0 and valori[2.0] == -12.0
    assert valori[4.0] == -12.0 and valori[4.6] == 0.0
    assert valori[0.0] == 0.0 and valori[8.0] == 0.0


def test_duck_keyframes_taglia_ai_bordi_della_clip():
    kfs = ops.duck_keyframes([(0.0, 10.0)], clip_start=0.0, clip_duration=3.0,
                             amount_db=-10)
    assert all(0.0 <= k["t"] <= 3.0 for k in kfs)
    assert min(k["v"] for k in kfs) == -10.0


def test_duck_keyframes_tratti_vicini_non_si_annullano():
    """Due frasi ravvicinate: la musica non deve risalire tra l'una e l'altra."""
    kfs = ops.duck_keyframes([(1.0, 2.0), (2.2, 3.0)], clip_start=0.0,
                             clip_duration=5.0, attack=0.3, release=0.6)
    tempi = [k["t"] for k in kfs]
    assert len(tempi) == len(set(tempi)), "keyframe duplicati sullo stesso istante"
    # nell'istante conteso vince l'abbassamento
    contesi = [k for k in kfs if abs(k["t"] - 2.2) < 1e-6]
    assert contesi and contesi[0]["v"] < 0


def test_duck_keyframes_relativi_alla_clip():
    kfs = ops.duck_keyframes([(10.0, 11.0)], clip_start=8.0, clip_duration=5.0)
    abbassati = [k["t"] for k in kfs if k["v"] < 0]
    assert abbassati[0] == pytest.approx(2.0)      # 10s timeline = 2s nella clip


def test_duck_music_applica_l_automazione(progetto, tmp_path):
    """Voce con una pausa: la musica deve avere keyframe che scendono e risalgono."""
    s, _, _ = progetto
    voce = tmp_path / "voce.mp4"
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=25:d=4",
        "-f", "lavfi", "-i",
        "sine=frequency=440:duration=1,apad=pad_dur=2[s1];"
        "sine=frequency=440:duration=1[s2];[s1][s2]concat=n=2:v=0:a=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(voce),
    ], check=True, capture_output=True)

    mv = s.import_media([str(voce)])[0]
    vt = s.add_track("video")
    vclip = s.add_clip(mv.id, track_id=vt.id, start=0.0, duration=4.0)
    at = s.add_track("audio")
    musica = s.add_clip(s.import_media([_video(tmp_path / "m.m4a", "black", 6.0)])[0].id,
                        track_id=at.id, start=0.0, duration=4.0)

    res = ops.duck_music(s, musica.id, vclip.id, amount_db=-15)
    assert res["tratti_di_parlato"] >= 1
    _, m = s.clip_or_die(musica.id)
    kfs = m.audio.gain_db["kf"]
    assert min(k["v"] for k in kfs) == -15.0
    assert max(k["v"] for k in kfs) == 0.0


# --------------------------------------------------------------------------
# J/L cut
# --------------------------------------------------------------------------


def test_detach_audio_crea_la_clip_gemella(progetto):
    s, _, _ = progetto
    video = sorted(s.project.tracks[0].clips, key=lambda c: c.start)[0]
    res = ops.detach_audio(s, video.id)
    _, audio = s.clip_or_die(res["audio_clip"])
    assert audio.start == video.start and audio.duration == video.duration
    _, v = s.clip_or_die(video.id)
    assert v.audio.mute is True, "l'audio originale deve tacere, altrimenti raddoppia"


def test_j_cut_anticipa_l_audio(progetto):
    s, _, _ = progetto
    seconda = sorted(s.project.tracks[0].clips, key=lambda c: c.start)[1]
    s.set_clip(seconda.id, in_=1.0)              # materiale disponibile prima
    res = ops.jl_cut(s, seconda.id, seconds=0.5, kind="J")
    assert res["applicato"] == 0.5
    _, audio = s.clip_or_die(res["audio_clip"])
    assert audio.start == pytest.approx(seconda.start - 0.5)
    assert audio.in_ == pytest.approx(0.5)


def test_j_cut_senza_materiale_prima(progetto):
    s, _, _ = progetto
    prima = sorted(s.project.tracks[0].clips, key=lambda c: c.start)[0]
    res = ops.jl_cut(s, prima.id, seconds=0.5, kind="J")
    assert res["applicato"] == 0.0
    assert "impossibile" in res["nota"]


def test_l_cut_prolunga_l_audio(progetto):
    s, _, _ = progetto
    prima = sorted(s.project.tracks[0].clips, key=lambda c: c.start)[0]
    res = ops.jl_cut(s, prima.id, seconds=0.5, kind="L")
    assert res["applicato"] == 0.5
    _, audio = s.clip_or_die(res["audio_clip"])
    assert audio.duration == pytest.approx(2.5)


def test_l_cut_limitato_dal_materiale(progetto):
    s, _, _ = progetto
    prima = sorted(s.project.tracks[0].clips, key=lambda c: c.start)[0]
    s.set_clip(prima.id, duration=3.8)           # il file dura 4s
    res = ops.jl_cut(s, prima.id, seconds=2.0, kind="L")
    assert 0 < res["applicato"] <= 0.25


def test_jl_cut_kind_sbagliato(progetto):
    s, _, _ = progetto
    c = s.project.tracks[0].clips[0]
    with pytest.raises(ValueError, match="'J' o 'L'"):
        ops.jl_cut(s, c.id, kind="X")


def test_jl_cut_non_scollega_due_volte(progetto):
    s, _, _ = progetto
    prima = sorted(s.project.tracks[0].clips, key=lambda c: c.start)[0]
    ops.jl_cut(s, prima.id, seconds=0.3, kind="L")
    ops.jl_cut(s, prima.id, seconds=0.2, kind="L")
    audio_clips = [c for t in s.project.tracks if t.kind == "audio" for c in t.clips]
    assert len(audio_clips) == 1, "ha creato una seconda clip audio invece di riusarla"
