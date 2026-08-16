"""Memoria del montaggio: marker con note e versioni da confrontare.

Due mancanze che si pagano quando il lavoro dura piu' di una sessione:

- **marker** - "qui il committente ha detto che non funziona", "manca il b-roll":
  senza, la ragione di un taglio evapora e si rifanno gli stessi errori;
- **snapshot** - undo torna indietro, ma non permette di tenere *due* montaggi e
  scegliere. Uno snapshot e' una copia nominata del progetto, e ``compare`` dice
  in cosa differiscono senza doverli guardare entrambi.
"""

from __future__ import annotations

import json
from pathlib import Path

from .model import Marker

KINDS = ("nota", "da_fare", "problema", "approvato")


# --------------------------------------------------------------------------
# marker
# --------------------------------------------------------------------------


def add_marker(store, t: float, note: str = "", kind: str = "nota",
               duration: float = 0.0) -> dict:
    """Ancora una nota a un istante (o a una regione, con duration > 0)."""
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} sconosciuto; scegli tra {list(KINDS)}")
    if t < 0:
        raise ValueError("il tempo non puo' essere negativo")
    store._touch()
    m = Marker(t=round(float(t), 3), duration=round(max(0.0, duration), 3),
               note=note.strip(), kind=kind)
    store.project.markers.append(m)
    store.project.markers.sort(key=lambda x: x.t)
    store._done()
    return _view(m)


def markers(store, kind: str | None = None, start: float | None = None,
            end: float | None = None) -> list[dict]:
    """I marker, filtrabili per tipo e per tratto."""
    out = []
    for m in sorted(store.project.markers, key=lambda x: x.t):
        if kind and m.kind != kind:
            continue
        if start is not None and m.t + m.duration < start:
            continue
        if end is not None and m.t > end:
            continue
        out.append(_view(m))
    return out


def remove_marker(store, marker_id: str) -> dict:
    m = next((x for x in store.project.markers if x.id == marker_id), None)
    if m is None:
        raise ValueError(f"marker {marker_id!r} inesistente")
    store._touch()
    store.project.markers.remove(m)
    store._done()
    return {"rimosso": marker_id}


def _view(m: Marker) -> dict:
    out = {"id": m.id, "t": m.t, "kind": m.kind, "note": m.note}
    if m.duration:
        out["duration"] = m.duration
    return out


# --------------------------------------------------------------------------
# snapshot
# --------------------------------------------------------------------------


def _dir(store) -> Path:
    if not store.path:
        raise ValueError("il progetto non e' su disco: salvalo prima di usare gli snapshot")
    d = Path(store.path).with_suffix("") .parent / (Path(store.path).stem + ".versioni")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(name: str) -> str:
    pulito = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name).strip()
    if not pulito:
        raise ValueError("nome dello snapshot vuoto")
    return pulito.replace(" ", "_")[:60]


def snapshot(store, name: str, note: str = "") -> dict:
    """Salva una copia nominata del progetto. Non tocca il montaggio corrente."""
    f = _dir(store) / f"{_safe(name)}.json"
    dati = store.project.to_dict()
    dati["_snapshot"] = {"nome": name, "nota": note,
                         "durata": store.project.duration()}
    f.write_text(json.dumps(dati, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"nome": name, "file": str(f.resolve()), "durata": store.project.duration(),
            "clip": _conta_clip(store.project.to_dict())}


def snapshots(store) -> list[dict]:
    """Le versioni salvate, dalla piu' recente."""
    out = []
    for f in sorted(_dir(store).glob("*.json"), key=lambda p: -p.stat().st_mtime):
        try:
            dati = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        meta = dati.get("_snapshot", {})
        out.append({"nome": meta.get("nome", f.stem), "nota": meta.get("nota", ""),
                    "durata": round(float(meta.get("durata", 0)), 3),
                    "clip": _conta_clip(dati), "file": str(f)})
    return out


def restore(store, name: str) -> dict:
    """Riporta il progetto a uno snapshot. E' una modifica: si annulla con undo."""
    f = _dir(store) / f"{_safe(name)}.json"
    if not f.exists():
        raise ValueError(f"snapshot {name!r} inesistente; disponibili: "
                         f"{[s['nome'] for s in snapshots(store)]}")
    dati = json.loads(f.read_text(encoding="utf-8"))
    dati.pop("_snapshot", None)
    store._touch()                       # cosi' il ritorno indietro e' annullabile
    from .model import Project
    store.project = Project.from_obj(dati)
    store._done()
    return {"ripristinato": name, "durata": store.project.duration(),
            "clip": _conta_clip(dati)}


def compare(store, a: str, b: str | None = None) -> dict:
    """Differenze tra due snapshot (o tra uno snapshot e il montaggio corrente)."""
    prima = _carica(store, a)
    dopo = store.project.to_dict() if b is None else _carica(store, b)
    etichetta_b = "corrente" if b is None else b

    ca, cb = _clip_index(prima), _clip_index(dopo)
    aggiunte = sorted(set(cb) - set(ca))
    tolte = sorted(set(ca) - set(cb))
    spostate = [k for k in set(ca) & set(cb) if ca[k] != cb[k]]

    return {
        "a": a, "b": etichetta_b,
        "durata": {a: _durata(prima), etichetta_b: _durata(dopo)},
        "clip": {a: _conta_clip(prima), etichetta_b: _conta_clip(dopo)},
        "aggiunte": len(aggiunte), "tolte": len(tolte), "modificate": len(spostate),
        "dettaglio": {
            "aggiunte": aggiunte[:10], "tolte": tolte[:10],
            "modificate": [{"clip": k, "prima": ca[k], "dopo": cb[k]}
                           for k in sorted(spostate)[:10]],
        },
        "uguali": not (aggiunte or tolte or spostate)
                  and abs(_durata(prima) - _durata(dopo)) < 1e-3,
    }


def _carica(store, name: str) -> dict:
    f = _dir(store) / f"{_safe(name)}.json"
    if not f.exists():
        raise ValueError(f"snapshot {name!r} inesistente")
    return json.loads(f.read_text(encoding="utf-8"))


def _conta_clip(dati: dict) -> int:
    return sum(len(t.get("clips", [])) for t in dati.get("tracks", []))


def _durata(dati: dict) -> float:
    fine = 0.0
    for t in dati.get("tracks", []):
        for c in t.get("clips", []):
            if c.get("enabled", True):
                fine = max(fine, float(c.get("start", 0)) + float(c.get("duration", 0)))
    return round(fine, 3)


def _clip_index(dati: dict) -> dict:
    """id clip -> posizione e durata: basta per dire cosa e' cambiato."""
    out = {}
    for t in dati.get("tracks", []):
        for c in t.get("clips", []):
            out[c.get("id", "?")] = {
                "traccia": t.get("id"), "start": round(float(c.get("start", 0)), 3),
                "durata": round(float(c.get("duration", 0)), 3),
                "in": round(float(c.get("in", 0)), 3),
            }
    return out
