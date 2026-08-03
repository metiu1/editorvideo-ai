# vedit

Editor video non lineare con **tre modi di guidarlo sullo stesso motore**: un'interfaccia
web per montare a mano, un assistente in chat dentro l'editor, e un server MCP per farci
lavorare un agente da fuori.

Il progetto è un documento JSON. Il render è una funzione pura di quel documento, compilata
in un unico `filter_complex` di ffmpeg: niente stato nascosto, lo stesso progetto produce
sempre lo stesso file. Ed è il motivo per cui i tre modi non possono divergere — passano
tutti dalle stesse operazioni.

---

## Indice

- [Requisiti](#requisiti)
- [Installazione](#installazione)
- [Avvio](#avvio)
- [L'interfaccia, pannello per pannello](#linterfaccia-pannello-per-pannello)
  - [Media](#1-media-pannello-sinistro-scheda-media)
  - [Libreria](#2-libreria-pannello-sinistro-scheda-libreria)
  - [Monitor e anteprima](#3-monitor-e-anteprima-centro)
  - [Timeline e tracce](#4-timeline-e-tracce-in-basso)
  - [Proprietà](#5-proprietà-pannello-destro-scheda-proprietà)
  - [Assistente](#6-assistente-pannello-destro-scheda-assistente)
  - [Esportare](#7-esportare)
- [Scorciatoie da tastiera](#scorciatoie-da-tastiera)
- [Riga di comando](#riga-di-comando)
- [Uso da agente (MCP)](#uso-da-agente-mcp)
- [Cosa sa fare](#cosa-sa-fare)
- [Keyframe](#keyframe)
- [Come è fatto](#come-è-fatto)
- [Test](#test)
- [Limiti noti](#limiti-noti)

---

## Requisiti

| | |
|---|---|
| Python | 3.10 o più recente |
| ffmpeg e ffprobe | nel `PATH`, oppure indicati con `VEDIT_FFMPEG` / `VEDIT_FFPROBE` |
| Node.js | 18+, serve **solo** per compilare l'interfaccia la prima volta |
| GPU | facoltativa. NVIDIA/Intel/AMD vengono rilevate e usate da sole per il render |

Verifica ffmpeg con `ffmpeg -version`. Se manca: [ffmpeg.org/download](https://ffmpeg.org/download.html)
(su Windows la build "essentials" di gyan.dev va benissimo).

---

## Installazione

```bash
git clone https://github.com/metiu1/editorvideo-ai.git
cd editorvideo-ai

pip install -e .                 # installa i comandi vedit e vedit-mcp
vedit doctor                     # controlla ffmpeg, encoder GPU, filtri disponibili

cd frontend
npm install
npm run build                    # compila l'interfaccia in frontend/dist
cd ..
```

`npm run build` va rifatto solo se modifichi il codice dell'interfaccia. Se ti dimentichi,
il server te lo dice invece di mostrare una pagina bianca.

**Assistente in chat (facoltativo).** Serve una credenziale Anthropic:

```bash
pip install -e ".[chat]"                     # aggiunge il pacchetto anthropic
export ANTHROPIC_API_KEY=sk-ant-...          # Windows: setx ANTHROPIC_API_KEY sk-ant-...
```

Senza chiave tutto il resto funziona identico: la scheda *assistente* mostra il motivo
invece di fingere di andare.

---

## Avvio

```bash
vedit ui                                     # apre il browser su http://127.0.0.1:8760
vedit ui --project miofilm.json              # aprendo già un progetto
vedit ui --port 9000 --no-browser            # su un'altra porta, senza aprire il browser
```

Il primo progetto lo crei con **nuovo** nella barra in alto: scegli il file `.json` e il
formato (`1080p`, `4k`, `vertical` per reel e short, `square`, …). Il `.json` è il progetto:
i video restano dove sono, non vengono copiati.

Un progetto nuovo parte con **una traccia video e una audio**. Ne aggiungi quante ne vuoi,
quando ti servono (vedi [Timeline e tracce](#4-timeline-e-tracce-in-basso)).

---

## L'interfaccia, pannello per pannello

```
┌──────────────────────────────────────────────────────────────────────┐
│  barra: nuovo · apri · salva · ↶↷ · +video +audio +testo · esporta   │
├───────────────┬──────────────────────────────────┬───────────────────┤
│ media         │  programma / sorgente            │ proprietà         │
│ libreria      │  ┌────────────────────────────┐  │ assistente        │
│               │  │      anteprima             │  │                   │
│  (schede)     │  └────────────────────────────┘  │   (schede)        │
│               │  ▶ ⏮  0:01.2/0:13.0  zoom tracce │                   │
│               ├──────────────────────────────────┤                   │
│               │  timeline: V3 V2 V1 A1 …         │                   │
└───────────────┴──────────────────────────────────┴───────────────────┘
```

Le zone si ridimensionano trascinando i divisori tra loro; le misure restano salvate.

### 1. Media (pannello sinistro, scheda *media*)

- **`+`** importa file *lasciandoli dove sono*.
- **Trascinare file dal desktop** dentro la finestra li **copia** in `media/` accanto al
  progetto (il browser non passa il percorso di origine). Per file pesanti usa `+`.
- **`📁+`** crea una cartella: è solo un'etichetta sul media, non sposta niente su disco.
- **Clic** su un media lo apre nel monitor *sorgente*; **doppio clic** lo accoda in timeline;
  **trascina** su una traccia per metterlo dove vuoi.

### 2. Libreria (pannello sinistro, scheda *libreria*)

Look, catene audio e transizioni già tarate, con un nome invece di venti parametri.

| Scheda | Contenuto |
|---|---|
| **look** | Colore (cinema teal & orange, bianco e nero, caldo tramonto, sbiadito pellicola…), Stilizzati (VHS, sogno, censura), Ritocco (nitido, pulisci ripresa, vignettatura, stabilizza) |
| **audio** | Voce (voce pulita, voce radiofonica), Effetti (telefono, sala grande, eco), Musica (musica sotto la voce, volume costante) |
| **transizioni** | dissolvenza, iris, tendina e scorrimento nelle quattro direzioni |

- **Clic** applica alla clip selezionata. Un look video senza clip selezionata va sul
  **master**, cioè su tutto il video. In fondo al pannello c'è sempre scritto su cosa finirà.
- **Trascina** un preset **sopra una clip** in timeline per applicarlo a quella.
- Un preset è solo una catena di effetti: si annulla con **un solo** Ctrl+Z e resta tutto
  regolabile dal pannello proprietà.

### 3. Monitor e anteprima (centro)

Due schede: **programma** (la timeline) e **sorgente** (un media da solo).

- Da fermo l'anteprima è il fotogramma **renderizzato da ffmpeg**, quindi identico al
  risultato finale, effetti compresi.
- **▶** riproduce segmenti da 12s preparando il successivo in sottofondo. Il primo segmento
  va atteso; premi **proxy** nella barra in alto per rendere tutto molto più rapido.
- Con una clip selezionata compare il **riquadro di trasformazione**: trascina l'immagine per
  spostarla, gli angoli per ridimensionarla.
- Nel monitor *sorgente*: `[` e `]` segnano attacco e stacco, poi **inserisci** mette solo
  quel pezzo alla testina — o lo trascini sulla traccia che vuoi.

### 4. Timeline e tracce (in basso)

**Le tracce non hanno un numero fisso.** Un progetto nuovo ne ha una video e una audio; le
altre si aggiungono con **`+ video`** / **`+ audio`** nella riga in fondo alla colonna dei
nomi (accanto c'è il conteggio: `3 video · 1 audio`). Gli stessi pulsanti sono anche nella
barra in alto.

Ogni traccia ha la sua testata:

| Comando | Cosa fa |
|---|---|
| **nome** | doppio clic per rinominarla (`riprese`, `titoli`, `musica`…) |
| **▲ ▼** | sposta la traccia. Per il video l'ordine **è** la sovrapposizione: più in alto = disegnata sopra |
| **👁 / 🔊** | nasconde il video / silenzia l'audio |
| **S** | *solo*: isola la traccia, le altre dello stesso tipo escono dal render |
| **🔒** | blocca: protegge le clip da spostamenti, tagli, effetti ed eliminazioni. È anche l'unico modo di sbloccarla |
| **✕** | elimina la traccia (chiede conferma se contiene clip) |
| **cursore** | volume della traccia |

Una traccia esclusa dal render si vede subito: corsia sbiadita e nome barrato. Una bloccata
ha il tratteggio diagonale.

Sulle clip:

- **trascina** per spostarle, anche **da una traccia all'altra**;
- **trascina i bordi** per tagliarle;
- aggancio automatico ai bordi delle altre clip e alla testina;
- le clip video mostrano i fotogrammi, quelle audio la forma d'onda.

Sotto la barra di trasporto ci sono due cursori: **zoom** (scala dei tempi) e **tracce**
(altezza). Abbassa l'altezza per tenerne una ventina sott'occhio: sotto una certa soglia
sparisce solo il cursore del volume, i pulsanti restano tutti.

> **Le tracce video servono a sovrapporre.** Un titolo sulla stessa traccia di una ripresa
> ci sta, ma per un PiP, un logo o due riprese sovrapposte a piacere serve una traccia in più.

### 5. Proprietà (pannello destro, scheda *proprietà*)

Con una clip selezionata: nome, inizio, durata, attacco, inquadratura, velocità e reverse,
dissolvenze, transizione in uscita, posizione/scala/rotazione/opacità, audio (volume in dB,
pan, dissolvenze), effetti.

Il pulsante **◆** accanto a un parametro lo rende **animato**: compare l'editor dei keyframe,
con i tempi relativi all'inizio della clip.

Senza selezione mostra il progetto: risoluzione, fps, sfondo, normalizzazione EBU R128 del
mix ed effetti sul master.

### 6. Assistente (pannello destro, scheda *assistente*)

Chiedi una modifica in italiano e viene fatta sul progetto:

> «togli i primi 2 secondi della prima clip»
> «metti una dissolvenza tra le due riprese»
> «rendi il video più cinematografico»
> «sposta la musica su una traccia sua e abbassala di 6 dB»

Gli strumenti che usa **sono le stesse operazioni dei pulsanti**: quello che fa compare in
timeline e lo annulli con Ctrl+Z, esattamente come una tua modifica. Sotto ogni risposta
vedi la lista di cosa ha toccato. **azzera** ricomincia la conversazione.

Richiede `ANTHROPIC_API_KEY` (vedi [Installazione](#installazione)).

### 7. Esportare

**esporta** apre la finestra di render: file di destinazione, qualità
(`bozza` / `media` / `alta` / `massima`), codec (H.264, HEVC, AV1, VP9) ed eventualmente solo
una porzione della timeline. L'estensione decide il contenitore: `.mp4` `.mov` `.mkv`
`.webm` `.gif` `.mp3` `.wav`. La barra mostra l'avanzamento reale di ffmpeg.

Il render finale usa **sempre gli originali**, mai i proxy.

---

## Scorciatoie da tastiera

| Tasto | Azione |
|---|---|
| `spazio` | play / pausa |
| `←` `→` | un fotogramma (con `shift`: un secondo) |
| `Home` / `Fine` | inizio / fine |
| `S` | taglia alla testina |
| `Canc` | elimina la clip (con `shift`: chiude il buco) |
| `Ctrl+Z` / `Ctrl+Y` | annulla / ripeti |
| `+` `-` | zoom della timeline |

---

## Riga di comando

Tutto quello che fa l'interfaccia si fa anche da terminale, sullo stesso file di progetto.

```bash
vedit new progetto.json --preset 1080p
vedit import progetto.json riprese/*.mp4 musica.mp3
vedit info progetto.json                 # media e timeline con gli id
vedit add progetto.json m1a2b3c4 --duration 8
vedit proxy progetto.json                # proxy 540p: anteprime molto più rapide
vedit frame progetto.json 12.5 controllo.jpg
vedit normalize progetto.json --lufs -14
vedit render progetto.json finale.mp4 --quality high
vedit effects video                      # catalogo effetti e parametri
vedit doctor                             # ffmpeg, encoder, filtri
vedit ui                                 # interfaccia web
```

Preset di formato: `1080p`, `1080p60`, `4k`, `720p`, `vertical` (9:16), `vertical60`, `square`.

---

## Uso da agente (MCP)

Il file `.mcp.json` è già pronto: aprendo Claude Code in questa cartella il server `vedit`
viene proposto al primo avvio (va approvato una volta). Altrove:

```bash
claude mcp add vedit -- vedit-mcp
```

42 strumenti: creazione progetto, import, taglio/split/trim, tracce (aggiungere,
riordinare, solo, blocco), velocità e reverse, transform con keyframe, effetti video e audio,
dissolvenze incrociate, normalizzazione EBU R128, render, e `preview_frame` che **restituisce
l'immagine vera** del fotogramma — così l'agente vede quello che ha montato invece di
indovinarlo.

> **Un progetto alla volta per file.** Interfaccia e server MCP salvano da soli dopo ogni
> modifica: se tieni lo stesso `.json` aperto in tutti e due contemporaneamente, l'ultimo che
> salva vince. Lavora su uno per volta.

---

## Cosa sa fare

**Montaggio** — taglio, split, trim, spostamento anche tra tracce, ripple delete, chiusura
buchi, tracce video e audio in numero libero con ordine, solo e blocco, cartelle nel bin,
undo/redo.

**Transizioni** — dissolvenza, tendina nelle quattro direzioni, scorrimento nelle quattro
direzioni, iris. La clip successiva viene accostata e sovrapposta in automatico; l'audio
incrocia sempre in dissolvenza.

**Velocità** — da 0.01x a 100x con audio in tempo (`atempo` a catena), reverse, motion blur o
interpolazione di frame per lo slow motion.

**Colore** — luminosità, contrasto, saturazione, gamma (animabili), bilanciamento
ombre/mezzitoni/alteluci, temperatura, curve, LUT `.cube`.

**Composizione** — posizione, scala, rotazione, opacità per clip, tutte animabili con keyframe
ed easing; PiP, overlay grafici, testi con box/bordo/ombra, chroma key, ritaglio, specchio,
pixelate, vignettatura, grana, glow, stabilizzazione.

**Audio** — guadagno in dB (animabile), pan, dissolvenze, equalizzatore, compressore, limiter,
riduzione rumore, gate, riverbero, eco, pitch shift, normalizzazione dinamica e
normalizzazione EBU R128 a due passaggi sul mix.

---

## Keyframe

Ogni parametro animabile accetta, al posto di un numero, un blocco keyframe:

```json
{"kf": [{"t": 0, "v": 1.0, "ease": "ease_in_out"}, {"t": 3, "v": 1.4}]}
```

`t` è il tempo **relativo all'inizio della clip**. Easing: `linear`, `hold`, `ease_in`,
`ease_out`, `ease_in_out` e le varianti `_cubic`.

I keyframe diventano espressioni ffmpeg valutate frame per frame: l'animazione non costa un
passaggio di render in più.

---

## Come è fatto

```
backend/vedit/
  model.py       documento di progetto (dataclass <-> JSON)
  keyframes.py   keyframe -> espressioni ffmpeg
  effects.py     registro effetti: parametri, validazione, filtri
  presets.py     look, catene audio e transizioni già tarate
  graph.py       timeline -> filter_complex
  render.py      esecuzione, progresso, analisi (loudness, stabilizzazione)
  proxy.py       proxy, forme d'onda, miniature
  store.py       operazioni di editing + undo/redo + salvataggio
  chat.py        assistente: gli strumenti sono le operazioni di store
  mcp_server.py  strumenti MCP
  api.py         API REST/WebSocket per la UI
  cli.py         riga di comando
frontend/        interfaccia web (React + Vite)
tests/           test, inclusi render reali di ogni effetto
```

**Un solo punto di verità.** Interfaccia, assistente e agente MCP chiamano tutti i metodi di
`Store`. Non esiste una strada privilegiata per modificare il progetto, quindi non esiste il
caso "funziona da qui ma non da lì".

Note tecniche che spiegano le scelte meno ovvie:

- **Composizione**: canvas + un `overlay` per clip. Regge multi-traccia, PiP e dissolvenze
  senza casi particolari.
- **Posizionamento**: `tpad` con frame trasparenti invece di spostare i PTS, così `overlay`
  non resta in attesa di frame.
- **Ordine di disegno**: le tracce video si sovrappongono nell'ordine della lista. Dentro una
  traccia, la clip che inizia prima sta sopra (così la sua transizione in uscita scopre quella
  dopo); titoli e colori pieni fanno eccezione e stanno sempre sopra i media.
- **Anteprima**: `slice_project` ritaglia la porzione richiesta, quindi rendere il secondo 300
  non costa più che rendere il secondo 3. Le clip tagliate conservano il proprio tempo
  d'origine, così una dissolvenza inquadrata a metà mostra il fotogramma giusto — c'è un test
  che confronta anteprima e render finale.
- **Transizioni**: sfruttano l'ordine di disegno. Tendine e iris cancellano pixel della clip in
  uscita con una maschera `geq` sull'alpha; lo scorrimento aggiunge un termine alle espressioni
  `x`/`y` dell'overlay. Nessun secondo ramo del grafo, nessun costo di composizione in più.
- **Strisce di fotogrammi**: una sola immagine per media (`tile`), posizionata via CSS in base
  ad attacco, velocità e zoom. Zoomare la timeline non genera nessuna richiesta.
- **Cache di anteprima**: ogni fotogramma e ogni segmento vengono scritti su un file
  temporaneo e spostati a destinazione solo a lavoro finito. Senza, il player riceverebbe un
  mp4 ancora senza atomo `moov` e la riproduzione non partirebbe.
- **Salvataggio**: stessa idea, `os.replace` atomico. Un'interruzione a metà non può lasciare
  un progetto troncato.
- **Filtergraph su file** (`-filter_complex_script`): le timeline lunghe superano il limite di
  32k caratteri della riga di comando di Windows.

---

## Test

```bash
pytest                  # tutto, render reali inclusi (~50s)
pytest -m "not slow"    # solo logica, senza ffmpeg

cd frontend
node test-util.mjs                       # funzioni pure della UI
npm run build && node smoke.mjs          # monta la UI compilata in jsdom
```

78 test Python: keyframe, operazioni di editing, compilazione del grafo, un render reale per
ognuno dei 28 effetti e delle 10 transizioni, corrispondenza tra anteprima e render finale,
strumenti MCP, API della UI, riga di comando.

---

## Limiti noti

- L'opacità animata e le tendine usano `geq` (valutazione per pixel): funzionano ma rallentano
  il render. Dissolvenze e scorrimenti non hanno questo costo.
- La scala animata passa da `zoompan`: sotto 0.25x il valore viene limitato.
- La riproduzione in anteprima è a segmenti: il primo è da attendere, i successivi vengono
  preparati mentre guardi.
- I file trascinati dal desktop vengono copiati (il browser non passa il percorso di origine):
  per file grandi conviene il pulsante di import.
- Il riquadro di trasformazione non modifica i parametri animati: in quel caso si agisce sui
  keyframe.
- Se due processi tengono aperto lo stesso `.json` (per esempio interfaccia e server MCP), il
  salvataggio automatico dell'uno può sovrascrivere il lavoro dell'altro. Non c'è ancora un
  lock sul file di progetto.
