"""Ogni effetto del registro deve produrre un filtergraph che ffmpeg accetta.

E' il test che impedisce a un effetto di rompersi in silenzio: viene renderizzato
davvero, mezzo secondo a 320x180.
"""

from pathlib import Path

import pytest

from vedit import effects as fx
from vedit import render
from vedit.store import Store

# parametri minimi per gli effetti che non funzionano con i soli default
PARAMS = {
    "curves": {"preset": "increase_contrast"},
    "crop": {"w": 200, "h": 120, "x": 20, "y": 20},
    "pitch": {"semitones": 3},
    "motionblur": {"mode": "blend"},
}


def _identity_cube(path: Path) -> str:
    """LUT 3D identita' 2x2x2, sufficiente per validare il filtro."""
    lines = ["LUT_3D_SIZE 2", ""]
    for b in (0, 1):
        for g in (0, 1):
            for r in (0, 1):
                lines.append(f"{r}.0 {g}.0 {b}.0")
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(fx.EFFECTS))
def test_effetto_renderizza(name, assets, tmp_path):
    s = Store.create("fx", "720p", path=str(tmp_path / "p.json"))
    s.set_settings(width=320, height=180)
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, duration=0.5)

    params = dict(PARAMS.get(name, {}))
    if name == "lut":
        params["file"] = _identity_cube(tmp_path / "id.cube")

    s.add_effect(c.id, name, params)
    out = tmp_path / f"{name}.mp4"
    res = render.render(s.project, render.RenderOptions(output=str(out), quality="draft"))
    assert Path(res.output).stat().st_size > 0


@pytest.mark.slow
def test_keyframe_animati_su_effetto(assets, tmp_path):
    """I parametri animabili accettano i keyframe e il render regge."""
    s = Store.create("fx", path=str(tmp_path / "p.json"))
    s.set_settings(width=320, height=180)
    m = s.import_media([assets["red"]])[0]
    c = s.add_clip(m.id, duration=1.0)
    s.add_effect(c.id, "color", {
        "saturation": {"kf": [{"t": 0, "v": 0.0, "ease": "ease_in_out"}, {"t": 1, "v": 2.0}]},
        "brightness": {"kf": [{"t": 0, "v": -0.3}, {"t": 1, "v": 0.3}]},
    })
    s.set_audio(c.id, gain_db={"kf": [{"t": 0, "v": -30}, {"t": 1, "v": 0}]})
    out = tmp_path / "kf.mp4"
    render.render(s.project, render.RenderOptions(output=str(out), quality="draft"))
    assert out.stat().st_size > 0


@pytest.mark.slow
def test_registro_documentato():
    """describe() deve descrivere ogni effetto: e' cio' che vede l'agente MCP."""
    d = fx.describe()
    assert len(d) == len(fx.EFFECTS)
    for e in d:
        assert e["label"] and e["kind"] in ("video", "audio")
        for p in e["params"]:
            assert p["name"] and p["type"]
