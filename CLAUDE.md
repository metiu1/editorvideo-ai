# vedit

Editor video non lineare guidabile da UI web, assistente in chat e server MCP — stesso motore
per tutti e tre.

**Solo per usarlo: `claude mcp add vedit -- uvx vedit-mcp`** — pacchetto PyPI `vedit-mcp`,
interfaccia web inclusa, niente clone. ffmpeg mancante: `vedit install-ffmpeg`.

**Per modificarlo, partenza da zero: `python scripts/setup.py`** (aggiungi `--json` se ti serve l'esito in forma
leggibile da programma). Installa dipendenze, compila l'interfaccia, registra il server MCP e
verifica con `vedit doctor` e i test.

Le istruzioni complete — verifica, mappa del codice, regole per modificarlo, uso da MCP — sono
in @AGENTS.md e valgono per qualunque agente.
