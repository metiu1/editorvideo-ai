"""Transizioni: ognuna deve renderizzare e mostrare davvero due clip diverse
durante il passaggio (non basta che ffmpeg non dia errore).
"""

from pathlib import Path

import pytest

from vedit import render
from vedit.model import TRANSITIONS
from vedit.store import EditError, Store


def _due_clip(assets, tmp_path, dur=1.5):
    s = Store.create("tr", path=str(tmp_path / "p.json"))
    s.set_settings(width=320, height=180)
    a_m, b_m = s.import_media([assets["red"], assets["green"]])
    a = s.add_clip(a_m.id, duration=dur)
    b = s.add_clip(b_m.id, duration=dur)
    return s, a, b


def test_tipo_sconosciuto(assets, tmp_path):
    s, a, b = _due_clip(assets, tmp_path)
    with pytest.raises(EditError, match="sconosciuta"):
        s.crossfade(a.id, b.id, 0.5, type="tenda_veneziana")


def test_crossfade_imposta_transizione(assets, tmp_path):
    s, a, b = _due_clip(assets, tmp_path)
    s.crossfade(a.id, b.id, 0.5, type="wipe_right")
    assert a.transition_out.type == "wipe_right"
    assert a.transition_out.duration == pytest.approx(0.5)
    assert a.fade_out == 0  # la tendina sostituisce la dissolvenza
    assert a.audio.fade_out == pytest.approx(0.5)  # l'audio incrocia comunque
    assert b.start == pytest.approx(a.end - 0.5)

    s.crossfade(a.id, b.id, 0.4, type="dissolve")
    assert a.fade_out == pytest.approx(0.4)
    assert a.transition_out.duration == 0


@pytest.mark.slow
@pytest.mark.parametrize("kind", TRANSITIONS)
def test_transizione_renderizza(kind, assets, tmp_path):
    s, a, b = _due_clip(assets, tmp_path)
    s.crossfade(a.id, b.id, 0.6, type=kind)
    out = tmp_path / f"{kind}.mp4"
    render.render(s.project, render.RenderOptions(output=str(out), quality="draft"))
    assert Path(out).stat().st_size > 0


@pytest.mark.slow
def test_wipe_mostra_entrambe_le_clip(assets, tmp_path):
    """A meta' tendina il fotogramma deve contenere sia il rosso sia il verde."""
    s, a, b = _due_clip(assets, tmp_path, dur=2.0)
    s.crossfade(a.id, b.id, 1.0, type="wipe_right")
    mid = a.end - 0.5  # meta' della transizione

    frame = tmp_path / "mid.png"
    render.render_frame(s.project, mid, str(frame), width=160, use_proxy=False)

    colori = _colonne(frame)
    assert colori["sinistra"] == "verde", colori   # gia' scoperto
    assert colori["destra"] == "rosso", colori     # ancora coperto


@pytest.mark.slow
def test_anteprima_coincide_col_render(assets, tmp_path):
    """Il fotogramma di anteprima a meta' dissolvenza deve essere quello vero.

    E' il test che protegge il meccanismo dell'offset: senza, il segmento
    ripartirebbe da zero e mostrerebbe la dissolvenza all'inizio invece che a meta'.
    """
    import subprocess

    from vedit import ffmpeg

    s, a, b = _due_clip(assets, tmp_path, dur=2.0)
    s.crossfade(a.id, b.id, 1.0, type="dissolve")
    mid = a.end - 0.5

    completo = tmp_path / "full.mp4"
    render.render(s.project, render.RenderOptions(output=str(completo), quality="max"))
    da_render = tmp_path / "da_render.png"
    subprocess.run([ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", f"{mid:.3f}", "-i", str(completo), "-frames:v", "1",
                    "-vf", "scale=64:36", str(da_render)], check=True)

    da_preview = tmp_path / "da_preview.png"
    render.render_frame(s.project, mid, str(da_preview), width=64, use_proxy=False)

    assert _colore_medio(da_render) == pytest.approx(_colore_medio(da_preview), abs=18)


def _colore_medio(png: Path) -> tuple:
    import subprocess

    from vedit import ffmpeg

    raw = subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-i", str(png),
        "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ], capture_output=True).stdout
    return tuple(raw[:3])


def _colonne(png: Path) -> dict:
    """Colore dominante nella colonna sinistra e in quella destra del fotogramma."""
    import subprocess

    from vedit import ffmpeg

    out = {}
    for nome, crop in (("sinistra", "iw/6:ih:0:0"), ("destra", "iw/6:ih:iw*5/6:0")):
        raw = subprocess.run([
            ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error",
            "-i", str(png), "-vf", f"crop={crop},scale=1:1", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-",
        ], capture_output=True).stdout
        r, g, bl = raw[0], raw[1], raw[2]
        out[nome] = "rosso" if r > g + 40 else "verde" if g > r + 40 else f"altro({r},{g},{bl})"
    return out
