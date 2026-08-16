"""Il server MCP deve funzionare passando dal protocollo, non solo chiamando le
funzioni python: e' cosi' che lo usera' l'agente.
"""

import json
from pathlib import Path

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


@pytest.mark.anyio
async def test_project_open_rilegge_da_disco(assets, tmp_path):
    """Il file puo' cambiare fuori (UI, altro processo): open deve rileggerlo."""
    p = str(tmp_path / "p.json")
    await call("project_create", path=p)
    m = (await call("import_media", paths=[assets["red"]]))[0]
    await call("add_clip", media=m["id"])
    assert len(_tracks(await call("project_info"))) == 1

    # modifica dall'esterno, come farebbe la UI su un altro processo
    doc = json.loads(Path(p).read_text(encoding="utf-8"))
    doc["tracks"][0]["clips"] = []
    Path(p).write_text(json.dumps(doc), encoding="utf-8")

    await call("project_open", path=p)
    assert _tracks(await call("project_info")) == []


@pytest.mark.anyio
async def test_add_clips_monta_in_una_chiamata(assets, tmp_path):
    """Un montaggio serrato deve entrare con una chiamata, non con una per taglio."""
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    red, blue = [m["id"] for m in await call(
        "import_media", paths=[assets["red"], assets["blue"]])]

    res = await call("add_clips", clips=[
        {"media": red, "start": 0.0, "in": 1.0, "duration": 0.5},
        {"media": blue, "start": 0.5, "in": 0.5, "duration": 0.75},
        {"media": red, "start": 1.25, "in": 3.0, "duration": 0.5},
    ])
    assert res["aggiunte"] == 3
    assert res["fine"] == pytest.approx(1.75)

    clips = _tracks(await call("project_info"))
    assert [c["in"] for c in clips] == [1.0, 0.5, 3.0]

    # tre tagli restano una modifica sola: un undo li toglie tutti
    await call("undo")
    assert _tracks(await call("project_info")) == []


@pytest.mark.anyio
async def test_add_clips_non_lascia_montaggi_a_meta(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    red = (await call("import_media", paths=[assets["red"]]))[0]["id"]
    with pytest.raises(ToolError):
        await call("add_clips", clips=[
            {"media": red, "duration": 1.0},
            {"media": "fantasma", "duration": 1.0},
        ])
    assert _tracks(await call("project_info")) == []


@pytest.mark.anyio
async def test_move_effect_riordina(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    await call("add_effect", type="sharpen", params={"amount": 1.0})
    await call("add_effect", type="denoise", params={"strength": 3})
    res = await call("move_effect", index=1, to=0)
    assert res["catena"] == ["denoise", "sharpen"]


@pytest.mark.anyio
async def test_music_beats(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"))
    b = await call("music_beats", path=assets["music"], every=4, end=4.0)
    assert b["bpm"] > 0
    assert b["beat"] == pytest.approx(60.0 / b["bpm"], abs=1e-3)
    assert b["bar"] == pytest.approx(b["beat"] * 4, abs=1e-3)
    assert b["profilo"], "senza profilo non si trova lo stacco"
    assert b["griglia"] and all(t <= 4.0 for t in b["griglia"])


@pytest.mark.anyio
async def test_analisi_su_un_progetto_lo_dice(assets, tmp_path):
    """Passare il progetto dove va il girato e' l'errore naturale: va spiegato."""
    p = str(tmp_path / "p.json")
    await call("project_create", path=p)
    with pytest.raises(ToolError, match="e' un progetto, non del girato"):
        await call("inspect_footage", path=p)


@pytest.mark.anyio
async def test_inspect_footage_accetta_un_media(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"))
    m = (await call("import_media", paths=[assets["red"]]))[0]
    rep = await call("inspect_footage", media=m["id"])
    assert rep["verdict"] in ("keep", "trim", "drop")


@pytest.mark.anyio
async def test_sinonimi_degli_argomenti(assets, tmp_path):
    """files/paths e time/t sono lo stesso argomento: sbagliarlo non deve fermare."""
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    media = await call("import_media", files=[assets["red"]])
    await call("add_clip", media=media[0]["id"], duration=1.0)
    r = await srv.mcp.call_tool("preview_frame", {"time": 0.5, "width": 160})
    assert not r.is_error


def test_istruzioni_contengono_le_regole_di_montaggio():
    """Le istruzioni del server sono l'unica cosa che l'agente legge sempre.

    Dentro non c'e' solo come si chiamano gli strumenti: ci sono i difetti veri
    dei video che escono da qui — musica a volume fisso, solo stacchi secchi,
    inquadrature ripetute, un video che dopo dieci secondi non aggiunge piu'
    niente. Se sparisce quella parte, l'editor torna a produrli.
    """
    t = srv.ISTRUZIONI.lower()
    assert srv.mcp.instructions == srv.ISTRUZIONI
    for regola in ("musica", "stacchi", "due volte", "dieci secondi", "cinematografico"):
        assert regola in t, f"regola di montaggio persa: {regola}"
    # e devono restare agganciate a strumenti veri, non a buoni propositi
    for strumento in ("music_beats", "add_clips", "preview_grid", "set_transform",
                      "set_transition", "set_audio", "verify_edit"):
        assert strumento in srv.ISTRUZIONI, f"regola senza strumento: {strumento}"


@pytest.mark.anyio
async def test_gli_strumenti_citati_esistono_davvero():
    """Le istruzioni non devono promettere strumenti che non ci sono."""
    nomi = {t.name for t in await srv.mcp.list_tools()}
    citati = {p.strip(".,:;()") for p in srv.ISTRUZIONI.replace("\n", " ").split()
              if p.strip(".,:;()") in nomi or "_" in p}
    inventati = {c for c in citati if "_" in c and c.isidentifier() and c not in nomi}
    assert not inventati, f"strumenti citati ma inesistenti: {sorted(inventati)}"
