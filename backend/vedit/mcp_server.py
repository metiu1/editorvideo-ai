"""Server MCP: espone l'editor come strumenti per un agente.

Filosofia degli strumenti:
- pochi strumenti, ognuno con un compito chiaro;
- risposte compatte (l'agente non deve leggere l'intero progetto a ogni mossa);
- errori con messaggio utile, che dicono cosa era ammesso;
- ``preview_frame`` restituisce un'immagine vera, cosi' l'agente puo' *vedere*
  il risultato di un montaggio invece di indovinarlo.

Avvio: ``vedit-mcp`` (stdio).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import Image, MCPServer

from . import analyze, captions, cleanup, colormatch, ops
from . import effects as fx
from . import ffmpeg, hw, probe, proxy, render, review, story, versions, vision
from .model import TRANSITIONS
from .store import EditError, Store

# Le istruzioni del server arrivano a chiunque usi vedit, quindi qui non sta solo
# come si chiamano gli strumenti: sta anche come si monta. I difetti elencati
# sotto sono quelli veri, raccolti guardando i video che escono da questo editor
# quando lo guida un agente — musica a volume fisso, solo stacchi secchi,
# inquadrature ripetute, e un video che dopo dieci secondi non aggiunge piu'
# niente. Nessuno di questi e' un limite degli strumenti: sono scelte che non
# vengono fatte.
ISTRUZIONI = """\
Editor video non lineare.

Flusso: project_create -> import_media -> plan_edit (per scegliere il materiale) ->
add_clips -> rifiniture (set_transition, set_speed, set_transform, add_effect,
set_audio) -> preview_grid per guardare -> render_video.

I tempi sono in secondi. Ogni parametro animabile accetta anche
{'kf':[{'t':0,'v':0},{'t':2,'v':1,'ease':'ease_in_out'}]}, con t relativo
all'inizio della clip. project_info da' lo stato della timeline con gli id.
Per un montaggio serrato usa add_clips: mette tutti i tagli in una chiamata sola,
ed e' atomico.

== COME MONTARE ==

Regola sopra tutte: **guarda il risultato**. preview_grid mostra il montaggio
tutto insieme, preview_frame un fotogramma (alza width a 1280 per giudicare un
dettaglio). Un montaggio non guardato e' un montaggio non fatto.

1. LA MUSICA DEVE MUOVERSI. Una traccia a volume fisso per tutta la durata e' la
   prima cosa che rende un video piatto, e non si nota consapevolmente: si sente
   solo che "non succede niente". Usa music_beats: il profilo di energia dice
   dove sono intro, stacco e ritornello. Scegli una sezione con un arco vero
   (parte, sale, culmina intorno al 75%, atterra) invece dei primi 90 secondi.
   Automatizza il guadagno con keyframe veri —
   set_audio(gain_db={'kf':[...]}) — abbassando dove il video deve respirare e
   rialzando sul picco. Mezzo secondo di quasi silenzio prima di un colpo vale
   piu' di qualunque effetto. Chiudi con una dissolvenza sull'ultima battuta,
   non con un taglio netto sulla musica.

2. NON TUTTI STACCHI SECCHI. Il taglio secco e' il valore predefinito, non
   l'unica scelta: un video fatto di soli stacchi si legge come un elenco.
   Disponibili: crossfade / set_transition con dissolve, wipe_*, slide_*, iris;
   un flash bianco di 2-3 fotogrammi con add_color tra due clip; una rampa con
   set_speed; una spinta lenta con set_transform(scale={'kf':[...]}); i
   fotogrammi mossi del girato come giunzione naturale. Ogni transizione deve
   avere un motivo — cambio di luogo, di tempo, di intensita'. Se non ce l'ha,
   taglia secco: una dissolvenza messa a caso e' peggio di uno stacco.

3. MAI LA STESSA INQUADRATURA DUE VOLTE. Riusare lo stesso punto d'attacco si
   vede subito e fa sembrare il materiale finito. Tieni il conto dei tratti gia'
   usati (file + in/out) e controlla project_info prima di aggiungere. Se il
   materiale non basta, **accorcia il video**: novanta secondi con dieci
   ripetizioni valgono meno di sessanta senza.

4. DOPO DIECI SECONDI SERVE INFORMAZIONE NUOVA. Passata l'apertura chi guarda ha
   capito il tema; da li' in poi ogni blocco deve aggiungere qualcosa — un luogo
   nuovo, un soggetto nuovo, una conseguenza, un dettaglio che prima non si
   vedeva. Tagliare piu' veloce su immagini equivalenti non salva niente: il
   ritmo senza contenuto e' rumore. Ragiona a blocchi di 10-15 secondi, ognuno
   con una cosa nuova, e cambia scala tra loro (campo lungo, medio, dettaglio).
   Alterna anche le durate: tagli tutti uguali diventano un metronomo.

5. CINEMATOGRAFICO E' UNA SCELTA, NON UN FILTRO. Un momento forte tenuto tre
   secondi vale piu' di dieci da mezzo. Dai movimento dentro l'inquadratura
   (spinta lenta con set_transform), correggi il colore con mano leggera sul
   master (color, curves, temperature), riquadra se il soggetto sta in un
   angolo (set_transform o auto_reframe), e chiudi su un'immagine che riassume,
   tenuta abbastanza da respirare.

Montare a tempo: prendi bpm/beat/bar da music_beats e fai cadere gli stacchi
sulla griglia. Non stimare il tempo a occhio — un errore dell'1% su novanta
secondi e' quasi una battuta di deriva e gli stacchi finiscono fuori tempo.

Prima di dire che e' finito: preview_grid su tutto il montaggio, audio_levels per
i livelli, verify_edit per i problemi rimasti.
"""

mcp = MCPServer(
    name="vedit",
    version="0.1.0",
    instructions=ISTRUZIONI,
)

_stores: dict[str, Store] = {}
_current: list[str | None] = [None]


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------


def _store(project: str | None = None) -> Store:
    if project:
        key = str(Path(project).resolve())
        if key not in _stores:
            _stores[key] = Store.open(key)
        _current[0] = key
        return _stores[key]
    if _current[0] is None:
        raise EditError("nessun progetto aperto: usa project_create o project_open")
    return _stores[_current[0]]


def _clip_view(c) -> dict:
    out = {"id": c.id, "type": c.type, "start": round(c.start, 3),
           "duration": round(c.duration, 3), "end": round(c.end, 3)}
    if c.type == "media":
        out["media"] = c.media
        out["in"] = round(c.in_, 3)
    if abs(c.speed - 1.0) > 1e-6:
        out["speed"] = c.speed
    return out


async def _off(fn, *args, **kwargs):
    """Esegue lavoro bloccante (ffmpeg) fuori dal loop asincrono."""
    return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))


# --------------------------------------------------------------------------
# progetto
# --------------------------------------------------------------------------


@mcp.tool()
def project_create(path: str, name: str = "untitled", preset: str = "1080p",
                   width: int | None = None, height: int | None = None,
                   fps: float | None = None) -> dict:
    """Crea un progetto e lo rende quello corrente.

    preset: 1080p, 1080p60, 4k, 720p, vertical (9:16 per reel/short), vertical60, square.
    """
    s = Store.create(name=name, preset=preset, path=path, width=width, height=height, fps=fps)
    key = str(Path(s.path).resolve())
    _stores[key] = s
    _current[0] = key
    return {"path": s.path, "settings": s.summary()["settings"], "tracks": ["V1", "A1"]}


@mcp.tool()
def project_open(path: str) -> dict:
    """Apre un progetto esistente (.json) e lo rende quello corrente."""
    # sempre riletto da disco: il file puo' essere cambiato dalla UI o da un
    # altro processo, e la copia in memoria mostrerebbe uno stato vecchio.
    # Non si perde nulla: ogni modifica viene gia' salvata subito (autosave).
    key = str(Path(path).resolve())
    _stores[key] = Store.open(key)
    _current[0] = key
    return _stores[key].summary()


@mcp.tool()
def project_info(detail: str = "normal", project: str | None = None) -> dict:
    """Stato completo della timeline: media, tracce, clip, effetti, durata.

    detail='full' aggiunge transform e audio di ogni clip.
    """
    return _store(project).summary(detail)


@mcp.tool()
def project_save(path: str | None = None, project: str | None = None) -> dict:
    """Salva il progetto (di norma non serve: il salvataggio e' automatico)."""
    return {"saved": _store(project).save(path)}


@mcp.tool()
def project_settings(width: int | None = None, height: int | None = None, fps: float | None = None,
                     background: str | None = None, sample_rate: int | None = None,
                     project: str | None = None) -> dict:
    """Cambia risoluzione, fps, colore di sfondo o sample rate del progetto."""
    s = _store(project)
    st = s.set_settings(width=width, height=height, fps=fps, background=background,
                        sample_rate=sample_rate)
    return {"width": st.width, "height": st.height, "fps": st.fps, "background": st.background}


@mcp.tool()
def undo(project: str | None = None) -> dict:
    """Annulla l'ultima modifica."""
    return {"undone": _store(project).undo()}


@mcp.tool()
def redo(project: str | None = None) -> dict:
    """Ripete la modifica annullata."""
    return {"redone": _store(project).redo()}


# --------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------


@mcp.tool()
async def import_media(paths: list[str] | None = None, files: list[str] | None = None,
                       project: str | None = None) -> list[dict]:
    """Importa file video/audio/immagine nel progetto leggendone i metadati.

    ``files`` e' accettato come sinonimo di ``paths``: sono lo stesso argomento.
    """
    lista = paths if paths is not None else files
    if not lista:
        raise EditError("serve paths (o files): la lista dei file da importare")
    s = _store(project)
    media = await _off(s.import_media, lista)
    return [{"id": m.id, "name": m.name, "kind": m.kind, "duration": m.duration,
             "resolution": f"{m.width}x{m.height}" if m.width else None,
             "fps": m.fps or None, "audio": m.has_audio} for m in media]


@mcp.tool()
async def analyze_media(path: str) -> dict:
    """Legge i metadati di un file senza importarlo nel progetto."""
    m = await _off(probe.probe, path)
    return {"kind": m.kind, "duration": m.duration, "width": m.width, "height": m.height,
            "fps": m.fps, "has_audio": m.has_audio, "sample_rate": m.sample_rate,
            "channels": m.channels, "path": m.path}


@mcp.tool()
async def build_proxies(height: int = 540, project: str | None = None) -> dict:
    """Genera i proxy a bassa risoluzione: rende preview e frame molto piu' rapidi."""
    s = _store(project)
    done = await _off(proxy.ensure, s.project, height)
    s.save()
    return {"generati": len(done), "altezza": height}


# --------------------------------------------------------------------------
# tracce
# --------------------------------------------------------------------------


@mcp.tool()
def add_track(kind: str = "video", name: str | None = None, project: str | None = None) -> dict:
    """Aggiunge una traccia. Le tracce video successive stanno sopra le precedenti."""
    t = _store(project).add_track(kind, name)
    return {"id": t.id, "kind": t.kind, "name": t.name}


@mcp.tool()
def set_track(track: str, hidden: bool | None = None, muted: bool | None = None,
              volume: Any = None, name: str | None = None, locked: bool | None = None,
              solo: bool | None = None, project: str | None = None) -> dict:
    """Stato di una traccia.

    hidden nasconde il video, muted la silenzia, solo isola (le altre tacciono),
    locked la protegge dalle modifiche, volume 0..N e' animabile.
    E' anche l'unico modo di sbloccare una traccia bloccata.
    """
    t = _store(project).set_track(track, hidden=hidden, muted=muted, volume=volume,
                                  name=name, locked=locked, solo=solo)
    return {"id": t.id, "hidden": t.hidden, "muted": t.muted, "solo": t.solo,
            "locked": t.locked, "volume": t.volume}


@mcp.tool()
def move_track(track: str, index: int, project: str | None = None) -> dict:
    """Cambia l'ordine di una traccia tra quelle dello stesso tipo.

    Per il video l'ordine e' la sovrapposizione: 0 sta sotto, l'ultimo sopra tutti.
    """
    order = _store(project).move_track(track, index)
    return {"ordine": order}


@mcp.tool()
def remove_track(track: str, project: str | None = None) -> dict:
    """Elimina una traccia e tutte le sue clip."""
    _store(project).remove_track(track)
    return {"rimossa": track}


# --------------------------------------------------------------------------
# clip
# --------------------------------------------------------------------------


@mcp.tool()
def add_clip(media: str, track: str | None = None, start: float | None = None,
             in_point: float = 0.0, duration: float | None = None,
             project: str | None = None) -> dict:
    """Mette un media in timeline.

    start=None accoda alla fine della traccia. in_point/duration ritagliano la
    sorgente; duration=None usa tutto il resto del media (5s per le immagini).
    """
    c = _store(project).add_clip(media, track, start, in_point, duration)
    return _clip_view(c)


@mcp.tool()
def add_text(text: str, start: float = 0.0, duration: float = 3.0, track: str | None = None,
             font_size: int = 64, color: str = "white", align: str = "center",
             box: bool = False, box_color: str = "black", box_opacity: float = 0.5,
             border_width: int = 0, font_file: str | None = None,
             project: str | None = None) -> dict:
    """Aggiunge un titolo/sottotitolo in sovrimpressione.

    Il testo sta su tutto il canvas: per spostarlo usa set_transform (x, y),
    per animarlo in entrata usa keyframe su opacity o y.
    """
    c = _store(project).add_text(
        text, track, start, duration, font_size=font_size, color=color, align=align,
        box=box, box_color=box_color, box_opacity=box_opacity,
        border_width=border_width, font_file=font_file,
    )
    return _clip_view(c)


@mcp.tool()
def add_clips(clips: list[dict], track: str | None = None, gap: float = 0.0,
              project: str | None = None) -> dict:
    """Mette in timeline una lista di tagli in una chiamata sola.

    Ogni voce e' ``{"media": "<id>", "start": 4.0, "in": 122.5, "duration": 1.5}``:
    ``start`` assente accoda in fila, ``duration`` assente prende il resto del
    media, ``track`` per voce se vuoi costruire piu' tracce insieme.

    Usalo *sempre* per un montaggio: una chiamata per taglio significa centinaia
    di andate e ritorni, altrettanti passi di undo per disfare quello che e' un
    gesto solo, e mezza timeline costruita se qualcosa si rompe a meta'. Qui o
    entrano tutti i tagli o non ne entra nessuno.

    Per accodare media *interi* senza ritagliarli c'e' append_sequence.
    """
    fatte = _store(project).add_clips(clips, track, gap)
    return {"aggiunte": len(fatte), "clip": [_clip_view(c) for c in fatte],
            "fine": round(max((c.start + c.duration for c in fatte), default=0.0), 3)}


@mcp.tool()
def add_color(color: str = "black", start: float = 0.0, duration: float = 2.0,
              track: str | None = None, project: str | None = None) -> dict:
    """Aggiunge una clip di colore pieno (stacco, fondale, schermata finale)."""
    return _clip_view(_store(project).add_color(color, track, start, duration))


@mcp.tool()
def split(clip: str, at: float, project: str | None = None) -> dict:
    """Taglia una clip in due nel punto ``at`` (tempo di timeline)."""
    a, b = _store(project).split_clip(clip, at)
    return {"prima": _clip_view(a), "dopo": _clip_view(b)}


@mcp.tool()
def trim(clip: str, in_point: float | None = None, out_point: float | None = None,
         duration: float | None = None, project: str | None = None) -> dict:
    """Cambia il punto di attacco/stacco nella sorgente o la durata in timeline."""
    return _clip_view(_store(project).trim_clip(clip, in_point, duration, out_point))


@mcp.tool()
def move(clip: str, start: float | None = None, track: str | None = None,
         project: str | None = None) -> dict:
    """Sposta una clip nel tempo e/o su un'altra traccia."""
    return _clip_view(_store(project).move_clip(clip, start, track))


@mcp.tool()
def delete(clip: str, ripple: bool = False, project: str | None = None) -> dict:
    """Elimina una clip. ripple=True chiude il buco spostando indietro le successive."""
    _store(project).remove_clip(clip, ripple)
    return {"eliminata": clip, "ripple": ripple}


@mcp.tool()
def set_speed(clip: str, speed: float, keep_duration: bool = False,
              reverse: bool | None = None, project: str | None = None) -> dict:
    """Cambia velocita' (2.0 = doppia, 0.5 = slow motion) ed eventualmente inverte.

    keep_duration=True mantiene la durata in timeline consumando piu'/meno sorgente.
    """
    s = _store(project)
    c = s.set_speed(clip, speed, keep_duration)
    if reverse is not None:
        c = s.set_reverse(clip, reverse)
    return _clip_view(c)


@mcp.tool()
def set_clip(clip: str, enabled: bool | None = None, fit: str | None = None,
             name: str | None = None, color: str | None = None,
             project: str | None = None) -> dict:
    """Proprieta' semplici: attiva/disattiva, adattamento al canvas, nome, colore.

    fit: contain (tutto visibile, bande), cover (riempie tagliando), stretch, none.
    """
    c = _store(project).set_clip(clip, enabled=enabled, fit=fit, name=name, color=color)
    return _clip_view(c)


@mcp.tool()
def set_text(clip: str, text: str | None = None, font_size: int | None = None,
             color: str | None = None, align: str | None = None, box: bool | None = None,
             box_color: str | None = None, box_opacity: float | None = None,
             border_width: int | None = None, border_color: str | None = None,
             font_file: str | None = None, project: str | None = None) -> dict:
    """Modifica il contenuto o lo stile di una clip di testo."""
    c = _store(project).set_text(
        clip, text=text, font_size=font_size, color=color, align=align, box=box,
        box_color=box_color, box_opacity=box_opacity, border_width=border_width,
        border_color=border_color, font_file=font_file)
    return {"id": c.id, "text": c.text.text, "font_size": c.text.font_size}


@mcp.tool()
def set_transform(clip: str, x: Any = None, y: Any = None, scale: Any = None,
                  rotation: Any = None, opacity: Any = None, project: str | None = None) -> dict:
    """Posizione, dimensione, rotazione e opacita' della clip sul canvas.

    x/y sono offset in pixel dal centro (y negativo = verso l'alto), scale 1.0 =
    dimensione naturale, rotation in gradi, opacity 0..1. Tutti animabili con
    keyframe. Esempio zoom lento: scale={"kf":[{"t":0,"v":1},{"t":5,"v":1.2}]}.
    """
    c = _store(project).set_transform(clip, x=x, y=y, scale=scale, rotation=rotation,
                                      opacity=opacity)
    return {"id": c.id, "transform": vars(c.transform)}


@mcp.tool()
def set_audio(clip: str, gain_db: Any = None, mute: bool | None = None,
              fade_in: float | None = None, fade_out: float | None = None,
              pan: float | None = None, project: str | None = None) -> dict:
    """Volume (dB, animabile), silenziamento, dissolvenze audio e panning (-1..1)."""
    c = _store(project).set_audio(clip, gain_db=gain_db, mute=mute, fade_in=fade_in,
                                  fade_out=fade_out, pan=pan)
    return {"id": c.id, "audio": vars(c.audio)}


@mcp.tool()
def set_fades(clip: str, fade_in: float | None = None, fade_out: float | None = None,
              audio: bool = True, project: str | None = None) -> dict:
    """Dissolvenza video in entrata/uscita (in secondi), audio incluso di default."""
    c = _store(project).set_fades(clip, fade_in, fade_out, audio)
    return {"id": c.id, "fade_in": c.fade_in, "fade_out": c.fade_out}


# --------------------------------------------------------------------------
# montaggio
# --------------------------------------------------------------------------


@mcp.tool()
def crossfade(clip_a: str, clip_b: str, duration: float = 1.0, type: str = "dissolve",
              project: str | None = None) -> dict:
    """Transizione tra due clip consecutive della stessa traccia.

    B viene avvicinata ad A di ``duration`` secondi e tutto cio' che segue si sposta.
    type: dissolve, wipe_left/right/up/down (tendina), slide_left/right/up/down
    (la clip esce di scena), iris (cerchio). L'audio incrocia sempre in dissolvenza.
    """
    return _store(project).crossfade(clip_a, clip_b, duration, type)


@mcp.tool()
def set_transition(clip: str, type: str = "dissolve", duration: float = 1.0,
                   project: str | None = None) -> dict:
    """Cambia la transizione in uscita di una clip senza spostare nulla.

    Usalo per modificare una transizione gia' creata con crossfade, o quando le
    clip si sovrappongono gia'. duration=0 la toglie.
    """
    return _store(project).set_transition(clip, type, duration)


@mcp.tool()
def list_transitions() -> list[str]:
    """Tipi di transizione disponibili."""
    return list(TRANSITIONS)


@mcp.tool()
def append_sequence(media: list[str], track: str | None = None, crossfade: float = 0.0,
                    project: str | None = None) -> list[dict]:
    """Accoda piu' media in fila, con dissolvenza incrociata opzionale tra loro."""
    return [_clip_view(c) for c in _store(project).append_sequence(media, track, crossfade)]


@mcp.tool()
def close_gaps(track: str, project: str | None = None) -> dict:
    """Compatta la traccia eliminando i buchi tra le clip."""
    return {"clip_spostate": _store(project).close_gaps(track)}


# --------------------------------------------------------------------------
# effetti
# --------------------------------------------------------------------------


@mcp.tool()
def list_effects(kind: str | None = None) -> list[dict]:
    """Catalogo degli effetti disponibili con parametri, range e animabilita'.

    kind='video' o 'audio' per filtrare. Consultalo prima di usare add_effect.
    """
    return fx.describe(kind)


@mcp.tool()
def add_effect(type: str, clip: str | None = None, params: dict | None = None,
               project: str | None = None) -> dict:
    """Applica un effetto a una clip (clip=None lo applica al master).

    I parametri sono validati contro il catalogo: vedi list_effects.
    """
    e = _store(project).add_effect(clip, type, params)
    lst = _store(project)._effect_list(clip)
    return {"clip": clip, "index": len(lst) - 1, "type": e.type, "params": e.params}


@mcp.tool()
def update_effect(index: int, clip: str | None = None, params: dict | None = None,
                  enabled: bool | None = None, project: str | None = None) -> dict:
    """Modifica i parametri di un effetto gia' applicato (index da project_info)."""
    e = _store(project).update_effect(clip, index, params, enabled)
    return {"clip": clip, "index": index, "type": e.type, "params": e.params, "enabled": e.enabled}


@mcp.tool()
def move_effect(index: int, to: int, clip: str | None = None,
                project: str | None = None) -> dict:
    """Sposta un effetto nella catena: l'ordine cambia il risultato.

    Denoise prima di sharpen pulisce e poi incide; l'ordine opposto incide anche
    il rumore e poi lo ammorbidisce. Stessi due effetti, immagini diverse.
    """
    lst = _store(project).move_effect(clip, index, to)
    return {"clip": clip, "catena": [e.type for e in lst]}


@mcp.tool()
def remove_effect(index: int, clip: str | None = None, project: str | None = None) -> dict:
    """Rimuove un effetto dalla clip (o dal master se clip=None)."""
    _store(project).remove_effect(clip, index)
    return {"rimosso": index, "clip": clip}


# --------------------------------------------------------------------------
# audio master
# --------------------------------------------------------------------------


@mcp.tool()
async def normalize_audio(target_lufs: float = -14.0, measure: bool = True,
                          true_peak: float = -1.0, project: str | None = None) -> dict:
    """Normalizza il volume complessivo allo standard EBU R128.

    -14 LUFS = YouTube/Spotify, -16 = podcast, -23 = broadcast TV.
    measure=True fa il primo passaggio di analisi sul mix (piu' lento ma preciso:
    normalizzazione lineare senza pompaggio).
    """
    s = _store(project)
    measured = None
    if measure:
        measured = await _off(render.measure_loudness, s.project)
    return s.set_loudnorm(True, target_lufs, true_peak, measured=measured)


@mcp.tool()
async def audio_levels(clip: str | None = None, project: str | None = None) -> dict:
    """Misura il livello (LUFS integrato, true peak, range) del mix o di una clip."""
    s = _store(project)
    if clip is None:
        data = await _off(render.measure_loudness, s.project)
    else:
        _, c = s.clip_or_die(clip)
        m = s.media_or_die(c.media or "")
        data = await _off(probe.loudness, m.path, c.in_, c.source_duration())
    return {"lufs": float(data.get("input_i", 0)), "true_peak_db": float(data.get("input_tp", 0)),
            "lra": float(data.get("input_lra", 0)), "soglia": float(data.get("input_thresh", 0))}


# --------------------------------------------------------------------------
# analisi del materiale
# --------------------------------------------------------------------------


def _e_un_progetto(p: Path) -> bool:
    """Il file e' un progetto vedit, non del girato."""
    if p.suffix.lower() != ".json":
        return False
    try:
        with p.open(encoding="utf-8") as f:
            return '"tracks"' in f.read(4096)
    except OSError:
        return False


def _source(path: str | None, clip: str | None, project: str | None,
            media: str | None = None) -> str:
    """Percorso del file da analizzare: da file, da media importato o da clip.

    Qui ``path`` e' il *file sorgente*, mentre in quasi tutti gli altri strumenti
    e' il progetto: passare il progetto per sbaglio e' l'errore naturale, e prima
    finiva dentro ffmpeg producendo un ``Invalid data found when processing
    input`` che non dice niente. Adesso lo si riconosce e lo si spiega.
    """
    if path:
        p = Path(path)
        if not p.exists():
            raise EditError(f"file non trovato: {path}")
        if _e_un_progetto(p):
            raise EditError(
                f"{p.name} e' un progetto, non del girato: qui 'path' vuole il file "
                "sorgente. Indica il materiale con media='<id>' oppure clip='<id>' "
                "e passa il progetto in 'project'.")
        return str(p.resolve())
    if media:
        return _store(project).media_or_die(media).path
    if not clip:
        raise EditError("serve path (file sorgente), media oppure clip")
    s = _store(project)
    _, c = s.clip_or_die(clip)
    if not c.media:
        raise EditError(f"la clip {clip} non ha un file sorgente")
    return s.media_or_die(c.media).path


@mcp.tool()
async def inspect_footage(path: str | None = None, clip: str | None = None,
                          media: str | None = None, deep: bool = False,
                          model: str = "small", language: str | None = None,
                          project: str | None = None) -> dict:
    """Che cosa c'e' dentro il girato: tagli, silenzi, buio, fuori fuoco, verdetto.

    Il materiale si indica in tre modi: ``path`` = **file sorgente su disco**
    (non il progetto), ``media`` = id di un media gia' importato, ``clip`` = id
    di una clip in timeline.

    Ritorna verdict = keep | trim | drop, gli ``issues`` che lo giustificano e
    suggested_in/out per accorciare. deep=True aggiunge la trascrizione (piu'
    lento la prima volta, poi e' in cache).

    Serve prima di montare: dice quali clip scartare e dove tagliarle.
    """
    src = _source(path, clip, project, media)
    return await _off(analyze.report, src, deep, model_size=model, language=language)


@mcp.tool()
async def music_beats(path: str | None = None, clip: str | None = None,
                      media: str | None = None, start: float = 0.0,
                      end: float | None = None, every: int = 0,
                      project: str | None = None) -> dict:
    """Battito e struttura di una traccia: BPM, griglia dei tempi, energia.

    Montare a tempo vuol dire far cadere gli stacchi sui battiti, e per farlo
    serve sapere dove sono. Ritorna ``bpm``, la durata di un battito (``beat``)
    e di una misura in 4/4 (``bar``), lo scostamento del primo battito
    (``offset``) e ``profilo``, l'energia per blocchi di 4 secondi normalizzata
    a 1: e' li' che si leggono intro, stacco e ritornello, cioe' dove mettere
    l'apertura e il picco.

    Con ``every`` > 0 aggiunge ``griglia``, gli istanti veri su cui tagliare:
    ``every=1`` ogni battito (tagli fitti), ``every=4`` ogni misura, ``every=8``
    ogni due misure. Limitala con start/end, altrimenti su un brano lungo sono
    migliaia di numeri.
    """
    src = _source(path, clip, project, media)
    out = dict(await _off(analyze.beats, src))
    if every > 0:
        out["griglia"] = await _off(analyze.beat_grid, src, start, end, every)
    return out


@mcp.tool()
async def transcribe(path: str | None = None, clip: str | None = None,
                     model: str = "small", language: str | None = None,
                     with_words: bool = False, project: str | None = None) -> dict:
    """Trascrive il parlato con i tempi, per capire il contenuto e dove tagliare.

    with_words=True aggiunge i timestamp per singola parola (serve per tagliare
    sulla pausa esatta o censurare una parola sola); senza, restituisce solo le
    frasi con inizio/fine, che e' molto piu' compatto da leggere.
    """
    src = _source(path, clip, project)
    tr = await _off(analyze.transcribe, src, model, language)
    segs = [{"t": s["start"], "e": s["end"], "text": s["text"]}
            if not with_words else s for s in tr["segments"]]
    return {"language": tr["language"], "words_per_minute": tr["words_per_minute"],
            "speech_seconds": tr["speech_seconds"], "text": tr["text"],
            "segments": segs}


@mcp.tool()
async def list_styles() -> dict:
    """Gli stili di montaggio disponibili e i numeri che li definiscono."""
    return {"stili": [{"nome": s.name, "label": s.label, "desc": s.desc,
                       "taglio_s": [s.shot_min, s.shot_max],
                       "apre_col_meglio": s.hook_first,
                       "transizione": s.transition} for s in story.STYLES.values()]}


@mcp.tool()
async def plan_edit(folder: str | None = None, files: list[str] | None = None,
                    style: str = "vlog", target_duration: float | None = None,
                    deep: bool = False, apply: bool = False, order: str = "score",
                    segment: bool = True, project: str | None = None) -> dict:
    """Da una cartella di girato alla scaletta: cosa entra, in che ordine, per quanto.

    Analizza tutto il materiale, scarta l'inutilizzabile e i doppioni, ordina
    secondo l'arco (apertura, salita, picco al 75%, chiusura) ed evita due
    inquadrature simili di fila. Ogni clip esce con il suo *perche'*.

    Le riprese lunghe vengono **spezzate nei loro tratti** e valutate a tratti,
    non a file: da tre minuti di ripresa continua escono decine di candidati con
    un punto d'attacco vero, invece di un punteggio solo per tutto il file.
    ``segment=False`` torna a un'inquadratura per file.

    style: shortform | vlog | documentary | cinematic (vedi list_styles).
    order: score (per punteggio) | chrono (data di ripresa vera, letta dai tag
    del file) | name. Con chrono/name l'apertura, il picco e la chiusura restano
    comunque scelti per punteggio: sono decisioni di ritmo.
    deep=True usa la trascrizione per pesare il parlato (piu' lento).
    apply=True costruisce davvero la timeline nel progetto corrente.

    Il piano va letto prima di applicarlo: e' li' che si discute il montaggio.
    """
    src = files if files else folder
    if not src:
        raise EditError("serve folder oppure files")
    p = await _off(story.plan, src, style, target_duration, deep, True, order, segment)
    if apply:
        p["applicato"] = story.apply_plan(_store(project), p)
    return p


@mcp.tool()
async def match_color(clip: str, reference: str, strength: float = 1.0,
                      apply: bool = True, project: str | None = None) -> dict:
    """Uniforma il colore di una clip a quello di una clip di riferimento.

    ``reference`` puo' essere l'id di un'altra clip o il percorso di un file.
    Allinea esposizione e dominante (media e deviazione per canale): serve a far
    sembrare girate insieme riprese fatte con camere o luci diverse.

    strength 0.5-0.7 quando le due inquadrature hanno contenuto molto diverso:
    al 100% le statistiche di un cielo trascinerebbero un primo piano.
    """
    s = _store(project)
    src = _source(None, clip, project)
    try:
        ref = _source(None, reference, project)
    except EditError:
        ref = _source(reference, None, project)
    res = await _off(colormatch.match, src, ref, strength)
    if apply:
        s.add_effect(clip, "colormatch", res["params"])
    return {"params": res["params"], "distanza_prima": res["distanza_prima"],
            "applicato": apply,
            "sorgente": res["sorgente"]["mean"], "riferimento": res["riferimento"]["mean"]}


@mcp.tool()
async def make_captions(clip: str | None = None, path: str | None = None,
                        output: str | None = None, format: str = "ass",
                        karaoke: bool = True, burn: bool = True,
                        max_chars: int = 42, uppercase: bool = False,
                        size: int = 64, primary: str = "#FFE100",
                        secondary: str = "#FFFFFF", margin_v: int = 120,
                        model: str = "small", language: str | None = None,
                        project: str | None = None) -> dict:
    """Genera i sottotitoli dal parlato e (se burn) li imprime sulla clip.

    format: ass (consigliato, porta il karaoke parola per parola stile
    TikTok/Reel) | srt | vtt. I colori sono #RRGGBB: ``primary`` e' la parola
    gia' pronunciata, ``secondary`` quella che deve ancora arrivare.

    Con ``clip`` i tempi vengono riportati all'inizio della clip, cosi' i
    sottotitoli restano in sincrono anche se la clip parte a meta' del file.
    """
    s = _store(project) if (clip or burn or project) else None
    src = _source(path, clip, project)
    tr = await _off(analyze.transcribe, src, model, language)

    offset = 0.0
    larghezza, altezza = 1080, 1920
    if clip:
        _, c = s.clip_or_die(clip)
        offset = c.in_
        larghezza, altezza = s.project.settings.width, s.project.settings.height

    righe = captions.group_words(tr, max_chars=max_chars, offset=offset)
    righe = [r for r in righe if r["end"] > 0]
    if not righe:
        return {"righe": 0, "file": None, "nota": "nessun parlato riconosciuto"}

    out = output or str(Path(tempfile.gettempdir()) / f"vedit_captions_{os.getpid()}.{format}")
    st = captions.CaptionStyle(size=size, primary=primary, secondary=secondary,
                               margin_v=margin_v, uppercase=uppercase)
    kw = {"style": st, "karaoke": karaoke, "width": larghezza, "height": altezza} \
        if format == "ass" else {}
    file = await _off(captions.write, out, righe, format, **kw)

    applicato = False
    if burn and clip:
        s.add_effect(clip, "subtitles", {"file": file})
        applicato = True
    return {"righe": len(righe), "file": file, "formato": format,
            "karaoke": karaoke and format == "ass", "applicato": applicato,
            "anteprima": [{"t": r["start"], "text": r["text"]} for r in righe[:5]]}


@mcp.tool()
async def tighten_speech(clip: str, min_silence: float = 0.5, pad: float = 0.12,
                         fillers: bool = True, extra_fillers: list[str] | None = None,
                         ripple: bool = True, model: str = "small",
                         language: str | None = None,
                         project: str | None = None) -> dict:
    """Stringe una clip parlata: via le pause lunghe e le esitazioni ("ehm", "uh").

    I tagli avvengono sulla timeline (split + rimozione), quindi si annullano con
    undo e il file originale non viene toccato. ``pad`` e' l'aria lasciata
    attorno alla voce: alzalo se il parlato risulta tagliato sull'attacco.

    extra_fillers aggiunge parole alla lista: usalo per "tipo", "cioe'",
    "allora", che di default NON vengono tolte perche' spesso sono parole vere.
    """
    s = _store(project)
    return await _off(cleanup.tighten, s, clip, min_silence, pad, fillers,
                      tuple(extra_fillers or ()), ripple, model, language)


@mcp.tool()
async def censor_speech(clip: str, words: list[str] | None = None,
                        mode: str = "mute", pad: float = 0.08,
                        model: str = "small", language: str | None = None,
                        project: str | None = None) -> dict:
    """Trova le parole da censurare nella clip e applica la censura audio.

    ``words`` si aggiunge alla lista predefinita. mode: mute (silenzio) oppure
    scramble (voce resa incomprensibile ma udibile). Ritorna gli intervalli
    trovati: se sono sbagliati, si rimuove l'effetto e si rifa con pad diverso.
    """
    s = _store(project)
    src = _source(None, clip, project)
    spans = await _off(analyze.censor_spans, src, tuple(words or ()), pad, model, language)
    if not spans:
        return {"trovati": 0, "intervalli": [], "effetto": None}
    # i tempi della trascrizione sono relativi al file: la clip parte da in_
    _, c = s.clip_or_die(clip)
    rel = [{"start": round(sp["start"] - c.in_, 3), "end": round(sp["end"] - c.in_, 3),
            "word": sp["word"]}
           for sp in spans
           if sp["end"] > c.in_ and sp["start"] < c.in_ + c.source_duration()]
    if not rel:
        return {"trovati": 0, "intervalli": [], "effetto": None,
                "nota": "parole trovate nel file ma fuori dal tratto usato dalla clip"}
    s.add_effect(clip, "censor", {"ranges": analyze.ranges_expr(rel), "mode": mode})
    _, c2 = s.clip_or_die(clip)
    return {"trovati": len(rel), "intervalli": rel,
            "effetto": {"type": "censor", "index": len(c2.effects) - 1, "mode": mode}}


# --------------------------------------------------------------------------
# preview e render
# --------------------------------------------------------------------------


@mcp.tool()
async def preview_frame(t: float | None = None, width: int = 640, path: str | None = None,
                        time: float | None = None, project: str | None = None) -> Image:
    """Renderizza il fotogramma della timeline al tempo ``t`` e lo restituisce.

    E' il modo per *vedere* il montaggio: posizione degli overlay, testo,
    correzione colore, inquadratura. Usa build_proxies per renderlo piu' rapido.

    ``time`` e' accettato come sinonimo di ``t``. Alza ``width`` a 1280 o 1920
    quando devi giudicare un dettaglio piccolo — la posizione di una maschera, un
    testo, il fuoco: a 640 px certe cose semplicemente non si vedono.
    """
    quando = t if t is not None else time
    if quando is None:
        raise EditError("serve t: il tempo in secondi sulla timeline")
    s = _store(project)
    out = path or str(Path(tempfile.gettempdir()) / f"vedit_preview_{os.getpid()}.jpg")
    p = await _off(render.render_frame, s.project, float(quando), out, width, True)
    return Image(path=p)


@mcp.tool()
async def detect_subjects(clip: str | None = None, path: str | None = None,
                          classes: list[str] | None = None, fps: float = 2.0,
                          conf: float = 0.35, project: str | None = None) -> dict:
    """Dove sta il soggetto, fotogramma per fotogramma (YOLO).

    Ritorna la traccia gia' levigata: posizione del centro nel tempo, copertura
    (in quanti fotogrammi il soggetto e' stato visto) e le classi trovate.
    Serve per mascherare un volto, tenere una persona al centro, evitare di
    coprirla col testo. classes vuoto = solo persone.
    """
    src = _source(path, clip, project)
    res = await _off(vision.follow, src, tuple(classes or ("person",)), fps, conf)
    return {"larghezza": res["larghezza"], "altezza": res["altezza"],
            "copertura": res["copertura"], "classi": res["classi"],
            "campioni": len(res["traccia"]),
            "traccia": [{"t": p["t"], "cx": p["cx"], "cy": p["cy"]}
                        for p in res["traccia"]]}


@mcp.tool()
async def auto_reframe(clip: str, classes: list[str] | None = None, fps: float = 2.0,
                       apply: bool = True, project: str | None = None) -> dict:
    """Tiene il soggetto al centro quando cambia il formato (16:9 -> 9:16).

    Imposta prima il progetto al formato voluto (project_settings preset
    'vertical'), poi chiama questo: calcola l'ingrandimento che copre il canvas e
    la panoramica che segue il soggetto, come keyframe sulla trasformazione.

    La panoramica e' limitata ai bordi dell'immagine, quindi non compare mai il
    vuoto ai lati.
    """
    s = _store(project)
    src = _source(None, clip, project)
    res = await _off(vision.follow, src, tuple(classes or ("person",)), fps)
    st = s.project.settings
    kf = vision.reframe_keyframes(res["traccia"], res["larghezza"], res["altezza"],
                                  st.width, st.height)
    if apply:
        s.set_transform(clip, scale=kf["scale"], x=kf["x"], y=kf["y"])
    return {"scale": kf["scale"], "copertura": res["copertura"],
            "punti": len(kf["x"]["kf"]), "limite_x": kf["limite_x"],
            "applicato": apply,
            "nota": "copertura bassa: il soggetto non e' stato visto spesso, "
                    "controlla con preview_grid" if res["copertura"] < 0.5 else None}


@mcp.tool()
async def track_mask(clip: str, kind: str = "mask_blur", padding: float = 1.25,
                     classes: list[str] | None = None, fps: float = 2.0,
                     project: str | None = None) -> dict:
    """Applica una maschera che segue il soggetto (volto, persona, targa).

    kind: mask_blur | mask_pixelate | mask_box. La maschera e' un riquadro con
    x/y animati sui keyframe del tracking, quindi resta addosso al soggetto
    invece di stare ferma.
    """
    if kind not in ("mask_blur", "mask_pixelate", "mask_box"):
        raise EditError("kind deve essere mask_blur | mask_pixelate | mask_box")
    s = _store(project)
    src = _source(None, clip, project)
    res = await _off(vision.follow, src, tuple(classes or ("person",)), fps)
    m = vision.mask_keyframes(res["traccia"], padding)
    s.add_effect(clip, kind, {"x": m["x"], "y": m["y"], "w": m["w"], "h": m["h"]})
    return {"effetto": kind, "w": m["w"], "h": m["h"],
            "punti": len(m["x"]["kf"]), "copertura": res["copertura"]}


@mcp.tool()
async def preview_grid(count: int = 12, width: int = 320, cols: int = 4,
                       start: float | None = None, end: float | None = None,
                       path: str | None = None, project: str | None = None) -> Image:
    """Griglia di fotogrammi della timeline: il montaggio si vede tutto insieme.

    Un solo fotogramma non dice niente sul ritmo. Qui ogni riquadro porta il suo
    tempo stampato sopra, quindi si leggono stacchi, continuita' e buchi in un
    colpo d'occhio. Usalo dopo ogni modifica strutturale, prima di renderizzare.
    """
    s = _store(project)
    out = path or str(Path(tempfile.gettempdir()) / f"vedit_grid_{os.getpid()}.jpg")
    res = await _off(review.contact_sheet, s.project, out, count, width, cols, start, end)
    return Image(path=res["file"])


@mcp.tool()
async def audio_waveform(start: float | None = None, end: float | None = None,
                         points: int = 120, project: str | None = None) -> dict:
    """Picchi audio del mix renderizzato in un intervallo, piu' i livelli.

    Serve a vedere dove sta davvero il suono: se un taglio cade in mezzo a una
    parola, se un tratto e' muto, se il livello e' troppo basso. I picchi sono
    0..1, i livelli in dBFS.
    """
    return await _off(review.waveform, _store(project).project, start, end, points)


@mcp.tool()
async def check_cuts(clip: str, model: str = "small", language: str | None = None,
                     project: str | None = None) -> dict:
    """Controlla che i bordi della clip non taglino a meta' una parola.

    Ritorna il punto suggerito per ogni bordo sbagliato: e' l'errore piu' comune
    del taglio automatico e si sente subito all'ascolto.
    """
    return await _off(review.cuts_on_speech, _store(project), clip, model, language)


@mcp.tool()
def marker(t: float, note: str = "", kind: str = "nota", duration: float = 0.0,
           project: str | None = None) -> dict:
    """Ancora una nota a un istante della timeline.

    kind: nota | da_fare | problema | approvato. duration > 0 marca una regione.
    E' la memoria del montaggio tra una sessione e l'altra: perche' un taglio
    sta li', cosa manca, dove qualcuno ha detto che non funziona.
    """
    return versions.add_marker(_store(project), t, note, kind, duration)


@mcp.tool()
def markers(kind: str | None = None, start: float | None = None,
            end: float | None = None, project: str | None = None) -> list[dict]:
    """I marker del progetto, filtrabili per tipo e per tratto."""
    return versions.markers(_store(project), kind, start, end)


@mcp.tool()
def remove_marker(marker_id: str, project: str | None = None) -> dict:
    """Toglie un marker."""
    return versions.remove_marker(_store(project), marker_id)


@mcp.tool()
def snapshot(name: str, note: str = "", project: str | None = None) -> dict:
    """Salva una versione nominata del montaggio, senza toccare quello corrente.

    Undo torna indietro; questo permette di tenere due montaggi diversi e
    sceglierli dopo averli confrontati.
    """
    return versions.snapshot(_store(project), name, note)


@mcp.tool()
def snapshots(project: str | None = None) -> list[dict]:
    """Le versioni salvate, dalla piu' recente."""
    return versions.snapshots(_store(project))


@mcp.tool()
def restore_snapshot(name: str, project: str | None = None) -> dict:
    """Riporta il progetto a una versione salvata. Si annulla con undo."""
    return versions.restore(_store(project), name)


@mcp.tool()
def compare_versions(a: str, b: str | None = None,
                     project: str | None = None) -> dict:
    """Cosa cambia tra due versioni (o tra una versione e il montaggio corrente).

    Dice quante clip sono state aggiunte, tolte o spostate e come cambia la
    durata: si sceglie leggendo, senza dover guardare due volte lo stesso video.
    """
    return versions.compare(_store(project), a, b)


@mcp.tool()
async def preview_clip(start: float | None = None, end: float | None = None,
                       height: int = 360, max_seconds: float = 30.0,
                       output: str | None = None, project: str | None = None) -> dict:
    """Renderizza un tratto breve e lascia il file: un'anteprima da guardare.

    preview_grid mostra la struttura, questo mostra il risultato. E' il modo per
    far dire a una persona "qui non funziona" invece di chiederle fiducia.
    Oltre max_seconds viene troncata: per il resto c'e' render_video.
    """
    return await _off(review.preview_clip, _store(project).project, output,
                      start, end, height, max_seconds)


@mcp.tool()
async def color_scopes(t: float, project: str | None = None) -> dict:
    """Misure del colore su un fotogramma: esposizione, clipping, dominante.

    Serve a giudicare il colore con dei numeri invece che a occhio su uno
    schermo non calibrato. Gli avvisi dicono cosa non va: sottoesposta, alte
    luci bruciate, dominante, immagine piatta.
    """
    return await _off(review.scopes, _store(project).project, t)


@mcp.tool()
def insert_clip(media: str, at: float, track: str | None = None,
                duration: float | None = None, in_point: float = 0.0,
                project: str | None = None) -> dict:
    """Inserisce una clip spingendo a destra tutto quello che segue.

    Se una clip sta a cavallo del punto di inserimento viene divisa. E'
    l'inserimento vero: add_clip invece appoggia e sovrappone.
    """
    return ops.insert_clip(_store(project), media, at, track, duration, in_point)


@mcp.tool()
def smooth_cuts(track: str | None = None, duration: float = 0.06,
                project: str | None = None) -> dict:
    """Micro-dissolvenza audio su ogni giunzione tra clip.

    Dopo un taglio netto sull'audio si sente un click: due o tre fotogrammi di
    sfumatura lo tolgono senza che si percepisca la dissolvenza. Da usare dopo
    tighten_speech o dopo qualunque serie di tagli.
    """
    return ops.smooth_cuts(_store(project), track, duration)


@mcp.tool()
async def duck_music(music: str, voice: str, amount_db: float = -12.0,
                     attack: float = 0.25, release: float = 0.6,
                     project: str | None = None) -> dict:
    """Abbassa la musica quando la voce parla (automazione del volume).

    Non e' un compressore sidechain: sono keyframe veri sul guadagno della clip
    musicale, quindi si vedono nel progetto, si correggono a mano e si annullano
    con undo. attack basso = stacco netto; release alto = rientro morbido.
    """
    return await _off(ops.duck_music, _store(project), music, voice,
                      amount_db, attack, release)


@mcp.tool()
def detach_audio(clip: str, track: str | None = None,
                 project: str | None = None) -> dict:
    """Porta l'audio della clip su una traccia separata e muta l'originale.

    Da qui audio e video si muovono indipendenti: e' il presupposto del J/L cut.
    """
    return ops.detach_audio(_store(project), clip, track)


@mcp.tool()
def jl_cut(clip: str, seconds: float = 0.5, kind: str = "J",
           project: str | None = None) -> dict:
    """J cut: l'audio entra prima dell'immagine. L cut: continua dopo lo stacco.

    E' la tecnica che rende invisibile il montaggio di un dialogo. Se l'audio
    non e' ancora scollegato viene scollegato in automatico; se manca materiale
    prima o dopo, lo dice invece di inventarselo.
    """
    return ops.jl_cut(_store(project), clip, seconds, kind)


@mcp.tool()
async def verify_edit(start: float | None = None, end: float | None = None,
                      height: int = 270, project: str | None = None) -> dict:
    """Renderizza davvero un tratto e verifica che sia quello che la timeline dice.

    Confronta gli stacchi attesi con quelli misurati sul file renderizzato, la
    durata, i tratti neri o muti. E' la differenza tra "credo di aver montato" e
    "ho verificato": usalo prima di consegnare un render lungo.
    """
    return await _off(review.verify, _store(project).project, start, end, height)


@mcp.tool()
async def render_video(output: str, quality: str = "high", codec: str = "h264",
                       start: float | None = None, end: float | None = None,
                       preview: bool = False, bitrate: str | None = None,
                       project: str | None = None) -> dict:
    """Renderizza il progetto in un file.

    quality: draft (velocissimo, per controllare) | medium | high | max.
    codec: h264 (compatibile) | hevc | av1 | vp9. Usa l'accelerazione GPU se c'e'.
    preview=True rende a 960px con i proxy: utile per una verifica rapida.
    start/end limitano la porzione di timeline da rendere.
    L'estensione decide il contenitore: .mp4 .mov .mkv .webm .gif .mp3 .wav .m4a.
    """
    s = _store(project)
    opts = render.RenderOptions(
        output=output, quality="draft" if preview else quality, codec=codec,
        start=start, end=end, bitrate=bitrate,
        width=960 if preview else None, use_proxy=preview,
    )
    res = await _off(render.render, s.project, opts)
    return {"output": res.output, "durata": res.duration, "secondi_impiegati": res.seconds,
            "encoder": res.encoder, "mb": round(res.size / 1e6, 2), "avvisi": res.warnings}


@mcp.tool()
async def system_info() -> dict:
    """Versione di ffmpeg, encoder hardware disponibili, cartella di cache."""
    info = await _off(hw.detect)
    return {"ffmpeg": ffmpeg.version(), "encoder": info.encoders,
            "hardware_verificato": info.working,
            "cache": str(proxy.cache_dir())}


@mcp.tool()
async def clear_cache(kind: str | None = None) -> dict:
    """Svuota la cache di proxy/miniature/stabilizzazione."""
    freed = await _off(proxy.clear, kind)
    return {"liberati_mb": round(freed / 1e6, 2)}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
