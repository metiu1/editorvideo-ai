# Istruzioni per un agente su questa repo

Questo file è il contratto per chi arriva qui con un agente di codice (Claude Code, Codex,
Cursor, Copilot…). Chi legge deve poter partire da una repo appena clonata e arrivare a un
editor funzionante senza fare domande.

`CLAUDE.md` importa questo file: le istruzioni sono le stesse per tutti.

---

## 0. Se devi solo *usarlo*

Il pacchetto sta su PyPI col nome `vedit-mcp` (il nome `vedit` era occupato; il modulo Python
resta `vedit`). Niente clone, niente compilazione:

```bash
claude mcp add vedit -- uvx vedit-mcp
```

L'interfaccia web viaggia già compilata dentro il pacchetto. ffmpeg no — è un programma, non
un pacchetto Python: se manca, `vedit install-ffmpeg` (strumento MCP `install_ffmpeg`) scarica
ffmpeg *e* ffprobe in `~/.vedit/bin` senza toccare il sistema.

Il resto di questo file serve a chi la repo la deve **modificare**.

---

## 1. Installazione: un comando

```bash
python scripts/setup.py
```

Fa tutto: dipendenze Python (`pip install -e ".[dev,chat]"`), interfaccia web compilata
(`npm ci && npm run build`), server MCP registrato, `vedit doctor`, test veloci.
Rilanciarlo è sicuro: i passi già a posto vengono saltati.

Opzioni utili:

| Opzione | Quando |
|---|---|
| `--venv` | tenere le dipendenze in `.venv` invece che nell'interprete corrente |
| `--install-ffmpeg` | provare a installare ffmpeg con winget / brew / apt |
| `--no-frontend` | serve solo CLI o MCP, niente interfaccia web |
| `--no-test` | installazione rapida, verifica dopo |
| `--rebuild` | ricompilare la UI dopo aver toccato `frontend/src` |
| `--reinstall` | forzare `pip install` (di norma saltato se le dipendenze ci sono) |
| `--json` | esito leggibile da programma: un oggetto JSON e basta |

**Con `--json` l'unico output è un JSON** con `result` (`ok` / `warn` / `fail`) e la lista dei
passi con `status`, `detail`, `hint`. Se sei un agente, usa questa forma e leggi `hint` prima
di inventarti una diagnosi.

### Cosa può ancora fallire, e cosa fare

| Sintomo | Rimedio |
|---|---|
| `ffmpeg non trovato` | `vedit install-ffmpeg` (scarica ffmpeg e ffprobe in `~/.vedit/bin`, nessun permesso di amministratore), oppure `python scripts/setup.py --install-ffmpeg` che usa winget / brew / apt, oppure indica i binari con `VEDIT_FFMPEG` / `VEDIT_FFPROBE`. Senza ffmpeg non si renderizza niente: è l'unica dipendenza davvero obbligatoria. |
| `externally-managed-environment` | gestito da solo: lo script crea `.venv` e ci reinstalla dentro. |
| `eseguibile in uso` (Windows) | l'interfaccia o il server MCP sono avviati e tengono `vedit-mcp.exe`. Chiudili e rilancia. |
| `npm non trovato` | Node.js 18+ manca: CLI e MCP funzionano lo stesso, resta fuori solo l'interfaccia web. |
| extra `chat` non installabile | l'assistente in chat resta spento, tutto il resto è identico. |

L'assistente in chat dentro la UI vuole anche `ANTHROPIC_API_KEY` nell'ambiente. Senza chiave
la scheda *assistente* spiega perché è spenta; nessun'altra funzione ne risente.

---

## 2. Verificare che funzioni davvero

```bash
vedit doctor                             # ffmpeg, encoder GPU, filtri
pytest -m "not slow"                     # logica, senza ffmpeg (~15s)
pytest                                   # tutto, render reali inclusi (~2min)
cd frontend && npm test                  # funzioni pure UI + montaggio in jsdom
```

Prova end-to-end in tre comandi, utile come verifica dopo una modifica:

```bash
vedit new /tmp/p.json --preset 1080p
vedit import /tmp/p.json un_video.mp4 && vedit info /tmp/p.json   # stampa gli id dei media
vedit add /tmp/p.json <id_media> --duration 3 && vedit render /tmp/p.json /tmp/out.mp4
```

---

## 3. Come è fatto (quel tanto che serve per non sbagliare)

Il progetto è **un documento JSON**. Il render è una funzione pura di quel documento,
compilata in un unico `filter_complex` di ffmpeg. Stesso progetto, stesso file in uscita.

```
backend/vedit/
  model.py       documento di progetto (dataclass <-> JSON)
  store.py       operazioni di editing + undo/redo + salvataggio atomico
  keyframes.py   keyframe -> espressioni ffmpeg
  effects.py     registro effetti: parametri, validazione, filtri
  presets.py     look, catene audio, transizioni gia' tarate
  graph.py       timeline -> filter_complex
  render.py      esecuzione ffmpeg, progresso, analisi (loudness, stabilizzazione)
  proxy.py       proxy, forme d'onda, miniature
  chat.py        assistente: i suoi strumenti sono i metodi di Store
  mcp_server.py  strumenti MCP
  api.py         API REST/WebSocket per la UI
  cli.py         riga di comando
frontend/src/    interfaccia web (React + Vite)
tests/           test, inclusi render reali di ogni effetto
```

**Regola che tiene in piedi tutto: ogni modifica al progetto passa da `Store`.** UI, assistente
e agente MCP chiamano gli stessi metodi. Se aggiungi un'operazione, mettila in `store.py` e poi
esponila dove serve — mai scrivere dentro il documento da `api.py`, `mcp_server.py` o `cli.py`.

Conseguenze pratiche quando modifichi qualcosa:

- **nuovo effetto** → `effects.py` (registro con parametri e validazione); il test parametrico
  in `tests/test_effects.py` lo renderizza davvero, quindi un filtro sbagliato si vede subito;
- **nuovo strumento MCP** → metodo in `store.py`, wrapper in `mcp_server.py`, test in
  `tests/test_mcp.py`;
- **cambio alla UI** → `npm run build` (o `python scripts/setup.py --rebuild`), altrimenti il
  server continua a servire il `dist` vecchio;
- **cambio al grafo** → `pytest -m slow` esegue i render reali: è lì che si scoprono le
  regressioni di composizione.

Le scelte tecniche meno ovvie (ordine di disegno, `tpad` invece dei PTS, transizioni fatte con
maschere alpha, filtergraph su file per il limite di 32k di Windows) sono spiegate nel README,
sezione *Come è fatto*: leggila prima di toccare `graph.py`.

---

## 4. Guidare l'editor da agente (MCP)

`.mcp.json` è già nella repo e `scripts/setup.py` lo allinea all'interprete che ha installato
davvero il pacchetto. Claude Code lo propone all'apertura della cartella; per registrarlo
altrove:

```bash
claude mcp add vedit -- vedit-mcp
```

Configurazione equivalente per gli altri client (Cursor `.cursor/mcp.json`, Codex, VS Code):

```json
{ "mcpServers": { "vedit": { "command": "vedit-mcp", "args": [] } } }
```

Se hai installato con `--venv`, al posto di `vedit-mcp` va il percorso assoluto
(`.venv/bin/vedit-mcp`, su Windows `.venv\Scripts\vedit-mcp.exe`) — è esattamente quello che
`scripts/setup.py` scrive in `.mcp.json`.

Flusso tipico degli strumenti:

```
project_create -> import_media -> add_clip / add_clips / add_text -> modifiche (split,
set_speed, add_effect, set_transform) -> preview_frame per guardare il fotogramma -> render_video
```

`preview_frame` restituisce **l'immagine vera**: guardala invece di dare per scontato il
risultato. I tempi sono in secondi. Ogni parametro animabile accetta anche un blocco keyframe
`{"kf": [{"t": 0, "v": 0}, {"t": 2, "v": 1, "ease": "ease_in_out"}]}` con `t` relativo
all'inizio della clip. `project_info` dà lo stato della timeline con gli id.

### Montare tanti tagli

Un montaggio serrato è fatto di decine o centinaia di tagli: **usa `add_clips`**, che li mette
tutti in una chiamata sola. Una chiamata per taglio è lenta, riempie la cronologia di undo per
quello che è un gesto solo, e se qualcosa si rompe a metà lascia mezza timeline costruita.
`add_clips` è atomico: o entrano tutti o non entra nessuno. `append_sequence` serve solo per
accodare media *interi*, senza punto d'attacco.

```json
[{"media": "m1b1a", "start": 0.0,   "in": 122.5, "duration": 1.5},
 {"media": "m9155", "start": 1.5,   "in": 98.5,  "duration": 0.75}]
```

### Montare a tempo di musica

`music_beats` dà BPM, durata di battito e battuta, scostamento del primo battito e il profilo
di energia per blocchi di 4 secondi — cioè dove stanno intro, stacco e ritornello. Con
`every=1|4|8` restituisce anche `griglia`, gli istanti veri su cui far cadere gli stacchi.
**Non stimare il tempo a occhio:** un errore dell'1% su novanta secondi è quasi una battuta di
deriva, e gli stacchi finiscono progressivamente fuori tempo.

### Scegliere il materiale

`plan_edit` spezza le riprese più lunghe di 12 secondi nei loro tratti e le valuta a tratti, non
a file: da tre minuti di ripresa continua escono decine di candidati con un punto d'attacco
vero. Leggi il piano prima di applicarlo (`apply=True` costruisce davvero la timeline).

Per guardare il girato prima di montarlo: `inspect_footage` vuole il **file sorgente** in
`path`, oppure `media=` / `clip=`; il progetto va sempre in `project=`. `preview_grid` mostra
tutto il montaggio insieme ed è il modo più rapido per accorgersi che un punto d'attacco è
caduto sull'inquadratura sbagliata.

L'ordine degli effetti conta e si cambia con `move_effect`: denoise prima di sharpen pulisce e
poi incide, l'ordine opposto incide anche il rumore.

### Come montare (non solo come chiamare gli strumenti)

Il server MCP dichiara le regole di montaggio nelle proprie istruzioni
(`mcp_server.ISTRUZIONI`), così arrivano a qualunque client. Sono lì perché sono i difetti
veri dei video che escono da qui, non limiti degli strumenti — sono scelte che non vengono
fatte:

1. **la musica deve muoversi** — volume fisso per tutta la durata è la prima cosa che rende un
   video piatto; automatizza il guadagno con i keyframe e scegli la sezione con `music_beats`;
2. **non tutti stacchi secchi** — il taglio secco è il default, non l'unica scelta; ogni
   transizione però deve avere un motivo;
3. **mai la stessa inquadratura due volte** — se il materiale non basta, accorcia il video;
4. **dopo dieci secondi serve informazione nuova** — tagliare più veloce sulle stesse immagini
   non salva niente;
5. **cinematografico è una scelta, non un filtro** — un momento forte tenuto tre secondi vale
   più di dieci da mezzo.

Se cambi quelle istruzioni, `tests/test_mcp.py` verifica che le regole restino: sono la parte
che l'agente legge sempre.

### Far vedere il montaggio (open_ui)

`open_ui` avvia l'interfaccia web **dentro il processo del server MCP** e restituisce
l'indirizzo. Non è una seconda istanza: `api.attach()` fa lavorare la UI sullo *stesso* oggetto
`Store` dell'agente, e `Store.on_change` fa aggiornare il browser a ogni modifica. Un solo
scrittore, nessun file conteso. `close_ui` la chiude.

**Un progetto alla volta per file.** Vale ancora se apri l'editor in un *altro* processo
(`vedit ui` da terminale mentre l'agente monta): lì sono due Store sullo stesso `.json` e
l'ultimo che salva vince, non c'è un lock. Con `open_ui` il problema non si pone.

---

## 5. Convenzioni della repo

- Codice, commenti e messaggi all'utente **in italiano**, come il resto del progetto.
- Niente dipendenze nuove senza motivo: il core sta su ffmpeg e libreria standard, l'unico
  extra facoltativo è `anthropic` per l'assistente.
- Ogni comportamento nuovo arriva con un test; i render reali stanno dietro il marker `slow`.
- Prima di dire che una modifica funziona: `pytest -m "not slow"` più il pezzo di `slow` che la
  tocca. Se hai cambiato la UI, anche `cd frontend && npm test`.
