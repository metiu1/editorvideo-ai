"""Operazioni di montaggio che nessun singolo comando copriva.

Sono quattro cose che in una sala di montaggio si danno per scontate e che qui
mancavano:

- **insert** - infilare una clip in mezzo spingendo a destra il resto, invece di
  appoggiarla e sperare;
- **micro-dissolvenze** - due o tre fotogrammi di sfumatura audio su ogni
  giunzione: senza, dopo un taglio si sente il click;
- **ducking** - la musica che si abbassa da sola quando qualcuno parla;
- **J/L cut** - l'audio che entra prima o resta dopo lo stacco video, la tecnica
  che rende un montaggio invisibile.

Il ducking qui non usa un compressore sidechain ma **automazione del volume**
calcolata dai tratti di parlato: e' deterministica, si vede nel progetto, si
corregge a mano e si annulla con undo. Un sidechain sarebbe una scatola nera.
"""

from __future__ import annotations

from . import analyze
from .cleanup import merge_spans

MICRO_FADE = 0.06          # ~1.5 fotogrammi a 25fps: non si vede, si sente
DUCK_DB = -12.0
ATTACK = 0.25              # quanto ci mette la musica ad abbassarsi
RELEASE = 0.6              # ...e a tornare su: piu' lento, altrimenti "pompa"
EPS = 1e-3


# --------------------------------------------------------------------------
# insert
# --------------------------------------------------------------------------


def insert_clip(store, media_id: str, at: float, track_id: str | None = None,
                duration: float | None = None, in_: float = 0.0) -> dict:
    """Inserisce una clip al tempo ``at`` spingendo a destra tutto il resto.

    Se una clip sta a cavallo del punto di inserimento viene divisa: e' quello
    che ci si aspetta da un insert, non un sovrascrivere.
    """
    m = store.media_or_die(media_id)
    if track_id is None:
        track_id = store._default_track("audio" if m.kind == "audio" else "video")
    track = store.track_for_edit(track_id)
    dur = duration if duration is not None else max(0.1, m.duration - in_)

    a_cavallo = next((c for c in track.clips
                      if c.start + EPS < at < c.end - EPS), None)
    if a_cavallo is not None:
        store.split_clip(a_cavallo.id, at)

    track = store.track_or_die(track_id)
    # da destra verso sinistra: cosi' nessuna clip finisce sopra un'altra mentre
    # le si sposta una alla volta
    for c in sorted(track.clips, key=lambda x: -x.start):
        if c.start >= at - EPS:
            store.move_clip(c.id, start=round(c.start + dur, 3))

    nuova = store.add_clip(media_id, track_id=track_id, start=round(at, 3),
                           in_=in_, duration=round(dur, 3))
    return {"clip": nuova.id, "start": nuova.start, "durata": nuova.duration,
            "spostate": sum(1 for c in store.track_or_die(track_id).clips
                            if c.start >= at + dur - EPS)}


# --------------------------------------------------------------------------
# micro-dissolvenze
# --------------------------------------------------------------------------


def smooth_cuts(store, track_id: str | None = None, duration: float = MICRO_FADE,
                only_touching: bool = True) -> dict:
    """Mette una micro-dissolvenza audio su ogni giunzione tra clip.

    ``only_touching`` limita l'intervento ai punti dove due clip si toccano
    davvero: sono quelli che fanno il click. Con False sfuma anche l'inizio e la
    fine di clip isolate.
    """
    tracce = ([store.track_for_edit(track_id)] if track_id
              else [t for t in store.project.tracks if not t.locked])
    toccate = 0
    for track in tracce:
        clips = sorted(track.clips, key=lambda c: c.start)
        for i, c in enumerate(clips):
            prima = clips[i - 1] if i else None
            dopo = clips[i + 1] if i + 1 < len(clips) else None
            attacca = prima is not None and abs(prima.end - c.start) < 0.02
            stacca = dopo is not None and abs(c.end - dopo.start) < 0.02
            fi = duration if (attacca or not only_touching) else None
            fo = duration if (stacca or not only_touching) else None
            if fi is None and fo is None:
                continue
            limite = max(0.0, min(duration, c.duration / 3))
            store.set_audio(c.id,
                            fade_in=limite if fi is not None else None,
                            fade_out=limite if fo is not None else None)
            toccate += 1
    return {"clip_sfumate": toccate, "durata": duration}


# --------------------------------------------------------------------------
# ducking
# --------------------------------------------------------------------------


def speech_ranges(store, clip_id: str, min_speech: float = 0.3) -> list[tuple[float, float]]:
    """Tratti in cui la clip parla, in tempo di **timeline**."""
    _, clip = store.clip_or_die(clip_id)
    if not clip.media:
        raise ValueError(f"la clip {clip_id} non ha un file sorgente")
    path = store.media_or_die(clip.media).path
    inizio, fine = clip.in_, clip.in_ + clip.source_duration()
    speed = abs(clip.speed or 1.0)

    muti = []
    for a, b in analyze.silences(path):
        b = fine if b < 0 else b
        muti.append((max(a, inizio), min(b, fine)))

    parlato, t = [], inizio
    for a, b in merge_spans(muti):
        if a - t > min_speech:
            parlato.append((t, a))
        t = max(t, b)
    if fine - t > min_speech:
        parlato.append((t, fine))

    return [(round(clip.start + (a - inizio) / speed, 3),
             round(clip.start + (b - inizio) / speed, 3)) for a, b in parlato]


def duck_keyframes(ranges, clip_start: float, clip_duration: float,
                   amount_db: float = DUCK_DB, attack: float = ATTACK,
                   release: float = RELEASE) -> list[dict]:
    """Automazione del guadagno: 0 dB fuori dal parlato, ``amount_db`` sotto.

    I keyframe sono relativi all'inizio della clip, come vuole il modello.
    """
    punti: list[tuple[float, float]] = [(0.0, 0.0)]
    for a, b in merge_spans([(x, y) for x, y in ranges]):
        la, lb = a - clip_start, b - clip_start
        if lb <= 0 or la >= clip_duration:
            continue
        for t, v in ((la - attack, 0.0), (la, amount_db),
                     (lb, amount_db), (lb + release, 0.0)):
            punti.append((max(0.0, min(clip_duration, t)), v))
    punti.append((clip_duration, 0.0))

    punti.sort(key=lambda p: p[0])
    out: list[dict] = []
    for t, v in punti:
        if out and abs(out[-1]["t"] - t) < EPS:
            # due punti sullo stesso istante: vince l'abbassamento, altrimenti
            # una rampa di rilascio cancellerebbe l'attacco successivo
            out[-1]["v"] = min(out[-1]["v"], v)
            continue
        out.append({"t": round(t, 3), "v": round(v, 2)})
    return out


def duck_music(store, music_clip: str, voice_clip: str, amount_db: float = DUCK_DB,
               attack: float = ATTACK, release: float = RELEASE,
               apply: bool = True) -> dict:
    """Abbassa la musica quando la voce parla, con rampe di attacco e rilascio."""
    _, musica = store.clip_or_die(music_clip)
    parlato = speech_ranges(store, voice_clip)
    if not parlato:
        return {"tratti_di_parlato": 0, "keyframe": 0, "applicato": False,
                "nota": "nessun parlato rilevato nella clip voce"}
    kfs = duck_keyframes(parlato, musica.start, musica.duration,
                         amount_db, attack, release)
    if apply:
        store.set_audio(music_clip, gain_db={"kf": kfs})
    return {"tratti_di_parlato": len(parlato), "keyframe": len(kfs),
            "amount_db": amount_db, "applicato": apply,
            "parlato": parlato[:8]}


# --------------------------------------------------------------------------
# J/L cut
# --------------------------------------------------------------------------


def detach_audio(store, clip_id: str, track_id: str | None = None) -> dict:
    """Porta l'audio della clip su una traccia audio separata.

    Da qui in poi audio e video si muovono in modo indipendente: e' la
    condizione per qualunque J/L cut.
    """
    _, clip = store.clip_or_die(clip_id)
    if not clip.media:
        raise ValueError(f"la clip {clip_id} non ha un file sorgente")
    m = store.media_or_die(clip.media)
    if not m.has_audio:
        raise ValueError(f"{m.name} non ha audio da scollegare")

    if track_id is None:
        audio_tracks = [t for t in store.project.tracks if t.kind == "audio"]
        track_id = (audio_tracks[0].id if audio_tracks
                    else store.add_track("audio").id)
    nuova = store.add_clip(m.id, track_id=track_id, start=clip.start,
                           in_=clip.in_, duration=clip.duration)
    store.set_audio(clip_id, mute=True)
    return {"audio_clip": nuova.id, "traccia": track_id, "video_clip": clip_id}


def jl_cut(store, clip_id: str, seconds: float = 0.5, kind: str = "J") -> dict:
    """Anticipa (J) o prolunga (L) l'audio rispetto allo stacco video.

    - **J**: l'audio di questa clip comincia *prima* che se ne veda l'immagine.
      Si sente la scena nuova mentre si guarda ancora quella vecchia.
    - **L**: l'audio continua *dopo* che l'immagine e' gia' passata alla clip
      successiva.

    Se l'audio non e' ancora scollegato lo scollega da solo.
    """
    if kind not in ("J", "L"):
        raise ValueError("kind deve essere 'J' o 'L'")
    if seconds <= 0:
        raise ValueError("seconds deve essere positivo")

    _, clip = store.clip_or_die(clip_id)
    gemella = _audio_twin(store, clip)
    if gemella is None:
        gemella_id = detach_audio(store, clip_id)["audio_clip"]
    else:
        gemella_id = gemella.id
        store.set_audio(clip_id, mute=True)

    _, audio = store.clip_or_die(gemella_id)
    if kind == "J":
        possibile = min(seconds, audio.in_, audio.start)
        if possibile <= 0:
            return {"applicato": 0.0, "tipo": kind, "audio_clip": gemella_id,
                    "nota": "niente materiale prima dell'attacco: J cut impossibile"}
        store.move_clip(gemella_id, start=round(audio.start - possibile, 3))
        store.set_clip(gemella_id, in_=round(audio.in_ - possibile, 3),
                       duration=round(audio.duration + possibile, 3))
    else:
        m = store.media_or_die(audio.media)
        avanzo = max(0.0, m.duration - (audio.in_ + audio.source_duration()))
        possibile = min(seconds, avanzo)
        if possibile <= 0:
            return {"applicato": 0.0, "tipo": kind, "audio_clip": gemella_id,
                    "nota": "niente materiale dopo lo stacco: L cut impossibile"}
        store.set_clip(gemella_id, duration=round(audio.duration + possibile, 3))
    return {"applicato": round(possibile, 3), "tipo": kind,
            "audio_clip": gemella_id, "video_clip": clip_id}


def _audio_twin(store, clip):
    """La clip audio gia' scollegata da questa, se c'e'."""
    for t in store.project.tracks:
        if t.kind != "audio":
            continue
        for c in t.clips:
            if c.media == clip.media and abs(c.start - clip.start) < 0.05:
                return c
    return None
