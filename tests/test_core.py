"""Test del core: keyframe, editing, compilazione e render reale con ffmpeg."""

from pathlib import Path

import pytest

from vedit import keyframes as kf
from vedit import probe, render
from vedit.graph import CompileOptions, compile_project, slice_project
from vedit.store import EditError, Store


# ---------------------------------------------------------------- keyframes
def test_keyframe_sample_e_easing():
    v = {"kf": [{"t": 0, "v": 0.0}, {"t": 2, "v": 1.0}]}
    assert kf.sample(v, -1) == 0.0
    assert kf.sample(v, 1) == pytest.approx(0.5)
    assert kf.sample(v, 5) == 1.0
    assert kf.sample(0.7, 3) == 0.7

    ease = {"kf": [{"t": 0, "v": 0.0, "ease": "ease_in_out"}, {"t": 1, "v": 1.0}]}
    assert kf.sample(ease, 0.5) == pytest.approx(0.5)
    assert kf.sample(ease, 0.25) < 0.25  # parte piano


def test_keyframe_expr_valido():
    e = kf.expr({"kf": [{"t": 0, "v": 0}, {"t": 1, "v": 100}]}, "t")
    assert "if(lt(t," in e and "e+" not in e  # niente notazione scientifica
    assert kf.expr(3.5, "t") == "3.5"


def test_keyframe_validate():
    with pytest.raises(ValueError):
        kf.validate({"kf": [{"t": 0}]})
    with pytest.raises(ValueError):
        kf.validate({"kf": [{"t": 0, "v": 1, "ease": "boh"}]})


# ---------------------------------------------------------------- editing
def test_import_e_clip(assets, tmp_path):
    s = Store.create("test", "1080p", path=str(tmp_path / "p.vedit.json"))
    media = s.import_media([assets["red"], assets["blue"]])
    assert len(media) == 2
    assert media[0].duration == pytest.approx(5, abs=0.2)
    assert media[0].has_audio

    # reimportare lo stesso file non duplica
    again = s.import_media([assets["red"]])
    assert again[0].id == media[0].id
    assert len(s.project.media) == 2

    c1 = s.add_clip(media[0].id)
    c2 = s.add_clip(media[1].id)
    assert c1.start == 0
    assert c2.start == pytest.approx(c1.duration)
    assert s.project.duration() == pytest.approx(c1.duration + c2.duration)

    # persistenza
    reopened = Store.open(s.path)
    assert reopened.project.duration() == pytest.approx(s.project.duration())


def test_split_trim_speed(assets, tmp_path):
    s = Store.create("t", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id)

    a, b = s.split_clip(c.id, 2.0)
    assert a.duration == pytest.approx(2.0)
    assert b.start == pytest.approx(2.0)
    assert b.in_ == pytest.approx(2.0)

    with pytest.raises(EditError):
        s.split_clip(a.id, 99)

    s.set_speed(b.id, 2.0)
    assert b.speed == 2.0
    assert b.duration == pytest.approx(1.5, abs=0.05)  # 3s di sorgente a 2x
    assert b.source_duration() == pytest.approx(3.0, abs=0.05)

    s.trim_clip(a.id, duration=1.0)
    assert a.duration == 1.0


def test_undo_redo(assets, tmp_path):
    s = Store.create("t", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["red"]])[0]
    s.add_clip(m.id)
    assert len(s.project.tracks[0].clips) == 1
    assert s.undo()
    assert len(s.project.tracks[0].clips) == 0
    assert s.redo()
    assert len(s.project.tracks[0].clips) == 1


def test_effetti_validati(assets, tmp_path):
    s = Store.create("t", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id)

    s.add_effect(c.id, "color", {"saturation": 1.4})
    with pytest.raises(ValueError):
        s.add_effect(c.id, "color", {"saturazione": 2})  # nome sbagliato
    with pytest.raises(ValueError):
        s.add_effect(c.id, "color", {"saturation": 99})  # fuori range
    with pytest.raises(KeyError):
        s.add_effect(c.id, "inesistente", {})
    # parametro non animabile
    with pytest.raises(ValueError):
        s.add_effect(c.id, "blur", {"sigma": {"kf": [{"t": 0, "v": 1}]}})

    s.update_effect(c.id, 0, {"contrast": 1.2})
    assert s.project.clip(c.id).effects[0].params["contrast"] == 1.2
    s.remove_effect(c.id, 0)
    assert not s.project.clip(c.id).effects


def test_crossfade_accosta_le_clip(assets, tmp_path):
    s = Store.create("t", path=str(tmp_path / "p.json"))
    a_m, b_m = s.import_media([assets["red"], assets["blue"]])
    a = s.add_clip(a_m.id)
    b = s.add_clip(b_m.id)
    total_before = s.project.duration()
    s.crossfade(a.id, b.id, 1.0)
    assert b.start == pytest.approx(a.end - 1.0)
    assert a.fade_out == 1.0
    assert s.project.duration() == pytest.approx(total_before - 1.0)


def test_slice_project(assets, tmp_path):
    """Il segmento sposta il punto di attacco ma conserva il tempo locale."""
    from vedit.graph import clip_offset, clip_visible

    s = Store.create("t", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["red"]])[0]
    c0 = s.add_clip(m.id)  # 0..5
    s.set_fades(c0.id, fade_out=1.0)

    sub = slice_project(s.project, 2.0, 4.0)
    c = sub.tracks[0].clips[0]
    assert c.start == 0
    assert c.in_ == pytest.approx(2.0)
    assert clip_offset(c) == pytest.approx(2.0)
    assert clip_visible(c) == pytest.approx(2.0)
    # durata e dissolvenza restano quelle originali: la dissolvenza in uscita
    # cade ancora a 4.0-5.0 del tempo clip, quindi il segmento la mostra a meta'
    assert c.duration == pytest.approx(5.0, abs=0.2)
    assert c.fade_out == 1.0


# ---------------------------------------------------------------- compilazione
def test_compile_produce_grafo(assets, tmp_path):
    s = Store.create("t", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id)
    s.set_transform(c.id, opacity={"kf": [{"t": 0, "v": 0}, {"t": 1, "v": 1}]})
    out = compile_project(s.project, CompileOptions(workdir=str(tmp_path)))
    assert out.video_label and out.audio_label
    assert "overlay" in out.filtergraph
    assert out.inputs.count("-i") == 2  # un ingresso per il video, uno per l'audio
    assert out.duration == pytest.approx(5, abs=0.2)


def test_timeline_vuota_errore(tmp_path):
    s = Store.create("t", path=str(tmp_path / "p.json"))
    with pytest.raises(ValueError):
        compile_project(s.project)


# ---------------------------------------------------------------- render
@pytest.mark.slow
def test_render_completo(assets, tmp_path):
    """Percorso completo: taglio, velocita', colore, testo, PiP, musica, fade."""
    s = Store.create("demo", "720p", path=str(tmp_path / "p.json"))
    red, blue, music, logo = s.import_media(
        [assets["red"], assets["blue"], assets["music"], assets["logo"]]
    )

    c1 = s.add_clip(red.id, duration=3.0)
    c2 = s.add_clip(blue.id, duration=3.0)
    s.set_speed(c2.id, 2.0)
    s.add_effect(c1.id, "color", {"saturation": 1.3, "contrast": 1.1})
    s.add_effect(c2.id, "vignette", {})
    s.crossfade(c1.id, c2.id, 0.5)
    s.set_fades(c1.id, fade_in=0.4)

    # traccia superiore: logo in sovrimpressione con zoom e spostamento animati
    v2 = s.add_track("video", "overlay")
    pip = s.add_clip(logo.id, v2.id, start=0.5, duration=2.0)
    s.set_clip(pip.id, fit="none")
    s.set_transform(
        pip.id,
        x={"kf": [{"t": 0, "v": -300, "ease": "ease_out"}, {"t": 1.5, "v": 300}]},
        y=-200,
        scale={"kf": [{"t": 0, "v": 1.0}, {"t": 2.0, "v": 1.6}]},
    )

    # titolo
    txt = s.add_text("Ciao mondo", start=0.2, duration=2.0, font_size=72, box=True)
    s.set_transform(txt.id, opacity={"kf": [{"t": 0, "v": 0}, {"t": 0.5, "v": 1}]})

    # musica di sottofondo abbassata
    a2 = s.add_track("audio", "musica")
    mus = s.add_clip(music.id, a2.id, start=0.0, duration=4.0)
    s.set_audio(mus.id, gain_db=-12)
    s.add_effect(mus.id, "highpass", {"freq": 100})
    s.set_loudnorm(True, -16)

    out = tmp_path / "out.mp4"
    res = render.render(s.project, render.RenderOptions(output=str(out), quality="draft"))
    assert Path(res.output).exists()
    info = probe.probe(res.output)
    assert info.duration == pytest.approx(s.project.duration(), abs=0.35)
    assert info.width == 1280 and info.height == 720
    assert info.has_audio


@pytest.mark.slow
def test_titolo_sopra_al_video_stessa_traccia(assets, tmp_path):
    """Un titolo aggiunto sulla traccia di una ripresa deve restare visibile.

    Sulla stessa traccia la clip che inizia prima sta sopra (serve alle
    transizioni): i titoli sono l'eccezione, altrimenti sparirebbero sotto la
    ripresa che li contiene.
    """
    import subprocess

    from vedit import ffmpeg

    s = Store.create("z", "720p", path=str(tmp_path / "p.json"))
    s.set_settings(width=320, height=180)
    m = s.import_media([assets["green"]])[0]
    s.add_clip(m.id, duration=3.0)                       # copre tutto il canvas
    s.add_text("XXXX", start=0.5, duration=2.0, font_size=90, color="white")

    out = tmp_path / "f.png"
    render.render_frame(s.project, 1.5, str(out), width=320, use_proxy=False)
    raw = subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(out),
        "-vf", "crop=iw/3:ih/4:iw/3:ih*3/8,scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], capture_output=True).stdout
    # al centro c'e' il testo bianco sopra il verde: il rosso sale parecchio
    assert raw[0] > 60, f"testo non visibile, centro = {tuple(raw[:3])}"


@pytest.mark.slow
def test_render_frame(assets, tmp_path):
    s = Store.create("t", "720p", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["blue"]])[0]
    s.add_clip(m.id)
    p = render.render_frame(s.project, 1.0, str(tmp_path / "f.jpg"), width=320, use_proxy=False)
    assert Path(p).stat().st_size > 0


def test_mp3_con_copertina_resta_audio(audio_con_copertina, tmp_path):
    """La copertina e' uno stream video: non deve trasformare il brano in video.

    Se passa per video finisce su una traccia video, prende la risoluzione
    della copertina e la striscia in timeline resta vuota.
    """
    s = Store.create(path=str(tmp_path / "p.json"))
    m = s.import_media([audio_con_copertina])[0]
    assert m.kind == "audio"
    assert m.has_audio and not m.has_video
    assert m.duration > 2.5

    with pytest.raises(EditError):
        s.add_clip(m.id, s.project.tracks[0].id)   # traccia video: deve rifiutare


# ---------------------------------------------------------------- hardware
def test_hwaccel_ripiega_ma_tiene_l_encoder(assets, tmp_path, monkeypatch):
    """Se la decodifica accelerata cede, cade solo lei: il render finisce lo stesso.

    L'accelerazione e' un'ottimizzazione e va trattata come tale: il device
    hardware puo' non nascere (driver occupato, troppi contesti aperti) e
    ffmpeg in quel caso non fallisce con grazia, esce di schianto. Prima
    questo portava via l'export intero.

    Le due meta' pero' si buttano separatamente. Qui a non reggere e' solo la
    decodifica, quindi il ripiego deve fermarsi al primo gradino e tenere
    l'encoder: scendere subito in software e' il motivo per cui ogni render
    finiva sulla CPU anche quando la GPU stava benissimo.
    """
    from vedit import hw

    # encoder buono, metodo di decodifica inesistente: cede solo la decodifica
    monkeypatch.setattr(hw, "detect", lambda force=False: hw.HWInfo(
        encoders={"h264": "libx264"}, working=["libx264"], hwaccel="nonesiste"))

    s = Store.create("hw", "720p", path=str(tmp_path / "p.json"))
    m = s.import_media([assets["green"]])[0]
    s.add_clip(m.id, duration=1.0)

    out = tmp_path / "out.mp4"
    res = render.render(s.project, render.RenderOptions(
        output=str(out), quality="draft", width=320, height=180))

    assert res.size > 0
    assert "-hwaccel" not in res.command          # il secondo giro l'ha tolto
    assert res.encoder == "libx264"               # l'encoder resta quello scelto
    assert any("decodifica accelerata" in w for w in res.warnings)
    assert not any("software" in w for w in res.warnings), \
        "e' caduta solo la decodifica: non c'era motivo di rifare tutto in software"
