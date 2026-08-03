"""Compilazione dei keyframe in espressioni ffmpeg.

Molti filtri ffmpeg valutano i loro parametri per ogni frame (overlay x/y,
rotate, eq con eval=frame, volume con eval=frame, ...). Sfruttiamo questo:
una lista di keyframe diventa una singola espressione ``if()`` annidata in
funzione di ``t``, quindi l'animazione costa zero passaggi extra.

Formato keyframe::

    {"kf": [{"t": 0.0, "v": 0.0, "ease": "ease_out"},
             {"t": 1.5, "v": 1.0}]}

``ease`` descrive la transizione *verso* il keyframe successivo e sta sul
keyframe di partenza del segmento.
"""

from __future__ import annotations

from typing import Any

EASINGS = (
    "linear",
    "hold",
    "ease_in",
    "ease_out",
    "ease_in_out",
    "ease_in_cubic",
    "ease_out_cubic",
    "ease_in_out_cubic",
)


def is_kf(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("kf"), list) and len(value["kf"]) > 0


def _sorted_keys(value: dict) -> list[dict]:
    return sorted(value["kf"], key=lambda k: float(k.get("t", 0.0)))


def _num(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# easing
# --------------------------------------------------------------------------


def _ease_expr(name: str, p: str) -> str:
    """Espressione ffmpeg per l'easing, ``p`` e' il progresso 0..1."""
    if name == "hold":
        return "0"
    if name == "ease_in":
        return f"({p})*({p})"
    if name == "ease_out":
        return f"(1-(1-({p}))*(1-({p})))"
    if name == "ease_in_out":
        return f"({p})*({p})*(3-2*({p}))"
    if name == "ease_in_cubic":
        return f"({p})*({p})*({p})"
    if name == "ease_out_cubic":
        return f"(1-(1-({p}))*(1-({p}))*(1-({p})))"
    if name == "ease_in_out_cubic":
        return f"if(lt({p},0.5),4*({p})*({p})*({p}),1-4*(1-({p}))*(1-({p}))*(1-({p})))"
    return p  # linear


def _ease_py(name: str, p: float) -> float:
    if name == "hold":
        return 0.0
    if name == "ease_in":
        return p * p
    if name == "ease_out":
        return 1 - (1 - p) ** 2
    if name == "ease_in_out":
        return p * p * (3 - 2 * p)
    if name == "ease_in_cubic":
        return p**3
    if name == "ease_out_cubic":
        return 1 - (1 - p) ** 3
    if name == "ease_in_out_cubic":
        return 4 * p**3 if p < 0.5 else 1 - 4 * (1 - p) ** 3
    return p


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


def sample(value: Any, t: float = 0.0, default: float = 0.0) -> float:
    """Valuta il parametro al tempo ``t`` in Python (preview, fallback statici)."""
    if not is_kf(value):
        return _num(value, default)
    keys = _sorted_keys(value)
    if t <= _num(keys[0].get("t")):
        return _num(keys[0].get("v"))
    if t >= _num(keys[-1].get("t")):
        return _num(keys[-1].get("v"))
    for a, b in zip(keys, keys[1:]):
        t0, t1 = _num(a.get("t")), _num(b.get("t"))
        if t0 <= t <= t1:
            v0, v1 = _num(a.get("v")), _num(b.get("v"))
            span = t1 - t0
            p = 0.0 if span <= 0 else (t - t0) / span
            return v0 + (v1 - v0) * _ease_py(str(a.get("ease", "linear")), p)
    return _num(keys[-1].get("v"))


def expr(value: Any, tvar: str = "t", default: float = 0.0) -> str:
    """Compila il parametro in un'espressione ffmpeg.

    ``tvar`` e' l'espressione del tempo *locale alla clip*: dentro la catena
    della clip e' ``"t"``, sul canvas della timeline e' ``"(t-<start>)"``.
    """
    if not is_kf(value):
        return _fmt(_num(value, default))

    keys = _sorted_keys(value)
    if len(keys) == 1:
        return _fmt(_num(keys[0].get("v")))

    out = _fmt(_num(keys[-1].get("v")))  # dopo l'ultimo keyframe: tiene il valore
    for a, b in reversed(list(zip(keys, keys[1:]))):
        t0, t1 = _num(a.get("t")), _num(b.get("t"))
        v0, v1 = _num(a.get("v")), _num(b.get("v"))
        span = t1 - t0
        if span <= 0:
            seg = _fmt(v1)
        else:
            p = f"(({tvar}-{_fmt(t0)})/{_fmt(span)})"
            e = _ease_expr(str(a.get("ease", "linear")), p)
            seg = f"({_fmt(v0)}+{_fmt(v1 - v0)}*({e}))"
        out = f"if(lt({tvar},{_fmt(t1)}),{seg},{out})"

    first_t = _num(keys[0].get("t"))
    return f"if(lt({tvar},{_fmt(first_t)}),{_fmt(_num(keys[0].get('v')))},{out})"


def animated(*values: Any) -> bool:
    return any(is_kf(v) for v in values)


def bounds(value: Any, default: float = 0.0) -> tuple[float, float]:
    """(min, max) dei valori assunti nei keyframe: serve per il dimensionamento."""
    if not is_kf(value):
        v = _num(value, default)
        return v, v
    vs = [_num(k.get("v")) for k in value["kf"]]
    return min(vs), max(vs)


def _fmt(x: float) -> str:
    """Numero senza notazione scientifica (ffmpeg non la accetta ovunque)."""
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def validate(value: Any) -> None:
    """Solleva ValueError se il blocco keyframe e' malformato."""
    if not isinstance(value, dict) or "kf" not in value:
        return
    kf = value["kf"]
    if not isinstance(kf, list) or not kf:
        raise ValueError("blocco keyframe vuoto o non lista")
    for k in kf:
        if not isinstance(k, dict) or "t" not in k or "v" not in k:
            raise ValueError(f"keyframe deve avere 't' e 'v': {k!r}")
        ease = str(k.get("ease", "linear"))
        if ease not in EASINGS:
            raise ValueError(f"easing sconosciuto {ease!r}, attesi: {', '.join(EASINGS)}")
