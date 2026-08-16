"""Modello dati della timeline.

Un progetto e' un documento JSON puro: nessuno stato nascosto, tutto
serializzabile. Il render e' una funzione pura del documento, quindi lo stesso
progetto produce sempre lo stesso file di output.

Ogni parametro numerico marcato "animabile" accetta sia uno scalare
(``0.5``) sia un blocco keyframe (``{"kf": [{"t": 0, "v": 0}, {"t": 1, "v": 1}]}``).
Vedi ``keyframes.py`` per la compilazione in espressioni ffmpeg.
"""

from __future__ import annotations

import uuid
import types
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Union, get_args, get_origin, get_type_hints

# Uno scalare oppure {"kf": [...]}.
Value = Any

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".ts"}
AUDIO_EXTS = {".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg", ".opus", ".wma", ".aiff"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------
# (de)serializzazione generica dei dataclass
# --------------------------------------------------------------------------

# Alias campo python -> chiave JSON (per keyword riservate come "in").
_ALIASES = {"in_": "in"}


def _json_key(name: str) -> str:
    return _ALIASES.get(name, name)


def to_dict(obj: Any) -> Any:
    if is_dataclass(obj):
        out = {}
        for f in fields(obj):
            out[_json_key(f.name)] = to_dict(getattr(obj, f.name))
        return out
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def _unwrap_optional(ftype: Any) -> Any:
    """``TextStyle | None`` -> ``TextStyle``; lascia intatto il resto."""
    if get_origin(ftype) in (Union, types.UnionType):
        args = [a for a in get_args(ftype) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ftype


def from_dict(cls: type, data: Any) -> Any:
    """Costruisce un dataclass da dict ignorando le chiavi sconosciute.

    Tollerante in avanti: un progetto salvato da una versione futura si apre
    comunque, perdendo solo i campi che non conosciamo.
    """
    if not is_dataclass(cls):
        return data
    if data is None:
        return cls()
    hints = get_type_hints(cls)
    kwargs = {}
    for f in fields(cls):
        key = _json_key(f.name)
        if key not in data:
            continue
        raw = data[key]
        ftype = _unwrap_optional(hints[f.name])
        origin = get_origin(ftype)
        if origin is list:
            (item_type,) = get_args(ftype) or (Any,)
            kwargs[f.name] = [from_dict(item_type, v) for v in (raw or [])]
        elif is_dataclass(ftype) and isinstance(raw, dict):
            kwargs[f.name] = from_dict(ftype, raw)
        else:
            kwargs[f.name] = raw
    return cls(**kwargs)


# --------------------------------------------------------------------------
# strutture
# --------------------------------------------------------------------------


@dataclass
class Settings:
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    sample_rate: int = 48000
    background: str = "black"  # colore o "#rrggbb"


@dataclass
class Media:
    """Un file sorgente importato, con i metadati letti da ffprobe."""

    id: str = field(default_factory=lambda: new_id("m"))
    path: str = ""
    kind: str = "video"  # video | audio | image
    duration: float = 0.0  # 0 per le immagini (durata illimitata)
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = True
    has_audio: bool = False
    sample_rate: int = 0
    channels: int = 0
    proxy: str | None = None  # path del proxy a bassa risoluzione, se generato
    name: str = ""
    folder: str = ""  # cartella nel media bin, es. "b-roll/interviste"


@dataclass
class Transform:
    """Posizione sul canvas. x/y sono offset in pixel dal centro."""

    x: Value = 0.0
    y: Value = 0.0
    scale: Value = 1.0
    rotation: Value = 0.0  # gradi, senso orario
    opacity: Value = 1.0  # 0..1


@dataclass
class ClipAudio:
    gain_db: Value = 0.0
    mute: bool = False
    fade_in: float = 0.0
    fade_out: float = 0.0
    pan: Value = 0.0  # -1 sinistra, +1 destra


@dataclass
class Effect:
    """Effetto applicato a una clip o al master. ``type`` indicizza EFFECTS."""

    type: str = ""
    params: dict = field(default_factory=dict)
    enabled: bool = True


@dataclass
class TextStyle:
    text: str = ""
    font_file: str | None = None
    font_size: int = 64
    color: str = "white"
    align: str = "center"  # left | center | right
    line_spacing: int = 8
    box: bool = False
    box_color: str = "black"
    box_opacity: float = 0.5
    box_padding: int = 20
    border_width: int = 0
    border_color: str = "black"
    shadow_x: int = 0
    shadow_y: int = 0
    shadow_color: str = "black"


TRANSITIONS = (
    "dissolve",     # dissolvenza incrociata
    "wipe_right",   # tendina: il bordo attraversa da sinistra a destra
    "wipe_left",
    "wipe_down",
    "wipe_up",
    "slide_left",   # la clip uscente scorre via e scopre quella sotto
    "slide_right",
    "slide_up",
    "slide_down",
    "iris",         # cerchio che si chiude al centro
)


@dataclass
class Transition:
    """Transizione in uscita: consuma la coda della clip e scopre quella sotto."""

    type: str = "dissolve"
    duration: float = 0.0


@dataclass
class Clip:
    id: str = field(default_factory=lambda: new_id("c"))
    type: str = "media"  # media | text | color
    media: str | None = None  # id del Media, per type=media
    start: float = 0.0  # posizione in timeline (s)
    in_: float = 0.0  # punto di attacco nella sorgente (s)
    duration: float = 1.0  # durata in timeline (s), gia' scalata dalla velocita'
    speed: float = 1.0
    reverse: bool = False
    fit: str = "contain"  # contain | cover | stretch | none
    enabled: bool = True
    name: str = ""

    transform: Transform = field(default_factory=Transform)
    audio: ClipAudio = field(default_factory=ClipAudio)
    effects: list[Effect] = field(default_factory=list)

    fade_in: float = 0.0  # dissolvenza video in ingresso (s)
    fade_out: float = 0.0
    transition_out: Transition = field(default_factory=Transition)

    text: TextStyle | None = None  # per type=text
    color: str = "black"  # per type=color

    @property
    def end(self) -> float:
        return self.start + self.duration

    def source_duration(self) -> float:
        """Quanto materiale sorgente consuma la clip (prima dello speed)."""
        return self.duration * abs(self.speed or 1.0)


@dataclass
class Track:
    id: str = field(default_factory=lambda: new_id("t"))
    kind: str = "video"  # video | audio
    name: str = ""
    clips: list[Clip] = field(default_factory=list)
    hidden: bool = False
    muted: bool = False
    volume: Value = 1.0
    locked: bool = False
    # con almeno una traccia in solo, le altre dello stesso tipo tacciono/spariscono
    solo: bool = False


@dataclass
class Loudnorm:
    """Normalizzazione EBU R128 sul master."""

    enabled: bool = False
    i: float = -14.0  # LUFS target (-14 = streaming, -23 = broadcast EBU)
    tp: float = -1.0  # true peak max dBTP
    lra: float = 11.0
    measured: dict | None = None  # cache misure del primo passaggio


@dataclass
class Master:
    loudnorm: Loudnorm = field(default_factory=Loudnorm)
    effects: list[Effect] = field(default_factory=list)
    volume: Value = 1.0


@dataclass
class Marker:
    """Una nota ancorata a un istante della timeline.

    E' la memoria del montaggio: perche' un taglio sta li', cosa manca ancora,
    dove il committente ha detto che non funziona. Senza, ogni sessione
    ricomincia da zero.
    """

    id: str = field(default_factory=lambda: new_id("mk"))
    t: float = 0.0
    duration: float = 0.0          # >0 = regione, 0 = punto
    note: str = ""
    kind: str = "nota"             # nota | da_fare | problema | approvato
    color: str = "#FFC107"


@dataclass
class Project:
    version: int = 1
    name: str = "untitled"
    settings: Settings = field(default_factory=Settings)
    media: list[Media] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    master: Master = field(default_factory=Master)
    markers: list[Marker] = field(default_factory=list)

    # ---- lookup -------------------------------------------------------
    def media_by_id(self, mid: str) -> Media | None:
        return next((m for m in self.media if m.id == mid), None)

    def media_by_path(self, path: str) -> Media | None:
        return next((m for m in self.media if m.path == path), None)

    def track_by_id(self, tid: str) -> Track | None:
        return next((t for t in self.tracks if t.id == tid), None)

    def find_clip(self, cid: str) -> tuple[Track, Clip] | None:
        for t in self.tracks:
            for c in t.clips:
                if c.id == cid:
                    return t, c
        return None

    def clip(self, cid: str) -> Clip:
        found = self.find_clip(cid)
        if not found:
            raise KeyError(f"clip {cid!r} inesistente")
        return found[1]

    def video_tracks(self) -> list[Track]:
        """Dal basso verso l'alto: l'ordine della lista e' lo z-order."""
        return [t for t in self.tracks if t.kind == "video"]

    def audio_tracks(self) -> list[Track]:
        return [t for t in self.tracks if t.kind == "audio"]

    def live_tracks(self, kind: str) -> list[Track]:
        """Tracce che finiscono davvero nel render, nell'ordine di sovrapposizione.

        Il solo vince sul resto: se almeno una traccia dello stesso tipo e' in
        solo, le altre non entrano nemmeno se non sono nascoste o silenziate.
        """
        same = self.video_tracks() if kind == "video" else self.audio_tracks()
        off = "hidden" if kind == "video" else "muted"
        solo = [t for t in same if t.solo]
        return [t for t in (solo or same) if not getattr(t, off)]

    def duration(self) -> float:
        end = 0.0
        for t in self.tracks:
            for c in t.clips:
                if c.enabled:
                    end = max(end, c.end)
        return round(end, 6)

    # ---- serializzazione ----------------------------------------------
    def to_dict(self) -> dict:
        return to_dict(self)

    @staticmethod
    def from_obj(data: dict) -> "Project":
        return from_dict(Project, data)
