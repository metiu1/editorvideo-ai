"""La CLI deve reggere il giro completo: crea, importa, monta, renderizza."""

from pathlib import Path

from vedit.cli import main


def test_new_import_add_render(assets, tmp_path, capsys):
    proj = str(tmp_path / "p.json")
    assert main(["new", proj, "--preset", "720p"]) == 0
    capsys.readouterr()

    assert main(["import", proj, assets["red"]]) == 0
    media_id = capsys.readouterr().out.split()[0]

    assert main(["add", proj, media_id, "--duration", "1.0"]) == 0
    assert main(["info", proj]) == 0
    assert "durata 1.00s" in capsys.readouterr().out

    out = str(tmp_path / "out.mp4")
    assert main(["render", proj, out, "--quality", "draft", "--quiet"]) == 0
    assert Path(out).stat().st_size > 0


def test_errori_ritornano_codice_1(tmp_path, capsys):
    assert main(["info", str(tmp_path / "manca.json")]) == 1
    assert "errore:" in capsys.readouterr().err


def test_effects_e_doctor(capsys):
    assert main(["effects", "video"]) == 0
    out = capsys.readouterr().out
    assert "chromakey" in out and "animabile" in out
    assert main(["doctor"]) == 0
    assert "ffmpeg" in capsys.readouterr().out
