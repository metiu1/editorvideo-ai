"""L'interfaccia aperta dall'agente.

Il punto delicato non e' che il server parta: e' che agente e interfaccia
lavorino sullo *stesso* progetto in memoria. Due Store sullo stesso file
significherebbe due scrittori e l'ultimo che salva vince — esattamente il
guaio che open_ui deve togliere di mezzo.
"""

import json
import urllib.request

import pytest

from vedit import api
from vedit import mcp_server as srv


def _out(result):
    data = result.structured_content
    if data is None:
        blocchi = [json.loads(c.text) for c in result.content if getattr(c, "text", None)]
        return blocchi[0] if len(blocchi) == 1 else blocchi
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


async def call(_tool: str, **args):
    return _out(await srv.mcp.call_tool(_tool, args))


@pytest.fixture(autouse=True)
def _pulizia():
    srv._stores.clear()
    srv._current[0] = None
    yield
    api.stop_background()
    if api.S.store is not None:
        api.S.store.on_change = None
    api.S.store = None


@pytest.mark.anyio
async def test_apre_e_condivide_il_progetto(tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    esito = await call("open_ui", open_browser=False, port=8791)

    assert esito["url"].startswith("http://127.0.0.1:")
    assert esito["avviato_ora"] is True
    # stesso oggetto, non una seconda copia letta da disco: un solo scrittore
    assert api.S.store is srv._stores[srv._current[0]]

    # il server risponde davvero, e serve qualcosa alla radice (interfaccia
    # compilata o il messaggio che spiega come compilarla)
    with urllib.request.urlopen(esito["url"] + "/", timeout=10) as r:
        assert r.status == 200
    assert api.S.store.project.settings.width == 1280


@pytest.mark.anyio
async def test_riaprire_non_riavvia(tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"))
    primo = await call("open_ui", open_browser=False, port=8792)
    secondo = await call("open_ui", open_browser=False, port=8792)
    assert secondo["avviato_ora"] is False
    assert secondo["url"] == primo["url"]


@pytest.mark.anyio
async def test_cambio_progetto_segue_linterfaccia(tmp_path):
    await call("project_create", path=str(tmp_path / "uno.json"))
    await call("open_ui", open_browser=False, port=8793)
    await call("project_create", path=str(tmp_path / "due.json"))
    # l'interfaccia deve seguire l'agente, non restare sul progetto di prima
    assert api.S.store.path.endswith("due.json")
    assert api.S.store is srv._stores[srv._current[0]]


@pytest.mark.anyio
async def test_le_modifiche_dellagente_avvisano_linterfaccia(assets, tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"), preset="720p")
    await call("open_ui", open_browser=False, port=8794)

    eventi = []
    api.S.publish = lambda e: eventi.append(e)

    media = await call("import_media", files=[assets["red"]])
    await call("add_clip", media=media[0]["id"], duration=1.0)
    assert {"type": "project"} in eventi


@pytest.mark.anyio
async def test_close_ui(tmp_path):
    await call("project_create", path=str(tmp_path / "p.json"))
    await call("open_ui", open_browser=False, port=8795)
    assert (await call("close_ui"))["chiusa"] is True
    assert api.background_info() is None
    assert (await call("close_ui"))["chiusa"] is False


def test_un_osservatore_rotto_non_blocca_la_modifica(tmp_path):
    from vedit.store import Store

    s = Store.create(path=str(tmp_path / "p.json"))
    s.on_change = lambda: 1 / 0
    s.add_track(kind="video")          # non deve sollevare
    assert len(s.project.tracks) == 3


def test_interfaccia_cercata_prima_nel_pacchetto(tmp_path, monkeypatch):
    """Installato da pip la UI sta in vedit/webui; da repo in frontend/dist."""
    finto = tmp_path / "vedit"
    (finto / "webui").mkdir(parents=True)
    (finto / "webui" / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(api, "__file__", str(finto / "api.py"))
    assert api._frontend_dir() == finto / "webui"
