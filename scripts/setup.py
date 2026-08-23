#!/usr/bin/env python3
"""Installazione completa di vedit con un comando solo.

    python scripts/setup.py

Fa tutto quello che serve per passare da una copia appena clonata a un editor
funzionante: dipendenze Python, interfaccia compilata, server MCP registrato,
controllo finale. Usa solo la libreria standard, cosi' si puo' lanciare prima
di aver installato qualunque cosa.

E' pensato anche per essere eseguito da un agente: ogni passo stampa una riga
`[ok]` / `[--]` / `[!!]`, alla fine c'e' un riepilogo, e con `--json` l'intero
esito esce come oggetto JSON sull'ultima riga.

Rilanciarlo e' sempre sicuro: i passi gia' a posto vengono saltati.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
VENV = ROOT / ".venv"
MIN_PY = (3, 10)

OK, SKIP, WARN, FAIL = "ok", "skip", "warn", "fail"
_MARK = {OK: "[ok]", SKIP: "[--]", WARN: "[!!]", FAIL: "[XX]"}

_report: list[dict] = []
_quiet_json = False


# ---------------------------------------------------------------- utilita'

def say(text: str = "") -> None:
    if not _quiet_json:
        print(text, flush=True)


def step(name: str, status: str, detail: str = "", hint: str = "") -> str:
    _report.append({"step": name, "status": status, "detail": detail, "hint": hint})
    say(f"{_MARK[status]} {name:22} {detail}")
    if hint and status in (WARN, FAIL):
        say(f"     -> {hint}")
    return status


def run(cmd: list[str], cwd: Path | None = None, capture: bool = True,
        timeout: int = 1800) -> tuple[int, str]:
    """Esegue un comando. Torna (codice, output). Non solleva mai."""
    try:
        if capture:
            p = subprocess.run(cmd, cwd=cwd, timeout=timeout, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            return p.returncode, (p.stdout or "").strip()
        p = subprocess.run(cmd, cwd=cwd, timeout=timeout)
        return p.returncode, ""
    except FileNotFoundError:
        return 127, f"comando non trovato: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout dopo {timeout}s: {' '.join(cmd)}"
    except OSError as exc:  # permessi, exec format, ...
        return 126, str(exc)


def tail(text: str, lines: int = 12) -> str:
    got = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(got[-lines:])


def which(name: str) -> str | None:
    return shutil.which(name)


# ------------------------------------------------------------------ passi

def check_python() -> str:
    v = sys.version_info
    got = f"{v.major}.{v.minor}.{v.micro}"
    if v[:2] < MIN_PY:
        return step("python", FAIL, got,
                    f"serve Python {MIN_PY[0]}.{MIN_PY[1]}+, rilancia con un interprete piu' recente")
    return step("python", OK, f"{got} ({platform.system()})")


_FFMPEG_HINT = {
    "Windows": "winget install Gyan.FFmpeg   (oppure ffmpeg.org/download, build 'essentials')",
    "Darwin": "brew install ffmpeg",
    "Linux": "sudo apt install ffmpeg   (o il gestore pacchetti della tua distribuzione)",
}


def _ffmpeg_path(name: str) -> str | None:
    env = os.environ.get(f"VEDIT_{name.upper()}")
    if env and Path(env).exists():
        return env
    return which(name)


def _install_ffmpeg() -> bool:
    """Prova a installare ffmpeg col gestore pacchetti del sistema."""
    system = platform.system()
    candidates: list[list[str]] = []
    if system == "Windows" and which("winget"):
        candidates.append(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                           "--accept-package-agreements", "--accept-source-agreements"])
    elif system == "Darwin" and which("brew"):
        candidates.append(["brew", "install", "ffmpeg"])
    elif system == "Linux":
        if which("apt-get"):
            candidates.append(["sudo", "apt-get", "install", "-y", "ffmpeg"])
        elif which("dnf"):
            candidates.append(["sudo", "dnf", "install", "-y", "ffmpeg"])
        elif which("pacman"):
            candidates.append(["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"])
    for cmd in candidates:
        say(f"     installo ffmpeg: {' '.join(cmd)}")
        code, _ = run(cmd, capture=False, timeout=1800)
        if code == 0:
            return True
    return False


def check_ffmpeg(auto: bool) -> str:
    ff, fp = _ffmpeg_path("ffmpeg"), _ffmpeg_path("ffprobe")
    if (not ff or not fp) and auto:
        if _install_ffmpeg():
            ff, fp = _ffmpeg_path("ffmpeg"), _ffmpeg_path("ffprobe")
    if not ff or not fp:
        mancante = "ffmpeg" if not ff else "ffprobe"
        return step("ffmpeg", FAIL, f"{mancante} non trovato",
                    _FFMPEG_HINT.get(platform.system(), "installa ffmpeg e mettilo nel PATH")
                    + "   |   oppure: python scripts/setup.py --install-ffmpeg"
                    + "   |   oppure: vedit install-ffmpeg (scarica i binari in ~/.vedit/bin,"
                      " senza amministratore)"
                    + "   |   oppure: indica il percorso con VEDIT_FFMPEG / VEDIT_FFPROBE")
    code, out = run([ff, "-version"])
    ver = out.splitlines()[0].split(" ")[2] if code == 0 and out else "?"
    return step("ffmpeg", OK, f"{ver}  ({ff})")


def _venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _bin_dir(py: Path) -> Path:
    return py.parent


def _externally_managed(out: str) -> bool:
    return "externally-managed-environment" in out or "externally managed" in out


def _file_locked(out: str) -> bool:
    """Eseguibile in uso: succede su Windows se UI o server MCP sono avviati."""
    return "WinError 32" in out or "Failed to write executable" in out


def _importable(py: Path) -> bool:
    return run([str(py), "-c", "import vedit"])[0] == 0


def _deps_ready(py: Path, extras: str) -> bool:
    """Vero se pacchetto e dipendenze obbligatorie sono gia' a posto."""
    mods = ["vedit", "vedit.api", "mcp", "fastapi", "uvicorn", "multipart"]
    if "dev" in extras:
        mods.append("pytest")
    return run([str(py), "-c", "import " + ", ".join(mods)])[0] == 0


def install_python_deps(py: Path, extras: str, force: bool = False,
                        retry: bool = True) -> tuple[str, Path]:
    """Installa il pacchetto in modalita' editabile. Torna (esito, interprete usato)."""
    target = f".[{extras}]" if extras else "."
    if not force and _deps_ready(py, extras):
        # reinstallare riscriverebbe vedit.exe / vedit-mcp.exe: su Windows fallisce
        # se l'agente tiene aperto il server MCP, e non servirebbe a niente
        return step("dipendenze", SKIP, "gia' installate (--reinstall per rifarle)"), py

    code, out = run([str(py), "-m", "pip", "install", "-e", target], cwd=ROOT)
    if code == 0:
        return step("dipendenze", OK, f"pip install -e {target}"), py

    if _externally_managed(out) and py == Path(sys.executable):
        # Python di sistema protetto (PEP 668): passo a un venv e riprovo
        say("     ambiente Python di sistema protetto, creo .venv")
        code_v, out_v = run([sys.executable, "-m", "venv", str(VENV)])
        if code_v != 0:
            return step("dipendenze", FAIL, "creazione .venv fallita", tail(out_v, 4)), py
        return install_python_deps(_venv_python(), extras, force=True)

    errori = [ln for ln in out.splitlines()
              if ln.startswith("ERROR") or "No matching distribution" in ln]
    if "chat" in extras and any("anthropic" in ln for ln in errori):
        # l'assistente e' facoltativo: senza il suo pacchetto il resto va uguale
        step("dipendenze", WARN, "extra 'chat' non installabile, riprovo senza",
             "l'assistente in chat restera' disattivo")
        return install_python_deps(py, extras.replace(",chat", "").replace("chat,", ""),
                                   force=True)

    if _file_locked(out):
        if retry:
            # pip lascia un .deleteme e al secondo colpo di solito passa
            time.sleep(2)
            return install_python_deps(py, extras, force=True, retry=False)
        if _deps_ready(py, extras):
            return step("dipendenze", WARN, "eseguibile in uso, installazione esistente tenuta",
                        "chiudi interfaccia web e server MCP, poi rilancia per aggiornarla"), py
        return step("dipendenze", FAIL, "eseguibile in uso (vedit.exe / vedit-mcp.exe)",
                    "chiudi interfaccia web e server MCP, poi rilancia questo script"), py

    return step("dipendenze", FAIL, f"pip install -e {target} fallito", tail(out)), py


def check_import(py: Path) -> str:
    code, out = run([str(py), "-c",
                     "import vedit, vedit.mcp_server, vedit.api; print(vedit.__file__)"])
    if code != 0:
        return step("import vedit", FAIL, "il pacchetto non si importa", tail(out, 6))
    return step("import vedit", OK, Path(out.strip()).parent.as_posix())


def build_frontend(force: bool) -> str:
    if not FRONTEND.exists():
        return step("interfaccia", SKIP, "cartella frontend assente")
    npm = which("npm")
    if not npm:
        return step("interfaccia", WARN, "npm non trovato",
                    "installa Node.js 18+ (nodejs.org) e rilancia: la UI web resta "
                    "non compilata, CLI e MCP funzionano lo stesso")
    dist = FRONTEND / "dist" / "index.html"
    if dist.exists() and not force:
        return step("interfaccia", SKIP, "frontend/dist gia' compilato (--rebuild per rifarla)")

    if not (FRONTEND / "node_modules").exists():
        say("     npm install ...")
        cmd = ["npm", "ci"] if (FRONTEND / "package-lock.json").exists() else ["npm", "install"]
        code, out = run(cmd, cwd=FRONTEND, timeout=1800)
        if code != 0 and cmd[1] == "ci":  # lockfile disallineato: ripiego
            code, out = run(["npm", "install"], cwd=FRONTEND, timeout=1800)
        if code != 0:
            return step("interfaccia", WARN, "npm install fallito", tail(out))

    say("     npm run build ...")
    code, out = run(["npm", "run", "build"], cwd=FRONTEND, timeout=1800)
    if code != 0 or not dist.exists():
        return step("interfaccia", WARN, "npm run build fallito", tail(out))
    return step("interfaccia", OK, "frontend/dist")


def _mcp_command(py: Path) -> list[str]:
    """Comando che avvia il server MCP con l'interprete giusto."""
    exe = _bin_dir(py) / ("vedit-mcp.exe" if os.name == "nt" else "vedit-mcp")
    if exe.exists():
        return [str(exe)]
    if which("vedit-mcp"):
        return ["vedit-mcp"]
    return [str(py), "-m", "vedit.mcp_server"]


def write_mcp_config(py: Path) -> str:
    """Allinea .mcp.json all'interprete usato davvero.

    Con l'installazione normale resta `vedit-mcp` e il file non viene toccato;
    dentro un venv serve il percorso assoluto, altrimenti l'agente non lo trova.
    """
    cmd = _mcp_command(py)
    cfg_path = ROOT / ".mcp.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    except json.JSONDecodeError:
        cfg = {}
    servers = cfg.setdefault("mcpServers", {})
    want = {"command": cmd[0], "args": cmd[1:], "env": {}}
    if servers.get("vedit") == want:
        return step("mcp .mcp.json", SKIP, "gia' allineato")
    servers["vedit"] = want
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return step("mcp .mcp.json", OK, " ".join(cmd))


def register_claude_mcp(py: Path) -> str:
    claude = which("claude")
    if not claude:
        return step("mcp claude", SKIP, "CLI claude non installata (basta .mcp.json)")
    code, out = run([claude, "mcp", "list"], timeout=120)
    if code == 0 and "vedit" in out:
        return step("mcp claude", SKIP, "server 'vedit' gia' registrato")
    cmd = _mcp_command(py)
    code, out = run([claude, "mcp", "add", "vedit", "--"] + cmd, timeout=120)
    if code != 0:
        return step("mcp claude", WARN, "registrazione fallita", tail(out, 4))
    return step("mcp claude", OK, "claude mcp add vedit")


def run_doctor(py: Path) -> str:
    code, out = run([str(py), "-m", "vedit.cli", "doctor"], cwd=ROOT, timeout=600)
    if code != 0:
        return step("vedit doctor", WARN, "controllo non superato", tail(out, 8))
    for line in out.splitlines():
        say(f"     {line}")
    return step("vedit doctor", OK, "ffmpeg, encoder e filtri verificati")


def run_tests(py: Path, full: bool) -> str:
    args = [str(py), "-m", "pytest", "-q"] + ([] if full else ["-m", "not slow"])
    code, out = run(args, cwd=ROOT, timeout=1800)
    riga = next((ln for ln in reversed(out.splitlines()) if "passed" in ln or "failed" in ln), "")
    if code != 0:
        return step("test", WARN, riga or "test falliti", tail(out, 15))
    return step("test", OK, riga)


# ------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    global _quiet_json
    ap = argparse.ArgumentParser(
        prog="setup.py", description="Installa vedit: dipendenze, UI, server MCP, verifica.")
    ap.add_argument("--venv", action="store_true",
                    help="crea e usa .venv invece dell'interprete corrente")
    ap.add_argument("--reinstall", action="store_true",
                    help="rifa' pip install anche se le dipendenze ci sono gia'")
    ap.add_argument("--no-chat", action="store_true",
                    help="non installare l'extra 'chat' (assistente Anthropic)")
    ap.add_argument("--no-frontend", action="store_true", help="salta la compilazione della UI")
    ap.add_argument("--rebuild", action="store_true", help="ricompila la UI anche se gia' presente")
    ap.add_argument("--no-mcp", action="store_true", help="non registrare il server MCP")
    ap.add_argument("--no-test", action="store_true", help="salta i test di verifica")
    ap.add_argument("--full-test", action="store_true", help="esegue anche i test lenti (render reali)")
    ap.add_argument("--install-ffmpeg", action="store_true",
                    help="prova a installare ffmpeg col gestore pacchetti del sistema")
    ap.add_argument("--json", action="store_true", help="stampa solo il riepilogo JSON")
    a = ap.parse_args(argv)
    _quiet_json = a.json

    t0 = time.time()
    say(f"vedit setup  ({ROOT})")
    say("")

    if check_python() == FAIL:
        return _finish(t0, 1)

    ffmpeg_ok = check_ffmpeg(a.install_ffmpeg) == OK

    py = Path(sys.executable)
    if a.venv:
        if not _venv_python().exists():
            code, out = run([sys.executable, "-m", "venv", str(VENV)])
            if code != 0:
                step("venv", FAIL, "creazione fallita", tail(out, 4))
                return _finish(t0, 1)
        py = _venv_python()
        step("venv", OK, py.as_posix())

    extras = "dev" if a.no_chat else "dev,chat"
    esito, py = install_python_deps(py, extras, force=a.reinstall)
    if esito == FAIL:
        return _finish(t0, 1)
    if check_import(py) == FAIL:
        return _finish(t0, 1)

    if a.no_frontend:
        step("interfaccia", SKIP, "--no-frontend")
    else:
        build_frontend(a.rebuild)

    if a.no_mcp:
        step("mcp", SKIP, "--no-mcp")
    else:
        write_mcp_config(py)
        register_claude_mcp(py)

    if ffmpeg_ok:
        run_doctor(py)
    else:
        step("vedit doctor", SKIP, "ffmpeg mancante")

    if a.no_test:
        step("test", SKIP, "--no-test")
    else:
        run_tests(py, a.full_test and ffmpeg_ok)

    return _finish(t0, 0 if ffmpeg_ok else 1, py)


def _finish(t0: float, code: int, py: Path | None = None) -> int:
    guasti = [r for r in _report if r["status"] == FAIL]
    avvisi = [r for r in _report if r["status"] == WARN]
    esito = "fail" if guasti or code else ("warn" if avvisi else "ok")

    if _quiet_json:
        print(json.dumps({
            "result": esito,
            "seconds": round(time.time() - t0, 1),
            "python": (py or Path(sys.executable)).as_posix(),
            "steps": _report,
        }, indent=2))
        return 0 if esito != "fail" else 1

    say("")
    say(f"esito: {esito.upper()}  in {time.time() - t0:.0f}s")
    if guasti or avvisi:
        for r in guasti + avvisi:
            say(f"  {_MARK[r['status']]} {r['step']}: {r['detail'].splitlines()[0] if r['detail'] else ''}")
            if r["hint"]:
                say(f"      {r['hint'].splitlines()[0]}")
    if not guasti:
        # dentro un venv il `vedit` del PATH non e' quello appena installato
        in_venv = py is not None and VENV in py.parents
        exe = f"{_bin_dir(py).as_posix()}/vedit" if in_venv else "vedit"
        say("")
        say("pronto:")
        say(f"  {exe} ui                 interfaccia web su http://127.0.0.1:8760")
        say(f"  {exe} new film.json      nuovo progetto da terminale")
        say("  l'agente trova il server MCP 'vedit' in .mcp.json")
    return 0 if esito != "fail" else 1


if __name__ == "__main__":
    sys.exit(main())
