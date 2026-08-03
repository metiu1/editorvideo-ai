"""Il server MCP deve funzionare passando dal protocollo, non solo chiamando le
funzioni python: e' cosi' che lo usera' l'agente.
"""

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from vedit import mcp_server as srv


def _out(result):
    """Contenuto della risposta: strutturato se c'e', altrimenti il JSON testuale."""
    data = result.structured_content
    if data is None:
        blocks = [json.loads(c.text) for c in result.content if getattr(c, "text", None)]
        return blocks[0] if len(blocks) == 1 else blocks
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


async def call(_tool: str, **args):
    return _out(await srv.mcp.call_tool(_tool, args))


@pytest.fixture(autouse=True)
def _reset():
    srv._stores.clear()
    srv._current[0] = None
    yield


@pytest.mark.anyio
async def test_elenco_strumenti():
    tools = await srv.mcp.list_tools()
    names = {t.name for t in tools}
    for atteso in ("project_create", "import_media", "add_clip", "split", "set_speed",
                   "add_effect", "render_video", "preview_frame", "normalize_audio"):
        assert atteso in names
    for t in tools:
        assert t.description, f"{t.name} senza descrizione"


@pytest.mark.anyio
async def test_flusso_completo(assets, tmp_path):
    """Monta un video passando solo dagli strumenti MCP."""
    p = str(tmp_path / "prog.json")
    await call("project_create", path=p, name="test", preset="720p")

    media = await call("import_media", paths=[assets["red"], assets["blue"], assets["music"]])
    assert len(media) == 3
    red, blue, music = [m["id"] for m in media]

    c1 = await call("add_clip", media=red, duration=3.0)
    c2 = await call("add_clip", media=blue, duration=3.0)
    assert c2["start"] == pytest.approx(3.0)

    parts = await call("split", clip=c1["id"], at=1.5)
    assert parts["dopo"]["start"] == pytest.approx(1.5)

    sped = await call("set_speed", clip=c2["id"], speed=2.0)
    assert sped["duration"] == pytest.approx(1.5)

    await call("add_effect", clip=c2["id"], type="color", params={"saturation": 1.4})
    await call("set_transform", clip=c2["id"],
               scale={"kf": [{"t": 0, "v": 1.0}, {"t": 1.5, "v": 1.3}]})
    await call("add_text", text="Titolo", start=0.0, duration=2.0, font_size=60, box=True)

    a2 = await call("add_track", kind="audio", name="musica")
    m2 = await call("add_clip", media=music, track=a2["id"], start=0.0, duration=4.0)
    await call("set_audio", clip=m2["id"], gain_db=-12)

    info = await call("project_info")
    assert info["duration"] > 0
    assert len(info["tracks"]) == 3
    assert c2["id"] in [c["id"] for c in info["tracks"][0]["clips"]]

    res = await call("render_video", output=str(tmp_path / "out.mp4"), preview=True)
    assert res["mb"] > 0


@pytest.mark.anyio
async def test_errori_sono_parlanti(tmp_path):
    with pytest.raises(ToolError, match="nessun progetto aperto"):
        await call("add_clip", media="x")

    await call("project_create", path=str(tmp_path / "p.json"))
    with pytest.raises(ToolError, match="inesistente"):
        await call("add_clip", media="fantasma")
    with pytest.raises(ToolError):
        await call("add_effect", type="nonesiste")
    with pytest.raises(ToolError, match="sconosciuti"):
        await call("add_effect", type="blur", params={"raggio": 3})


@pytest.mark.anyio
async def test_catalogo_effetti():
    audio = await call("list_effects", kind="audio")
    assert audio and all(e["kind"] == "audio" for e in audio)
    assert any(e["name"] == "compressor" for e in audio)
    tutti = await call("list_effects")
    assert len(tutti) > len(audio)


@pytest.mark.anyio
async def test_undo_redo_via_mcp(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"))
    m = (await call("import_media", paths=[assets["red"]]))[0]
    await call("add_clip", media=m["id"])
    assert (await call("undo"))["undone"] is True
    assert len(_tracks(await call("project_info"))) == 0
    assert (await call("redo"))["redone"] is True
    assert len(_tracks(await call("project_info"))) == 1


def _tracks(info):
    return info["tracks"][0]["clips"]


@pytest.mark.anyio
@pytest.mark.slow
async def test_preview_frame_restituisce_immagine(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    m = (await call("import_media", paths=[assets["blue"]]))[0]
    await call("add_clip", media=m["id"])
    r = await srv.mcp.call_tool("preview_frame", {"t": 1.0, "width": 320,
                                                 "path": str(tmp_path / "f.jpg")})
    assert not r.is_error
    assert "image" in [getattr(c, "type", None) for c in r.content]
