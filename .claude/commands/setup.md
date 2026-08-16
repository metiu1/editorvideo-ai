---
description: Installa vedit da zero (dipendenze, UI, server MCP) e verifica che funzioni
allowed-tools: Bash, Read, Edit
---

Porta questa repo da copia appena clonata a editor funzionante.

1. Esegui `python scripts/setup.py --json $ARGUMENTS` dalla radice della repo (dai tempo: la
   prima volta compila l'interfaccia e gira i test, qualche minuto).
2. Leggi il JSON finale: `result` vale `ok`, `warn` o `fail`. Per ogni passo non riuscito
   applica il rimedio in `hint` e rilancia solo quello che serve — lo script è idempotente.
   I casi noti (ffmpeg mancante, `externally-managed-environment`, eseguibile in uso su
   Windows, npm assente) sono in @AGENTS.md sezione 1.
3. Se ffmpeg manca e non c'è un motivo per non farlo, riprova con `--install-ffmpeg`.
4. Riferisci in poche righe: esito, cosa è stato installato, cosa resta spento e perché
   (assistente in chat senza `ANTHROPIC_API_KEY`, UI senza Node, …), e i comandi per iniziare
   (`vedit ui`, `vedit new film.json`).

Non modificare il codice del progetto per far passare l'installazione: se qualcosa non va,
spiega cosa manca nell'ambiente.
