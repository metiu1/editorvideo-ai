"""Test dell'accelerazione hardware: scelta encoder, bitrate, ripiego a gradini.

Niente GPU richiesta: le prove reali di ffmpeg vengono sostituite, cosi' i test
girano identici su una macchina senza scheda video.
"""

from dataclasses import replace

import pytest

from vedit import hw, render


# ---------------------------------------------------------------- encoder_args
@pytest.mark.parametrize("enc", [
    "h264_nvenc", "h264_qsv", "h264_amf", "libx264", "libx265", "libsvtav1", "libvpx-vp9",
])
def test_bitrate_onorato_da_tutti_gli_encoder(enc):
    """Il bitrate chiesto deve arrivare a ffmpeg qualunque encoder entri.

    Era il bug: ``-b:v`` compariva solo nel ramo NVENC, quindi bastava che la
    GPU non ci fosse perche' la richiesta sparisse in silenzio.
    """
    args = hw.encoder_args(enc, "medium", "12M")
    assert "-b:v" in args
    assert args[args.index("-b:v") + 1] == "12M"
    assert "-maxrate" in args and "-bufsize" in args
    # con una taglia richiesta non si impone anche un fattore di qualita'
    assert "-crf" not in args and "-cq" not in args and "-global_quality" not in args


@pytest.mark.parametrize("enc", ["libx264", "libx265", "h264_nvenc", "libsvtav1"])
def test_senza_bitrate_resta_a_qualita_costante(enc):
    args = hw.encoder_args(enc, "high")
    assert "-b:v" not in args or args[args.index("-b:v") + 1] == "0"
    assert any(f in args for f in ("-crf", "-cq", "-global_quality", "-qp_i"))


def test_qualita_muove_il_preset():
    veloce = hw.encoder_args("libx264", "draft", "8M")
    lento = hw.encoder_args("libx264", "max", "8M")
    assert veloce[veloce.index("-preset") + 1] != lento[lento.index("-preset") + 1]


def test_bufsize_doppio_del_bitrate():
    assert hw._bufsize("12M") == "24M"
    assert hw._bufsize("800k") == "1600k"
    assert hw._bufsize("strano") == "strano"


# ---------------------------------------------------------------- detect
def test_hwaccel_provato_insieme_all_encoder(monkeypatch, tmp_path):
    """La decodifica accelerata va scartata se non regge con l'encoder scelto.

    E' il caso reale che rompeva il render: ``d3d11va`` e ``h264_nvenc`` passano
    le prove separate e falliscono insieme. Qui ``d3d11va`` funziona da solo ma
    non in coppia, e il rilevamento deve preferire ``cuda``.
    """
    probe = tmp_path / "probe.mp4"
    probe.write_bytes(b"x")

    monkeypatch.setattr(hw, "_cache_file", lambda: tmp_path / "hw.json")
    monkeypatch.setattr(hw, "_probe_file", lambda: probe)
    monkeypatch.setattr(hw, "DECODERS", ["d3d11va", "cuda"])
    monkeypatch.setattr(hw.ffmpeg, "encoders", lambda: {"h264_nvenc", "libx264", "libx265"})
    monkeypatch.setattr(hw, "_test_encoder", lambda enc: enc == "h264_nvenc")

    visti = []

    def finto(method, probe_path, encoder=""):
        visti.append((method, encoder))
        return not (method == "d3d11va" and encoder == "h264_nvenc")

    monkeypatch.setattr(hw, "_test_hwaccel", finto)

    info = hw.detect(force=True)
    assert info.encoders["h264"] == "h264_nvenc"
    assert info.hwaccel == "cuda"
    # l'encoder vero deve comparire nella prova, altrimenti non e' un test di coppia
    assert all(enc == "h264_nvenc" for _, enc in visti)


def test_nessuna_coppia_regge_ma_encoder_tenuto(monkeypatch, tmp_path):
    """Se nessun metodo di decodifica sopravvive all'encoder, si tiene l'encoder.

    Meta' accelerazione vale molto piu' di zero: e' la codifica a far
    risparmiare il tempo, la decodifica e' il contorno.
    """
    probe = tmp_path / "probe.mp4"
    probe.write_bytes(b"x")
    monkeypatch.setattr(hw, "_cache_file", lambda: tmp_path / "hw.json")
    monkeypatch.setattr(hw, "_probe_file", lambda: probe)
    monkeypatch.setattr(hw, "DECODERS", ["d3d11va", "cuda"])
    monkeypatch.setattr(hw.ffmpeg, "encoders", lambda: {"h264_nvenc", "libx264"})
    monkeypatch.setattr(hw, "_test_encoder", lambda enc: enc == "h264_nvenc")
    monkeypatch.setattr(hw, "_test_hwaccel", lambda m, p, encoder="": False)

    info = hw.detect(force=True)
    assert info.hwaccel == ""
    assert info.encoders["h264"] == "h264_nvenc"
    assert info.is_hw("h264_nvenc")


# ---------------------------------------------------------------- ripiego
def test_ripiego_toglie_prima_la_decodifica_poi_tutto(assets, tmp_path, monkeypatch):
    """Il ripiego e' a gradini: prima cade la decodifica, l'encoder GPU resta.

    Buttare subito anche l'encoder e' quello che faceva finire ogni render in
    software appena la coppia non reggeva.
    """
    from vedit.store import Store

    s = Store.create(tmp_path / "p.json")
    m = s.import_media([assets["red"]])[0]
    s.add_clip(m.id, duration=1.0)

    tentativi = []
    reale = render.build_command

    def spia(project, opts, workdir):
        args, dur, warn, enc = reale(project, opts, workdir)
        tentativi.append({"hwaccel": "-hwaccel" in args, "enc": enc})
        return args, dur, warn, enc

    monkeypatch.setattr(render, "build_command", spia)
    monkeypatch.setattr(render.hw, "detect", lambda force=False: hw.HWInfo(
        encoders={"h264": "h264_nvenc"}, working=["h264_nvenc"], hwaccel="cuda"))

    # i primi due passaggi falliscono, il terzo (software) riesce
    esiti = iter([(1, ["no encode device"]), (1, ["ancora GPU"]), (0, [])])

    def passaggio(args, *a, **k):
        code, log = next(esiti)
        if code == 0:
            render.Path(args[-1]).write_bytes(b"finto")
        return code, log

    monkeypatch.setattr(render, "_run_pass", passaggio)

    res = render.render(s.project, render.RenderOptions(output=str(tmp_path / "o.mp4")))

    assert [t["hwaccel"] for t in tentativi] == [True, False, False]
    assert tentativi[1]["enc"] == "h264_nvenc"   # secondo tentativo: encoder GPU tenuto
    assert tentativi[2]["enc"] == "libx264"      # solo alla fine si scende in software
    assert "decodifica accelerata fallita" in res.warnings[0]
    assert "no encode device" in res.warnings[0]  # la diagnosi vera arriva a galla


def test_perche_estrae_la_riga_utile():
    log = [
        "[h264_nvenc @ 0000027d] OpenEncodeSessionEx failed: no encode device (1)",
        "[fc#0] Error sending frames to consumers: No such file or directory",
        "[out#0/mp4] Nothing was written into output file",
    ]
    msg = render._perche(log)
    assert "no encode device" in msg
    assert "Error sending frames" not in msg


def test_perche_senza_niente_di_utile():
    assert render._perche([]) == ""
    assert render._perche(["Conversion failed"]) == ""
