"""Montaggio ragionato: quale clip, in che ordine, per quanto tempo.

Il modulo non "capisce" il senso di un video: misura il girato (:mod:`analyze`)
e applica regole di montaggio esplicite. Ogni scelta esce con la sua
motivazione, cosi' si puo' discutere invece di subirla.

Le regole implementate sono quattro, e sono quelle che tengono sveglio chi
guarda:

1. **Niente materiale morto** - nero, congelato, fuori fuoco, muto: fuori.
2. **Niente doppioni** - due riprese quasi identiche annoiano; resta la migliore.
3. **Arco** - si apre forte, si sale, il picco sta verso il 75%, si chiude calmi.
4. **Alternanza** - due clip consecutive troppo simili per ritmo o luce vengono
   separate: la monotonia e' il vero nemico dell'attenzione.

Lo stile decide i numeri (durata dei tagli, quanta aria lasciare, se aprire con
l'inquadratura piu' forte); le regole restano le stesse.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from . import analyze
from .model import AUDIO_EXTS, VIDEO_EXTS


@dataclass
class Style:
    """I numeri di uno stile di montaggio."""

    name: str
    label: str
    shot_min: float          # durata minima di un'inquadratura (s)
    shot_max: float
    hook_first: bool         # apre con l'inquadratura piu' forte
    keep_silence: float      # aria lasciata attorno al parlato (s)
    transition: str          # transizione predefinita tra le clip
    transition_dur: float
    speech_weight: float     # quanto pesa il parlato nel punteggio
    motion_weight: float
    peak_at: float = 0.75    # dove cade il picco lungo la durata totale
    desc: str = ""


STYLES: dict[str, Style] = {
    "shortform": Style(
        "shortform", "Reel / TikTok", 1.2, 3.0, True, 0.05, "cut", 0.0,
        speech_weight=1.0, motion_weight=1.4, peak_at=0.6,
        desc="Tagli rapidissimi, apre col colpo migliore, zero pause: i primi "
             "due secondi decidono se qualcuno resta.",
    ),
    "vlog": Style(
        "vlog", "Vlog", 2.5, 6.0, True, 0.15, "cut", 0.0,
        speech_weight=1.3, motion_weight=0.9,
        desc="Ritmo sostenuto ma respirabile, guidato dal parlato.",
    ),
    "documentary": Style(
        "documentary", "Documentario", 4.0, 10.0, False, 0.35, "dissolve", 0.5,
        speech_weight=1.5, motion_weight=0.6, peak_at=0.8,
        desc="Inquadrature lunghe, si lascia respirare, si apre calmi e si "
             "costruisce: l'attenzione si guadagna col contenuto.",
    ),
    "cinematic": Style(
        "cinematic", "Cinematico", 3.0, 8.0, False, 0.4, "dissolve", 0.8,
        speech_weight=0.7, motion_weight=1.2, peak_at=0.8,
        desc="Immagine sopra tutto, transizioni morbide, montaggio sul respiro.",
    ),
}


@dataclass
class Shot:
    """Una clip candidata, con le sue misure e il posto che le tocca."""

    path: str
    duration: float
    in_: float = 0.0
    out: float = 0.0
    score: float = 0.0
    energy: float = 0.0
    speech: float = 0.0
    quality: float = 0.0
    verdict: str = "keep"
    issues: list[str] = field(default_factory=list)
    fingerprint: list[float] = field(default_factory=list)
    reason: str = ""

    @property
    def used(self) -> float:
        return max(0.0, self.out - self.in_)


# --------------------------------------------------------------------------
# misure -> punteggi
# --------------------------------------------------------------------------


def fingerprint(stats: list[dict]) -> list[float]:
    """Firma compatta di una clip: come cambiano luce, contrasto e fuoco.

    Serve solo a riconoscere due riprese quasi identiche, non a descrivere il
    contenuto: e' volutamente grossolana (8 valori).
    """
    if not stats:
        return []
    out = []
    for key in ("brightness", "contrast", "focus"):
        vals = [s[key] for s in stats]
        top = max(vals) or 1.0
        out.append(sum(vals) / len(vals) / top)
        out.append((max(vals) - min(vals)) / top)
    # quanto "si muove": variazione media tra campioni consecutivi
    b = [s["brightness"] for s in stats]
    out.append(sum(abs(b[i] - b[i - 1]) for i in range(1, len(b))) / max(1, len(b) - 1))
    out.append(min(1.0, len(stats) / 100.0))
    return [round(v, 4) for v in out]


def similarity(a: list[float], b: list[float]) -> float:
    """Coseno tra due firme: 1 = praticamente la stessa ripresa."""
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    return round(num / (da * db), 4) if da and db else 0.0


def shot_from(path: str, style: Style, deep: bool = False, **kw) -> Shot:
    """Analizza un file e ne ricava punteggio, taglio suggerito e firma."""
    rep = analyze.report(path, deep=deep, **kw)
    a = analyze.analyze(path, deep=False)
    m = rep["measures"]

    quality = max(0.0, 1.0 - (m["black"] + m["freeze"] + m["blurry"]
                              + 0.5 * m["dark"] + 0.5 * m["bright"]))
    stats = a.get("stats") or []
    fp = fingerprint(stats)
    motion = fp[6] * 6 if len(fp) > 6 else 0.0          # variazione tra campioni
    cuts = m.get("cuts", 0)
    energy = min(1.0, motion + 0.08 * max(0, cuts - 1))
    speech = min(1.0, m.get("speech", 0.0) * 1.4)
    if not deep and a.get("has_audio"):
        # senza trascrizione il parlato si stima dal non-silenzio
        speech = min(1.0, (1.0 - m.get("silence", 1.0)) * 0.9)

    score = (style.speech_weight * speech + style.motion_weight * energy
             + 1.2 * quality) / (style.speech_weight + style.motion_weight + 1.2)

    return Shot(
        path=rep["path"], duration=rep["duration"],
        in_=rep["suggested_in"], out=rep["suggested_out"],
        score=round(score, 4), energy=round(energy, 4), speech=round(speech, 4),
        quality=round(quality, 4), verdict=rep["verdict"], issues=list(rep["issues"]),
        fingerprint=fp,
    )


# --------------------------------------------------------------------------
# dal file all'inquadratura: spezzare le riprese lunghe
# --------------------------------------------------------------------------

# Sotto questa durata un file e' gia' un'inquadratura sola e non si tocca.
SEGMENT_OVER = 12.0


def segment_bounds(path: str, style: Style, duration: float) -> list[tuple[float, float]]:
    """Divide una ripresa lunga nei tratti che potrebbero diventare inquadrature.

    Un file non e' un'inquadratura. Su una ripresa continua di tre minuti —
    bodycam, intervista, drone, una GoPro lasciata accesa — valutare il file
    intero da un punteggio solo per centottanta secondi che contengono di tutto,
    e qualunque scelta ne discenda e' un caso. Il montaggio si fa sui tratti.

    I confini arrivano dai cambi di inquadratura quando ci sono; dove la ripresa
    e' continua si taglia a finestre regolari, perche' e' meglio avere trenta
    candidati misurati male ai bordi che uno solo misurato bene e inutilizzabile.
    """
    target = max(style.shot_max * 2.0, 4.0)
    cuts = [t for t in analyze.scenes(path) if 0.0 <= t < duration]
    bordi = sorted(set([0.0] + cuts + [duration]))

    out: list[tuple[float, float]] = []
    for a, b in zip(bordi, bordi[1:]):
        span = b - a
        if span < style.shot_min:
            continue
        n = max(1, round(span / target))
        passo = span / n
        for i in range(n):
            s = a + i * passo
            e = min(b, s + passo)
            if e - s >= style.shot_min:
                out.append((round(s, 3), round(e, 3)))
    return out


def _window(stats: list[dict], a: float, b: float) -> list[dict]:
    return [s for s in stats if a <= s["t"] < b]


def shot_in_window(path: str, a: dict, style: Style, start: float, end: float,
                   deep: bool = False) -> Shot:
    """Misura un singolo tratto di un file gia' analizzato.

    Riusa le misure del file (campioni, silenzi, tratti morti, cambi scena) che
    sono in cache: spezzare in trenta candidati non costa trenta analisi.
    """
    dur = max(1e-6, end - start)
    stats = _window(a.get("stats") or [], start, end)
    dead = a.get("dead") or {}

    black = analyze._cover(dead.get("black"), start, end) / dur
    freeze = analyze._cover(dead.get("freeze"), start, end) / dur
    silence = analyze._cover(a.get("silences"), start, end) / dur

    dark = bright = blurry = 0.0
    if stats:
        tutti = sorted(s["focus"] for s in (a.get("stats") or []))
        med = tutti[len(tutti) // 2] if tutti else 0.0
        quota = 1.0 / len(stats)
        for s in stats:
            if s["brightness"] < analyze.DARK_LEVEL:
                dark += quota
            elif s["brightness"] > analyze.BRIGHT_LEVEL:
                bright += quota
            if med > 0 and s["focus"] < med * analyze.FOCUS_FLOOR:
                blurry += quota

    quality = max(0.0, 1.0 - (black + freeze + blurry + 0.5 * dark + 0.5 * bright))
    fp = fingerprint(stats)
    motion = fp[6] * 6 if len(fp) > 6 else 0.0
    cuts = sum(1 for t in (a.get("scenes") or []) if start < t < end)
    energy = min(1.0, motion + 0.08 * cuts)
    speech = min(1.0, (1.0 - silence) * 0.9) if a.get("has_audio") else 0.0

    score = (style.speech_weight * speech + style.motion_weight * energy
             + 1.2 * quality) / (style.speech_weight + style.motion_weight + 1.2)

    issues = []
    if black + freeze > 0.5:
        issues.append("tratto nero o congelato")
    if blurry > 0.6:
        issues.append("fuori fuoco")
    if dark > 0.6:
        issues.append("sottoesposto")
    elif bright > 0.6:
        issues.append("bruciato")
    verdict = "drop" if (black + freeze > 0.6 or blurry > 0.7 or quality < 0.35) else "keep"

    return Shot(
        path=a["path"], duration=float(a["duration"]), in_=start, out=end,
        score=round(score, 4), energy=round(energy, 4), speech=round(speech, 4),
        quality=round(quality, 4), verdict=verdict, issues=issues, fingerprint=fp,
    )


def shots_from(path: str, style: Style, deep: bool = False, **kw) -> list[Shot]:
    """Tutti i tratti utilizzabili di un file, gia' misurati.

    Un file corto resta una clip sola: e' gia' un'inquadratura. Uno lungo esce
    spezzato, ed e' li' che il montaggio diventa possibile.
    """
    rep = analyze.report(path, deep=deep, **kw)
    if rep["verdict"] == "drop" or rep["duration"] <= SEGMENT_OVER:
        return [shot_from(path, style, deep=deep, **kw)]

    a = analyze.analyze(path, deep=False)
    tratti = segment_bounds(path, style, rep["duration"])
    if not tratti:
        return [shot_from(path, style, deep=deep, **kw)]
    return [shot_in_window(path, a, style, s, e, deep) for s, e in tratti]


def select(shots: list[Shot], style: Style, target: float | None,
           per_file_max: int | None = None) -> tuple[list[Shot], list[Shot]]:
    """Da tanti candidati ai pochi che entrano davvero, senza svuotare un file.

    Con le riprese spezzate i candidati diventano centinaia: prenderli tutti
    darebbe un video lungo dieci volte il richiesto, e prendere solo i primi per
    punteggio significa pescarli tutti dalla stessa ripresa, quella girata
    meglio. Si tiene quindi il meglio con un tetto per file, e si torna
    all'ordine di partenza.
    """
    if not shots:
        return [], []
    medio = (style.shot_min + style.shot_max) / 2
    quanti = (max(1, round(target / medio)) if target
              else min(40, max(1, 3 * len({s.path for s in shots}))))
    if quanti >= len(shots):
        return list(shots), []

    files = len({s.path for s in shots})
    tetto = per_file_max or max(1, math.ceil(quanti / files * 1.6))

    posizione = {id(s): i for i, s in enumerate(shots)}
    presi: list[Shot] = []
    usati: dict[str, int] = {}
    for s in sorted(shots, key=lambda x: -x.score):
        if len(presi) >= quanti:
            break
        if usati.get(s.path, 0) >= tetto:
            continue
        usati[s.path] = usati.get(s.path, 0) + 1
        presi.append(s)

    presi.sort(key=lambda s: posizione[id(s)])
    dentro = {id(s) for s in presi}
    scartati = [s for s in shots if id(s) not in dentro]
    for s in scartati:
        s.reason = s.reason or "non entra nella durata richiesta"
    return presi, scartati


# --------------------------------------------------------------------------
# regole di montaggio
# --------------------------------------------------------------------------


def drop_duplicates(shots: list[Shot], threshold: float = 0.995) -> tuple[list[Shot], list[Shot]]:
    """Tra due riprese quasi identiche tiene quella con punteggio migliore."""
    keep: list[Shot] = []
    dropped: list[Shot] = []
    for s in sorted(shots, key=lambda x: -x.score):
        twin = next((k for k in keep if similarity(k.fingerprint, s.fingerprint) >= threshold), None)
        if twin is None:
            keep.append(s)
        else:
            s.reason = f"quasi identica a {Path(twin.path).name}"
            dropped.append(s)
    return keep, dropped


def arrange(shots: list[Shot], style: Style, keep_order: bool = False) -> list[Shot]:
    """Ordina secondo l'arco: apertura, salita, picco, chiusura.

    Il picco non sta alla fine: chi guarda deve avere il tempo di atterrare,
    altrimenti il video finisce sul massimo e sembra tagliato.

    ``keep_order=True`` conserva la sequenza cosi' com'e': se hai chiesto
    l'ordine cronologico, spostare il picco al 75% romperebbe proprio il tempo
    che volevi rispettare. L'unica eccezione e' il gancio in apertura degli
    stili che lo prevedono (``hook_first``), che e' una scelta dichiarata: si
    apre col momento migliore e poi si torna in ordine.
    """
    if keep_order and len(shots) > 2:
        ordered = list(shots)
        peak = max(ordered, key=lambda s: s.score)
        if style.hook_first:
            gancio = ordered.pop(ordered.index(peak))
            ordered.insert(0, gancio)
        for i, s in enumerate(ordered):
            s.reason = s.reason or (
                "apertura: il momento piu' forte" if style.hook_first and i == 0
                else "picco" if s is peak
                else "chiusura, si atterra" if i == len(ordered) - 1
                else "in sequenza"
            )
        return ordered

    if len(shots) <= 2:
        # con due clip l'arco non esiste: si mette davanti quella piu' forte se
        # lo stile apre col colpo migliore, e si dichiara comunque il perche'
        out = (sorted(shots, key=lambda s: -s.score)
               if style.hook_first and not keep_order else list(shots))
        for i, s in enumerate(out):
            s.reason = s.reason or ("apertura" if i == 0 else "chiusura")
        return out

    per_punteggio = sorted(shots, key=lambda s: s.score)
    opener = None
    if style.hook_first:
        opener = per_punteggio.pop()            # il colpo migliore in apertura
    peak = per_punteggio.pop()                  # il picco vero
    closer = per_punteggio.pop(0) if len(per_punteggio) > 1 else None  # chiusura calma

    rest = per_punteggio

    n = len(rest)
    idx = max(0, min(n, round(n * style.peak_at)))
    ordered = rest[:idx] + [peak] + rest[idx:]
    if opener is not None:
        ordered.insert(0, opener)
    if closer is not None:
        ordered.append(closer)

    for i, s in enumerate(ordered):
        s.reason = s.reason or (
            "apertura: il momento piu' forte" if opener is not None and i == 0
            else "picco" if s is peak
            else "chiusura, si atterra" if s is closer
            else "salita"
        )
    return ordered


def avoid_monotony(shots: list[Shot], threshold: float = 0.99) -> list[Shot]:
    """Separa le clip consecutive troppo simili: e' li' che nasce la noia.

    L'ultima posizione non si tocca: :func:`arrange` ci ha messo la chiusura, e
    scambiarla rimetterebbe il picco in fondo, che e' esattamente il difetto che
    l'arco vuole evitare.
    """
    out = list(shots)
    fine = len(out) - 1 if len(out) > 2 else len(out)   # slot di chiusura protetto
    for i in range(1, fine):
        if similarity(out[i - 1].fingerprint, out[i].fingerprint) < threshold:
            continue
        for j in range(i + 1, fine):
            if similarity(out[i - 1].fingerprint, out[j].fingerprint) < threshold:
                out[i], out[j] = out[j], out[i]
                out[i].reason += " (spostata: troppo simile alla precedente)"
                break
    return out


def pace(shots: list[Shot], style: Style, target: float | None = None) -> list[Shot]:
    """Assegna a ogni clip la sua durata: piu' lunga se ha piu' da dire.

    Con ``target`` la somma viene riportata alla durata richiesta, ma senza mai
    scendere sotto shot_min: meglio togliere una clip che averne venti da mezzo
    secondo che nessuno riesce a seguire.
    """
    for s in shots:
        span = style.shot_min + (style.shot_max - style.shot_min) * s.score
        span = min(span, s.used or s.duration)
        s.out = round(s.in_ + max(style.shot_min * 0.5, span), 3)
        s.out = round(min(s.out, s.duration), 3)

    if not target or not shots:
        return shots
    total = sum(s.used for s in shots)
    if total <= 0:
        return shots
    k = target / total
    for s in shots:
        span = max(style.shot_min * 0.6, min(s.used * k, s.duration - s.in_))
        s.out = round(s.in_ + span, 3)
    return shots


# --------------------------------------------------------------------------
# piano
# --------------------------------------------------------------------------


ORDERS = ("score", "chrono", "name")


def collect(folder: str, order: str = "name") -> list[str]:
    """File montabili dentro una cartella.

    ``order='chrono'`` usa la data di ripresa letta dai tag (con la data del
    file come ripiego), non il nome: ``IMG_9987`` puo' essere di ieri e
    ``IMG_0001`` di stamattina.
    """
    p = Path(folder)
    if not p.is_dir():
        raise NotADirectoryError(f"non e' una cartella: {folder}")
    exts = VIDEO_EXTS | AUDIO_EXTS
    files = [str(f.resolve()) for f in p.iterdir()
             if f.is_file() and f.suffix.lower() in exts]
    if order == "chrono":
        from . import probe
        return sorted(files, key=probe.sort_key)
    return sorted(files)


def plan(source: str | list[str], style: str = "vlog", target_duration: float | None = None,
         deep: bool = False, dedupe: bool = True, order: str = "score",
         segment: bool = True, **kw) -> dict:
    """Dal materiale grezzo alla scaletta: cosa entra, in che ordine, per quanto.

    ``source`` e' una cartella o una lista di file. Ritorna un piano leggibile,
    non una timeline: si guarda, si corregge, poi lo si applica con
    :func:`apply_plan`.

    ``order``:

    - ``score`` - il corpo del montaggio segue il punteggio (piu' forte = piu'
      avanti nella salita). E' il default;
    - ``chrono`` - segue la data di ripresa letta dai file: per un racconto che
      deve rispettare il tempo reale;
    - ``name`` - segue l'ordine dei nomi: per materiale gia' numerato da te.

    Anche con ``chrono``/``name`` l'apertura, il picco e la chiusura restano
    scelti per punteggio: sono decisioni di ritmo, non di cronologia.

    ``segment=True`` (predefinito) spezza le riprese piu' lunghe di
    :data:`SEGMENT_OVER` secondi nei loro tratti prima di valutarle: senza,
    un'unica ripresa da tre minuti vale un punteggio solo e il piano che ne esce
    e' arbitrario. Con ``segment=False`` si torna a un'inquadratura per file.
    """
    st = STYLES.get(style)
    if st is None:
        raise ValueError(f"stile sconosciuto: {style!r}; scegli tra {sorted(STYLES)}")
    if order not in ORDERS:
        raise ValueError(f"order sconosciuto: {order!r}; scegli tra {list(ORDERS)}")

    paths = (collect(source, order) if isinstance(source, str)
             else list(source))
    if order == "chrono" and not isinstance(source, str):
        from . import probe
        paths = sorted(paths, key=probe.sort_key)
    if not paths:
        raise ValueError("nessun file da montare")

    if segment:
        shots = [s for p in paths for s in shots_from(p, st, deep=deep, **kw)]
    else:
        shots = [shot_from(p, st, deep=deep, **kw) for p in paths]
    spezzati = len(shots) > len(paths)

    posizione = {id(s): i for i, s in enumerate(shots)}

    scarti = [s for s in shots if s.verdict == "drop"]
    for s in scarti:
        s.reason = "scartata: " + (s.issues[0] if s.issues else "inutilizzabile")
    tenute = [s for s in shots if s.verdict != "drop"]

    doppioni: list[Shot] = []
    if dedupe and len(tenute) > 1:
        tenute, doppioni = drop_duplicates(tenute)
        # drop_duplicates scorre per punteggio e restituisce in quell'ordine:
        # senza rimetterle a posto un ordine cronologico richiesto uscirebbe
        # rimescolato proprio da chi doveva solo togliere i doppioni.
        tenute.sort(key=lambda s: posizione[id(s)])

    tenute, fuori = select(tenute, st, target_duration)

    ordinate = arrange(tenute, st, keep_order=order != "score")
    if order == "score":
        ordinate = avoid_monotony(ordinate)
    ordinate = pace(ordinate, st, target_duration)
    # con un ordine richiesto (cronologia, numerazione) non si riordina di
    # nascosto: se restano due riprese simili attaccate lo si dice e basta
    attaccate = sum(1 for a, b in zip(ordinate, ordinate[1:])
                    if similarity(a.fingerprint, b.fingerprint) >= 0.99)

    t = 0.0
    timeline = []
    for i, s in enumerate(ordinate):
        timeline.append({
            "ordine": i, "path": s.path, "nome": Path(s.path).name,
            "in": round(s.in_, 3), "out": round(s.out, 3),
            "durata": round(s.used, 3), "inizio_timeline": round(t, 3),
            "punteggio": s.score, "energia": s.energy, "parlato": s.speech,
            "qualita": s.quality, "perche": s.reason,
            "transizione": st.transition if i else "cut",
        })
        t += s.used

    # Con le riprese spezzate gli scarti sono centinaia di tratti: elencarli
    # tutti seppellisce le poche righe che si leggono davvero. Si mostrano i
    # primi, il resto si conta.
    buttate = scarti + doppioni
    note = _notes(ordinate, st, t, target_duration, attaccate, order)
    if spezzati:
        note.insert(0, f"{len(paths)} riprese spezzate in {len(shots)} tratti; "
                       f"{len(ordinate)} entrano nel montaggio")
    if fuori:
        note.append(f"{len(fuori)} tratti buoni restano fuori per la durata "
                    f"richiesta: alza target_duration per farne entrare altri")

    return {
        "stile": {"nome": st.name, "label": st.label, "desc": st.desc,
                  "taglio": [st.shot_min, st.shot_max], "transizione": st.transition},
        "ordine": order,
        "durata_totale": round(t, 3),
        "tratti_valutati": len(shots),
        "clip": timeline,
        "scartate": [{"nome": Path(s.path).name, "path": s.path,
                      "in": round(s.in_, 3), "out": round(s.out, 3),
                      "perche": s.reason, "problemi": s.issues}
                     for s in buttate[:20]],
        "scartate_totale": len(buttate),
        "note": note,
    }


def _notes(shots: list[Shot], style: Style, total: float, target: float | None,
           attaccate: int = 0, order: str = "score") -> list[str]:
    out = []
    if not shots:
        out.append("non resta niente di montabile: tutto il materiale e' stato scartato")
        return out
    if attaccate:
        out.append(
            f"{attaccate} coppie di inquadrature quasi identiche restano attaccate: "
            + ("l'ordine richiesto ha la precedenza, se vuoi che le separi usa "
               "order='score'" if order != "score"
               else "non c'era dove spostarle"))
    if target and abs(total - target) > 0.5:
        out.append(f"durata {total:.1f}s contro {target:.1f}s richiesti: "
                   f"{'serve altro materiale' if total < target else 'si puo\' stringere ancora'}")
    if len(shots) > 2 and all(s.speech < 0.15 for s in shots):
        out.append("nessun parlato: senza voce o musica il montaggio regge solo "
                   "se le immagini sono forti, valuta una traccia audio")
    if style.transition != "cut":
        out.append(f"transizione {style.transition} di {style.transition_dur}s tra le clip")
    lento = [s for s in shots if s.energy < 0.05]
    if len(lento) > len(shots) / 2:
        out.append("meta' del materiale e' statico: alterna inquadrature diverse "
                   "o accorcia, e' il caso tipico in cui si smette di guardare")
    return out


def apply_plan(store, plan_data: dict, track: str | None = None) -> dict:
    """Costruisce la timeline dal piano: importa, taglia, dispone, transizioni.

    Tutto dentro un blocco solo: applicare un piano e' un gesto, e con le riprese
    spezzate le clip sono decine — una modifica per clip vorrebbe dire decine di
    undo per tornare indietro da una scelta sola.
    """
    with store.batch():
        media = {p: m.id for p, m in zip(
            dict.fromkeys(i["path"] for i in plan_data["clip"]),
            store.import_media(list(dict.fromkeys(i["path"] for i in plan_data["clip"]))))}
        clips = store.add_clips([
            {"media": media[i["path"]], "start": i["inizio_timeline"],
             "in": i["in"], "duration": i["durata"]}
            for i in plan_data["clip"]], track_id=track)
        creati = [c.id for c in clips]

        trans = plan_data["stile"].get("transizione", "cut")
        if trans and trans != "cut" and len(creati) > 1:
            dur = STYLES[plan_data["stile"]["nome"]].transition_dur
            # la transizione e' in uscita: l'ultima clip non ne ha una
            for cid in creati[:-1]:
                store.set_transition(cid, trans, dur)
    return {"clip": creati, "durata": plan_data["durata_totale"]}
