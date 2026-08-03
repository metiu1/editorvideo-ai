"""API della UI. Le stesse operazioni del server MCP, esposte via HTTP."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vedit import api as api_mod


@pytest.fixture
def client(tmp_path):
    api_mod.S.store = None
    api_mod.S.jobs.clear()
    with TestClient(api_mod.app) as c:
        yield c


def _create(client, tmp_path, preset="720p"):
    r = client.post("/api/project/create", json={"path": str(tmp_path / "p.json"), "preset": preset})
    assert r.status_code == 200
    return r.json()


def test_stato_iniziale(client):
    s = client.get("/api/state").json()
    assert s["project"] is None
    assert any(e["name"] == "chromakey" for e in s["effects"])
    assert "1080p" in s["presets"]
    assert s["system"]["ffmpeg"]


def test_operazioni_e_revisione(client, tmp_path, assets):
    _create(client, tmp_path)
    rev0 = client.get("/api/state").json()["revision"]

    r = client.post("/api/op/import_media", json={"paths": [assets["red"]]})
    assert r.status_code == 200
    media_id = r.json()["result"][0]["id"]

    r = client.post("/api/op/add_clip", json={"media_id": media_id, "duration": 2.0})
    body = r.json()
    assert body["project"]["duration"] == pytest.approx(2.0)
    assert body["revision"] != rev0  # la revisione invalida le anteprime in cache

    clip_id = body["result"]["id"]
    r = client.post("/api/op/split_clip", json={"clip_id": clip_id, "at": 1.0})
    assert r.status_code == 200
    assert len(r.json()["project"]["tracks"][0]["clips"]) == 2

    # undo/redo passano dallo stesso canale
    assert client.post("/api/op/undo", json={}).json()["project"]["tracks"][0]["clips"].__len__() == 1
    assert client.post("/api/op/redo", json={}).json()["project"]["tracks"][0]["clips"].__len__() == 2


def test_errori_http(client, tmp_path):
    assert client.post("/api/op/add_clip", json={"media_id": "x"}).status_code == 400
    _create(client, tmp_path)
    r = client.post("/api/op/add_clip", json={"media_id": "fantasma"})
    assert r.status_code == 400 and "inesistente" in r.json()["detail"]

    assert client.post("/api/op/formatta_il_disco", json={}).status_code == 404
    r = client.post("/api/op/add_clip", json={"parametro_sbagliato": 1})
    assert r.status_code == 400


def test_browse(client, tmp_path, assets):
    r = client.get("/api/browse", params={"path": str(Path(assets["red"]).parent)})
    data = r.json()
    assert any(f["name"] == "red.mp4" for f in data["files"])
    assert data["parent"]
    assert client.get("/api/browse", params={"path": str(tmp_path / "nope")}).status_code == 404


@pytest.mark.slow
def test_frame_e_anteprima(client, tmp_path, assets):
    _create(client, tmp_path)
    # sorgente con dettaglio (testsrc2): un colore piatto comprimerebbe a poche centinaia di byte
    mid = client.post("/api/op/import_media", json={"paths": [assets["blue"]]}).json()["result"][0]["id"]
    client.post("/api/op/add_clip", json={"media_id": mid, "duration": 2.0})

    r = client.get("/api/frame", params={"t": 1.0, "width": 320})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert len(r.content) > 1000

    r = client.get("/api/preview", params={"start": 0.0, "duration": 1.0, "height": 180})
    assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
    assert len(r.content) > 1000


def test_cartelle_del_bin(client, tmp_path, assets):
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]

    r = client.post("/api/op/set_media", json={"media_id": mid, "folder": "b-roll/citta"})
    assert r.json()["project"]["media"][0]["folder"] == "b-roll/citta"

    r = client.post("/api/op/rename_folder", json={"old": "b-roll", "new": "riprese"})
    assert r.json()["result"] == 1
    assert client.get("/api/state").json()["project"]["media"][0]["folder"] == "riprese/citta"

    # un media in uso non sparisce per sbaglio
    client.post("/api/op/add_clip", json={"media_id": mid, "duration": 1.0})
    r = client.post("/api/op/remove_media", json={"media_id": mid})
    assert r.status_code == 400 and "force" in r.json()["detail"]
    r = client.post("/api/op/remove_media", json={"media_id": mid, "force": True})
    assert r.json()["result"]["clip_eliminate"] == 1


def test_transizione_via_api(client, tmp_path, assets):
    _create(client, tmp_path)
    ids = [m["id"] for m in client.post(
        "/api/op/import_media", json={"paths": [assets["red"], assets["green"]]}).json()["result"]]
    a = client.post("/api/op/add_clip", json={"media_id": ids[0], "duration": 2.0}).json()["result"]
    b = client.post("/api/op/add_clip", json={"media_id": ids[1], "duration": 2.0}).json()["result"]

    r = client.post("/api/op/crossfade",
                    json={"clip_a": a["id"], "clip_b": b["id"], "duration": 0.5, "type": "iris"})
    assert r.json()["result"]["type"] == "iris"
    clip = r.json()["project"]["tracks"][0]["clips"][0]
    assert clip["transition"]["type"] == "iris"

    r = client.post("/api/op/crossfade",
                    json={"clip_a": a["id"], "clip_b": b["id"], "type": "tenda"})
    assert r.status_code == 400 and "sconosciuta" in r.json()["detail"]


@pytest.mark.slow
def test_filmstrip_e_stream(client, tmp_path, assets):
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["blue"]]}).json()["result"][0]["id"]

    info = client.get(f"/api/media/{mid}/strip", params={"height": 40}).json()
    assert info["tiles"] >= 1 and info["tile_height"] == 40
    assert client.get(info["url"].replace("/api/file?path=", "/api/file?path=")).status_code == 200

    r = client.get(f"/api/media/{mid}/stream")
    assert r.status_code == 200 and len(r.content) > 1000

    wf = client.get(f"/api/media/{mid}/waveform").json()
    assert len(wf["peaks"]) > 5 and max(wf["peaks"]) <= 1.0


@pytest.mark.slow
def test_upload_da_drag_and_drop(client, tmp_path, assets):
    _create(client, tmp_path)
    with open(assets["green"], "rb") as fh:
        r = client.post("/api/upload", files={"files": ("green.mp4", fh, "video/mp4")},
                        data={"folder": "trascinati"})
    body = r.json()
    assert len(body["importati"]) == 1
    m = body["project"]["media"][0]
    assert m["folder"] == "trascinati"
    assert (tmp_path / "media" / "green.mp4").exists()


@pytest.mark.slow
def test_prefetch_segmento(client, tmp_path, assets):
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]
    client.post("/api/op/add_clip", json={"media_id": mid, "duration": 3.0})

    assert client.post("/api/preview/prefetch",
                       params={"start": 1.0, "duration": 1.0, "height": 90}).json()["avviato"]
    # oltre la fine non c'e' niente da preparare
    assert client.post("/api/preview/prefetch", params={"start": 99.0}).json().get("skip")

    for _ in range(60):
        r = client.get("/api/preview", params={"start": 1.0, "duration": 1.0, "height": 90})
        if r.status_code == 200:
            break
        time.sleep(0.5)
    assert r.status_code == 200


@pytest.mark.slow
def test_render_in_background(client, tmp_path, assets):
    _create(client, tmp_path)
    mid = client.post("/api/op/import_media", json={"paths": [assets["red"]]}).json()["result"][0]["id"]
    client.post("/api/op/add_clip", json={"media_id": mid, "duration": 1.0})

    out = str(tmp_path / "out.mp4")
    job = client.post("/api/render", json={"output": out, "quality": "draft"}).json()
    assert job["state"] == "running"

    for _ in range(120):
        job = client.get(f"/api/render/{job['id']}").json()
        if job["state"] != "running":
            break
        time.sleep(0.5)
    assert job["state"] == "done", job.get("error")
    assert Path(out).stat().st_size > 0
