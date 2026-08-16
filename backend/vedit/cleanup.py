"""Togliere dalla timeline cio' che non serve: silenzi, esitazioni, tratti morti.

Il taglio vero e' un'operazione sulla timeline, non sul file: la clip viene
divisa nei punti giusti e i pezzi da buttare vengono rimossi. Cosi' resta tutto
reversibile (undo) e il materiale originale non si tocca.

Ordine di lavoro: gli intervalli si applicano **dal fondo verso l'inizio**, cosi'
i tempi di quelli ancora da fare restano validi anche dopo un taglio.
"""

from __future__ import annotations

from . import analyze

MIN_PIECE = 0.08        # sotto questa durata un pezzo non ha senso: si scarta
MIN_CUT = 0.10          # tagli piu' corti di cosi' si sentono come glitch


def merge_spans(spans, gap: float = 0.05) -> list[tuple[float, float]]:
    """Unisce intervalli sovrapposti o separati da meno di ``gap``."""
    clean = sorted((float(a), float(b)) for a, b in spans if float(b) > float(a))
    out: list[list[float]] = []
    for a, b in clean:
        if out and a - out[-1][1] <= gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def invert_spans(spans, duration: float) -> list[tuple[float, float]]:
    """Il complemento: cio' che resta dopo aver tolto ``spans`` da [0, duration]."""
    out = []
    t = 0.0
    for a, b in merge_spans(spans):
        if a - t > MIN_PIECE:
            out.append((round(t, 3), round(min(a, duration), 3)))
        t = max(t, b)
    if duration - t > MIN_PIECE:
        out.append((round(t, 3), round(duration, 3)))
    return out


def cut_ranges(store, clip_id: str, ranges, ripple: bool = True) -> dict:
    """Rimuove dalla clip gli intervalli indicati (tempi relativi alla clip).

    ``ripple=True`` ricompatta la traccia alla fine; con False restano i buchi,
    utile se il montaggio deve mantenere il sincrono con un'altra traccia.
    """
    track, clip = store.clip_or_die(clip_id)
    base, fine = clip.start, clip.end
    spans = [(base + a, base + b) for a, b in merge_spans(ranges)]
    spans = [(max(a, base), min(b, fine)) for a, b in spans]
    spans = [(a, b) for a, b in spans if b - a >= MIN_CUT]
    if not spans:
        return {"tagli": 0, "secondi_tolti": 0.0, "clip": [clip_id]}

    tolti = 0.0
    rimossi = 0
    for a, b in sorted(spans, reverse=True):
        _, corrente = store.clip_or_die(clip_id)
        if a <= corrente.start + MIN_PIECE and b >= corrente.end - MIN_PIECE:
            store.remove_clip(clip_id)          # non resta niente da tenere
            tolti += corrente.duration
            rimossi += 1
            return {"tagli": rimossi, "secondi_tolti": round(tolti, 3), "clip": []}
        if b >= corrente.end - MIN_PIECE:        # taglio in coda
            d = corrente.end - a
            nuova = corrente.duration - d
            if nuova < MIN_PIECE:
                continue
            store.set_clip(clip_id, duration=round(nuova, 3))
        elif a <= corrente.start + MIN_PIECE:    # taglio in testa
            d = b - corrente.start
            nuova = corrente.duration - d
            if nuova < MIN_PIECE:
                continue
            store.set_clip(clip_id, in_=round(corrente.in_ + d, 3),
                           duration=round(nuova, 3))
        else:                                    # taglio interno: due split
            _, coda = store.split_clip(clip_id, a)
            store.split_clip(coda.id, b)
            store.remove_clip(coda.id)
        tolti += b - a
        rimossi += 1

    if ripple:
        store.close_gaps(track.id)
    ids = [c.id for c in store.clip_or_die(clip_id)[0].clips]
    return {"tagli": rimossi, "secondi_tolti": round(tolti, 3), "clip": ids}


def speech_spans_to_cut(path: str, clip, min_silence: float = 0.5, pad: float = 0.12,
                        fillers: bool = True, extra_fillers: tuple[str, ...] = (),
                        model_size: str = "small",
                        language: str | None = None) -> list[tuple[float, float]]:
    """Cosa togliere da una clip: pause troppo lunghe ed esitazioni.

    I tempi delle misure sono relativi al **file**; qui diventano relativi alla
    clip, tenendo conto del punto di attacco e della velocita'.
    """
    speed = abs(clip.speed or 1.0)
    inizio, fine = clip.in_, clip.in_ + clip.source_duration()

    grezzi: list[tuple[float, float]] = []
    for a, b in analyze.silences(path):
        b = fine if b < 0 else b
        a, b = a + pad, b - pad          # si lascia un po' d'aria attorno alla voce
        if b - a >= min_silence:
            grezzi.append((a, b))
    if fillers:
        for f in analyze.filler_spans(path, tuple(extra_fillers),
                                      model_size=model_size, language=language):
            grezzi.append((f["start"], f["end"]))

    locali = []
    for a, b in grezzi:
        a, b = max(a, inizio), min(b, fine)
        if b - a < MIN_CUT:
            continue
        locali.append(((a - inizio) / speed, (b - inizio) / speed))
    return merge_spans(locali)


def tighten(store, clip_id: str, min_silence: float = 0.5, pad: float = 0.12,
            fillers: bool = True, extra_fillers: tuple[str, ...] = (),
            ripple: bool = True, model_size: str = "small",
            language: str | None = None) -> dict:
    """Stringe una clip parlata: via le pause lunghe e le esitazioni."""
    _, clip = store.clip_or_die(clip_id)
    if not clip.media:
        raise ValueError(f"la clip {clip_id} non ha un file sorgente")
    path = store.media_or_die(clip.media).path
    prima = clip.duration

    spans = speech_spans_to_cut(path, clip, min_silence, pad, fillers,
                                tuple(extra_fillers), model_size, language)
    res = cut_ranges(store, clip_id, spans, ripple=ripple)
    res["durata_prima"] = round(prima, 3)
    res["durata_dopo"] = round(max(0.0, prima - res["secondi_tolti"]), 3)
    return res
