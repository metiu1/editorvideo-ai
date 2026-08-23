"""Costruisce il pacchetto da pubblicare su PyPI.

Un solo passaggio in piu' rispetto a ``python -m build``, ma indispensabile:
l'interfaccia web va copiata *dentro* il pacchetto. Chi installa da PyPI non ha
Node e non puo' compilarla; se il pacchetto partisse senza, ``vedit ui`` e
``open_ui`` aprirebbero una pagina vuota.

    python scripts/build_wheel.py            # compila la UI e costruisce
    python scripts/build_wheel.py --no-ui    # riusa frontend/dist come sta

Escono ``dist/vedit_mcp-*.whl`` e ``.tar.gz``. Per pubblicare a mano:
``python -m twine upload dist/*`` (di norma ci pensa GitHub Actions al tag).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parents[1]
DIST_UI = RADICE / "frontend" / "dist"
DENTRO = RADICE / "backend" / "vedit" / "webui"
DIST = RADICE / "dist"


def esegui(cmd: list[str], cwd: Path) -> None:
    print(f"  $ {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=cwd, shell=(sys.platform == "win32"))
    if proc.returncode != 0:
        raise SystemExit(f"fallito: {' '.join(cmd)}")


def compila_ui() -> None:
    front = RADICE / "frontend"
    if not (front / "node_modules").is_dir():
        esegui(["npm", "ci"], front)
    esegui(["npm", "run", "build"], front)


def copia_ui() -> None:
    if not (DIST_UI / "index.html").is_file():
        raise SystemExit(
            f"manca {DIST_UI}/index.html: compila l'interfaccia prima "
            "(`cd frontend && npm run build`) o togli --no-ui"
        )
    shutil.rmtree(DENTRO, ignore_errors=True)
    shutil.copytree(DIST_UI, DENTRO)
    peso = sum(f.stat().st_size for f in DENTRO.rglob("*") if f.is_file())
    print(f"  interfaccia copiata in {DENTRO} ({peso / 1e6:.1f} MB)")


def main() -> int:
    ap = argparse.ArgumentParser(description="costruisce il pacchetto per PyPI")
    ap.add_argument("--no-ui", action="store_true", help="non ricompilare la UI, usa frontend/dist")
    ap.add_argument("--keep", action="store_true", help="lascia backend/vedit/webui dopo la build")
    a = ap.parse_args()

    print("1. interfaccia web")
    if not a.no_ui:
        compila_ui()
    copia_ui()

    print("2. pacchetto")
    shutil.rmtree(DIST, ignore_errors=True)
    esegui([sys.executable, "-m", "build"], RADICE)

    if not a.keep:
        # in sviluppo la copia dentro il pacchetto avrebbe la precedenza su
        # frontend/dist, e `npm run build` sembrerebbe non avere effetto
        shutil.rmtree(DENTRO, ignore_errors=True)

    print("\nfatto:")
    for f in sorted(DIST.glob("*")):
        print(f"  {f.name}  ({f.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
