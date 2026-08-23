"""Che il pacchetto dichiari davvero cio' su cui gira.

Il caso che ha motivato questo file: numpy era usato da analyze, colormatch,
review e vision ma non era in ``dependencies``. Sulla macchina di chi sviluppa
c'era gia', quindi i test passavano; chi installava da PyPI si ritrovava
music_beats, plan_edit, inspect_footage, match_color e check_cuts morti con un
"numpy richiesto". Un test che guarda l'ambiente non lo avrebbe mai visto: qui
si guarda il *dichiarato*.
"""

import sys
from pathlib import Path

import pytest

if sys.version_info < (3, 11):  # tomllib e' arrivato nella 3.11
    pytest.skip("serve tomllib", allow_module_level=True)

import tomllib

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@pytest.fixture(scope="module")
def meta() -> dict:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]


def _nomi(requisiti: list[str]) -> set[str]:
    """"numpy>=1.24" -> {"numpy"}; "faster-whisper" -> {"faster-whisper", "faster_whisper"}.

    Il nome della distribuzione e quello del modulo non sempre coincidono: il
    trattino diventa underscore all'import.
    """
    fuori = set()
    for r in requisiti:
        nome = r.split(";")[0].split("[")[0].strip()
        for sep in (">", "=", "<", "!", "~"):
            nome = nome.split(sep)[0]
        nome = nome.strip()
        fuori |= {nome, nome.replace("-", "_")}
    return fuori


def test_numpy_e_obbligatorio(meta):
    """Non e' un extra: senza, meta' degli strumenti di analisi non parte."""
    assert "numpy" in _nomi(meta["dependencies"])


def test_ultralytics_resta_un_extra(meta):
    """Si tira dietro torch: chi non fa reframe automatico non deve scaricarlo."""
    extra = meta.get("optional-dependencies", {})
    assert "ultralytics" in _nomi(extra["vision"])
    assert "ultralytics" not in _nomi(meta["dependencies"])


def test_gli_extra_degradano_con_un_messaggio_utile():
    """Se manca l'extra, l'errore deve dire cosa installare, non un ImportError."""
    from vedit import vision
    sorgente = Path(vision.__file__).read_text(encoding="utf8")
    assert "pip install ultralytics" in sorgente


def test_si_importa_solo_cio_che_e_dichiarato():
    """Ogni import di terze parti nel backend sta fra dipendenze o extra."""
    import ast

    with PYPROJECT.open("rb") as f:
        p = tomllib.load(f)["project"]
    dichiarati = _nomi(p["dependencies"])
    for req in p.get("optional-dependencies", {}).values():
        dichiarati |= _nomi(req)
    # nomi di distribuzione che non coincidono col modulo importato
    dichiarati |= {"multipart", "starlette", "pydantic", "PIL"}   # PIL <- pillow
    # torch non e' una dipendenza e non deve diventarlo: analyze lo prova solo
    # per sapere se c'e' una GPU per whisper, e senza ripiega su cpu.
    dichiarati |= {"torch"}

    pacchetto = Path(__file__).resolve().parents[1] / "backend" / "vedit"
    ignoti: dict[str, str] = {}
    for f in sorted(pacchetto.glob("*.py")):
        albero = ast.parse(f.read_text(encoding="utf8"))
        for nodo in ast.walk(albero):
            if isinstance(nodo, ast.Import):
                radici = [a.name.split(".")[0] for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                radici = [(nodo.module or "").split(".")[0]] if nodo.level == 0 else []
            else:
                continue
            for r in radici:
                if not r or r in dichiarati or r == "vedit":
                    continue
                if r in sys.stdlib_module_names:
                    continue
                ignoti.setdefault(r, f.name)
    assert not ignoti, f"import non dichiarati in pyproject: {ignoti}"
