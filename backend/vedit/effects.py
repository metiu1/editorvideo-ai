"""Registro degli effetti: dichiarazione parametri + costruzione filtri ffmpeg.

Ogni effetto e' una funzione pura ``(params, ctx) -> [stringhe filtro]``.
I parametri marcati ``anim=True`` accettano keyframe, perche' il filtro ffmpeg
corrispondente rivaluta l'espressione a ogni frame; gli altri vengono
campionati a t=0.

Aggiungere un effetto = aggiungere una voce a EFFECTS. Il server MCP e la UI
si auto-descrivono da questo registro, non serve toccare altro.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from . import keyframes as kf


@dataclass
class Ctx:
    """Contesto di compilazione di una catena di effetti."""

    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    sample_rate: int = 48000
    tvar: str = "t"  # espressione del tempo locale alla clip
    duration: float = 0.0
    # rapporto tra risoluzione di render e risoluzione del progetto: in preview
    # vale <1 e i parametri espressi in pixel vanno riscalati di conseguenza
    scale: float = 1.0
    extra: dict = field(default_factory=dict)  # es. file .trf per la stabilizzazione
    _counter: list = field(default_factory=lambda: [0])

    def uid(self, prefix: str) -> str:
        """Etichetta univoca per gli effetti che aprono sotto-grafi."""
        self._counter[0] += 1
        return f"{prefix}{self._counter[0]}"


@dataclass
class Param:
    name: str
    default: Any = 0.0
    kind: str = "number"  # number | bool | string | color | file | enum
    min: float | None = None
    max: float | None = None
    anim: bool = False
    choices: tuple[str, ...] = ()
    desc: str = ""


@dataclass
class EffectDef:
    name: str
    kind: str  # video | audio
    label: str
    params: tuple[Param, ...]
    build: Callable[[dict, Ctx], list[str]]
    desc: str = ""

    def param(self, name: str) -> Param | None:
        return next((p for p in self.params if p.name == name), None)


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------


def esc_str(s: str) -> str:
    """Escape di un valore stringa dentro un argomento di filtro."""
    return (
        str(s)
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


def esc_path(p: str) -> str:
    """Path Windows dentro un filtro: slash avanti e due punti protetti."""
    return str(p).replace("\\", "/").replace(":", "\\:")


def quoted(expr: str) -> str:
    """Espressione come argomento di filtro (virgole/duepunti al sicuro)."""
    return "'" + str(expr).replace("'", "") + "'"


def _spec(effect: str) -> EffectDef:
    if effect not in EFFECTS:
        raise KeyError(f"effetto sconosciuto: {effect!r}")
    return EFFECTS[effect]


def val(params: dict, name: str, default: Any = 0.0, t: float = 0.0) -> Any:
    """Valore statico (keyframe campionati a ``t``)."""
    v = params.get(name, default)
    if kf.is_kf(v):
        return kf.sample(v, t)
    return v


def num(params: dict, name: str, default: float = 0.0) -> float:
    try:
        return float(val(params, name, default))
    except (TypeError, ValueError):
        return float(default)


def anim(params: dict, name: str, default: float, ctx: Ctx) -> str:
    """Espressione animabile (gia' pronta per essere messa tra apici)."""
    return kf.expr(params.get(name, default), ctx.tvar, default)


def flag(params: dict, name: str, default: bool = False) -> bool:
    v = params.get(name, default)
    return bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on")


def fnum(x: float) -> str:
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return s or "0"


# --------------------------------------------------------------------------
# effetti video
# --------------------------------------------------------------------------


def _f_color(p: dict, c: Ctx) -> list[str]:
    args = [
        f"brightness={quoted(anim(p, 'brightness', 0.0, c))}",
        f"contrast={quoted(anim(p, 'contrast', 1.0, c))}",
        f"saturation={quoted(anim(p, 'saturation', 1.0, c))}",
        f"gamma={quoted(anim(p, 'gamma', 1.0, c))}",
        "eval=frame",
    ]
    return ["eq=" + ":".join(args)]


def _f_colorbalance(p: dict, c: Ctx) -> list[str]:
    keys = ("rs", "gs", "bs", "rm", "gm", "bm", "rh", "gh", "bh")
    args = [f"{k}={fnum(num(p, k, 0.0))}" for k in keys]
    return ["colorbalance=" + ":".join(args)]


def _f_temperature(p: dict, c: Ctx) -> list[str]:
    return [f"colortemperature=temperature={fnum(num(p, 'temperature', 6500))}:mix={fnum(num(p, 'mix', 1.0))}"]


def _f_curves(p: dict, c: Ctx) -> list[str]:
    preset = str(val(p, "preset", "none"))
    if preset and preset != "none":
        return [f"curves=preset={preset}"]
    master = str(val(p, "master", "")).strip()
    return [f"curves=master={quoted(master)}"] if master else []


def _f_lut(p: dict, c: Ctx) -> list[str]:
    path = str(val(p, "file", "")).strip()
    if not path:
        return []
    return [f"lut3d=file='{esc_path(path)}':interp={val(p, 'interp', 'tetrahedral')}"]


def _f_colormatch(p: dict, c: Ctx) -> list[str]:
    """Guadagno e offset per canale: la correzione lineare del color transfer.

    Si usa ``lutrgb`` con un'espressione invece di ``colorlevels`` perche'
    quest'ultimo accetta punti di uscita solo tra 0 e 1: un guadagno sotto 1 o
    un offset negativo non sarebbero rappresentabili.
    """
    args = []
    for ch in "rgb":
        gain = fnum(num(p, f"{ch}_gain", 1.0))
        off = num(p, f"{ch}_off", 0.0) * 255.0
        segno = "+" if off >= 0 else "-"
        args.append(f"{ch}='clip(val*{gain}{segno}{fnum(abs(off))},0,255)'")
    return ["lutrgb=" + ":".join(args)]


def _f_blur(p: dict, c: Ctx) -> list[str]:
    return [f"gblur=sigma={fnum(num(p, 'sigma', 8) * c.scale)}:steps={int(num(p, 'steps', 1))}"]


def _f_sharpen(p: dict, c: Ctx) -> list[str]:
    a = fnum(num(p, "amount", 1.0))
    return [f"unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount={a}:chroma_amount={fnum(num(p, 'chroma', 0.0))}"]


def _f_glow(p: dict, c: Ctx) -> list[str]:
    """Sotto-grafo: split -> ramo sfocato -> blend screen.

    Restituisce un blocco con ``;`` interni: resta valido perche' il primo
    filtro riceve dalla virgola precedente e l'ultimo non ha etichetta di
    uscita, quindi la catena prosegue normalmente.
    """
    sigma = fnum(num(p, "sigma", 12) * c.scale)
    amount = fnum(num(p, "amount", 0.5))
    a, b, bb = c.uid("glwa"), c.uid("glwb"), c.uid("glwc")
    return [
        f"split[{a}][{b}];[{b}]gblur=sigma={sigma}[{bb}];"
        f"[{a}][{bb}]blend=all_mode=screen:all_opacity={amount}"
    ]


def _f_vignette(p: dict, c: Ctx) -> list[str]:
    angle = fnum(num(p, "angle", 0.8))
    return [f"vignette=angle={angle}:mode={val(p, 'mode', 'forward')}"]


def _f_grain(p: dict, c: Ctx) -> list[str]:
    return [f"noise=alls={int(num(p, 'strength', 12))}:allf=t+u"]


def _f_denoise(p: dict, c: Ctx) -> list[str]:
    s = num(p, "strength", 4)
    return [f"hqdn3d={fnum(s)}:{fnum(s * 0.75)}:{fnum(s * 1.5)}:{fnum(s * 1.5)}"]


def _f_chromakey(p: dict, c: Ctx) -> list[str]:
    color = str(val(p, "color", "green"))
    out = [
        "format=yuva420p",
        f"chromakey=color={esc_str(color)}:similarity={fnum(num(p, 'similarity', 0.20))}"
        f":blend={fnum(num(p, 'blend', 0.05))}",
    ]
    if flag(p, "despill", True):
        out.append(f"chromanr=thres={fnum(num(p, 'despill_amount', 20))}")
    return out


def _f_crop(p: dict, c: Ctx) -> list[str]:
    """Ritaglia e riporta al canvas (zona tagliata trasparente)."""
    w = int(num(p, "w", c.width) * c.scale)
    h = int(num(p, "h", c.height) * c.scale)
    x = int(num(p, "x", 0) * c.scale)
    y = int(num(p, "y", 0) * c.scale)
    w = max(2, min(w, c.width))
    h = max(2, min(h, c.height))
    return [
        f"crop={w}:{h}:{x}:{y}",
        "format=yuva420p",
        f"pad={c.width}:{c.height}:{x}:{y}:color=black@0",
    ]


def _f_pixelate(p: dict, c: Ctx) -> list[str]:
    n = max(2, int(num(p, "size", 16) * c.scale))
    return [
        f"scale=iw/{n}:ih/{n}:flags=neighbor",
        f"scale={c.width}:{c.height}:flags=neighbor",
    ]


def parse_ranges(s: Any) -> list[tuple[float, float]]:
    """``"1.2-1.8;4-4.5"`` -> [(1.2, 1.8), (4.0, 4.5)]. Ordinati e senza vuoti."""
    out: list[tuple[float, float]] = []
    for chunk in str(s or "").replace(",", ";").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        a, _, b = chunk.partition("-")
        try:
            t0, t1 = float(a), float(b)
        except ValueError:
            continue
        if t1 > t0:
            out.append((t0, t1))
    return sorted(out)


def enable_expr(p: dict, c: Ctx) -> str:
    """``:enable='...'`` per gli intervalli dichiarati, stringa vuota se sempre."""
    r = parse_ranges(val(p, "ranges", ""))
    if not r:
        return ""
    cond = "+".join(f"between({c.tvar},{fnum(a)},{fnum(b)})" for a, b in r)
    return f":enable='{cond}'"


def _px(expr: str, c: Ctx) -> str:
    """Espressione in pixel di progetto -> pixel di render (preview ridotta)."""
    return expr if abs(c.scale - 1.0) < 1e-6 else f"(({expr})*{fnum(c.scale)})"


def _box(p: dict, c: Ctx) -> tuple[int, int, str, str]:
    """Rettangolo della maschera, sempre dentro il fotogramma.

    Il ritaglio non puo' eccedere il canvas (ffmpeg rifiuta un crop piu' grande
    dell'ingresso) e nemmeno uscirne muovendosi: x/y sono animabili, quindi il
    limite va messo nell'espressione, non nel valore.
    """
    w = max(2, min(int(num(p, "w", 300) * c.scale) // 2 * 2, c.width))
    h = max(2, min(int(num(p, "h", 300) * c.scale) // 2 * 2, c.height))
    x = f"min(max({_px(anim(p, 'x', 0, c), c)},0),{c.width - w})"
    y = f"min(max({_px(anim(p, 'y', 0, c), c)},0),{c.height - h})"
    return w, h, x, y


def _f_mask_blur(p: dict, c: Ctx) -> list[str]:
    """Sfoca solo un rettangolo: volto, targa, schermo, documento.

    x/y sono animabili, quindi la maschera segue il soggetto con i keyframe.
    """
    w, h, x, y = _box(p, c)
    sigma = fnum(max(0.1, num(p, "sigma", 20) * c.scale))
    a, b, m = c.uid("mka"), c.uid("mkb"), c.uid("mkm")
    return [
        f"split[{a}][{b}];"
        f"[{b}]crop=w={w}:h={h}:x='{x}':y='{y}',gblur=sigma={sigma}:steps=2[{m}];"
        f"[{a}][{m}]overlay=x='{x}':y='{y}'{enable_expr(p, c)}"
    ]


def _f_mask_pixelate(p: dict, c: Ctx) -> list[str]:
    """Come mask_blur ma a mosaico: censura riconoscibile come tale."""
    w, h, x, y = _box(p, c)
    n = max(2, int(num(p, "size", 16) * c.scale))
    a, b, m = c.uid("mpa"), c.uid("mpb"), c.uid("mpm")
    return [
        f"split[{a}][{b}];"
        f"[{b}]crop=w={w}:h={h}:x='{x}':y='{y}',"
        f"scale=iw/{n}:ih/{n}:flags=neighbor,scale={w}:{h}:flags=neighbor[{m}];"
        f"[{a}][{m}]overlay=x='{x}':y='{y}'{enable_expr(p, c)}"
    ]


def _f_mask_box(p: dict, c: Ctx) -> list[str]:
    """Rettangolo pieno: la censura piu' netta, o una barra grafica."""
    w, h, x, y = _box(p, c)
    color = esc_str(str(val(p, "color", "black")))
    alpha = fnum(max(0.0, min(1.0, num(p, "opacity", 1.0))))
    return [
        f"drawbox=x='{x}':y='{y}':w={w}:h={h}:color={color}@{alpha}:t=fill"
        + enable_expr(p, c)
    ]


def _f_subtitles(p: dict, c: Ctx) -> list[str]:
    """Imprime un file di sottotitoli (.ass, .srt, .vtt) nell'immagine.

    Con .ass lo stile e il karaoke arrivano dal file; con .srt si puo' forzare
    l'aspetto con ``force_style``. I tempi del file sono relativi alla clip.
    """
    path = str(val(p, "file", "")).strip()
    if not path:
        return []
    args = [f"filename='{esc_path(path)}'"]
    forza = str(val(p, "force_style", "")).strip()
    if forza:
        args.append(f"force_style='{esc_str(forza)}'")
    if abs(c.scale - 1.0) > 1e-6:
        # in preview il fotogramma e' piu' piccolo: senza questo i sottotitoli
        # verrebbero disegnati alla dimensione del progetto e uscirebbero
        args.append(f"original_size={int(c.width / c.scale)}x{int(c.height / c.scale)}")
    return ["subtitles=" + ":".join(args)]


def _f_mirror(p: dict, c: Ctx) -> list[str]:
    out = []
    if flag(p, "horizontal", True):
        out.append("hflip")
    if flag(p, "vertical", False):
        out.append("vflip")
    return out


def _f_stabilize(p: dict, c: Ctx) -> list[str]:
    """Usa il file .trf se l'analisi e' gia' stata fatta, altrimenti deshake."""
    trf = c.extra.get("trf")
    if trf:
        return [
            f"vidstabtransform=input='{esc_path(trf)}':smoothing={int(num(p, 'smoothing', 15))}"
            f":zoom={fnum(num(p, 'zoom', 0))}:optzoom=1:interpol=bilinear",
            "unsharp=5:5:0.8:3:3:0.4",
        ]
    return ["deshake=rx=32:ry=32:edge=mirror"]


def _f_fps_blend(p: dict, c: Ctx) -> list[str]:
    """Motion blur/interpolazione per slow motion morbido."""
    mode = str(val(p, "mode", "blend"))
    if mode == "interpolate":
        return [f"minterpolate=fps={fnum(c.fps)}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"]
    return [f"tmix=frames={int(num(p, 'frames', 3))}:weights='1 1 1'"]


# --------------------------------------------------------------------------
# effetti audio
# --------------------------------------------------------------------------


def _a_eq3(p: dict, c: Ctx) -> list[str]:
    return [
        f"bass=g={fnum(num(p, 'bass', 0))}:f=110",
        f"equalizer=f=1000:width_type=o:width=2:g={fnum(num(p, 'mid', 0))}",
        f"treble=g={fnum(num(p, 'treble', 0))}:f=8000",
    ]


def _a_compressor(p: dict, c: Ctx) -> list[str]:
    return [
        f"acompressor=threshold={fnum(num(p, 'threshold', -18))}dB:ratio={fnum(num(p, 'ratio', 3))}"
        f":attack={fnum(num(p, 'attack', 20))}:release={fnum(num(p, 'release', 250))}"
        f":makeup={fnum(num(p, 'makeup', 1))}"
    ]


def _a_limiter(p: dict, c: Ctx) -> list[str]:
    return [f"alimiter=limit={fnum(num(p, 'limit', 0.95))}:level=false"]


def _a_denoise(p: dict, c: Ctx) -> list[str]:
    return [f"afftdn=nr={fnum(num(p, 'reduction', 12))}:nf={fnum(num(p, 'floor', -40))}:tn=1"]


def _a_highpass(p: dict, c: Ctx) -> list[str]:
    return [f"highpass=f={fnum(num(p, 'freq', 80))}:poles=2"]


def _a_lowpass(p: dict, c: Ctx) -> list[str]:
    return [f"lowpass=f={fnum(num(p, 'freq', 16000))}:poles=2"]


def _a_echo(p: dict, c: Ctx) -> list[str]:
    d = int(num(p, "delay_ms", 300))
    dec = fnum(num(p, "decay", 0.4))
    return [f"aecho=0.8:0.85:{d}:{dec}"]


def _a_reverb(p: dict, c: Ctx) -> list[str]:
    amount = max(0.05, min(0.9, num(p, "amount", 0.3)))
    size = max(0.1, min(1.0, num(p, "size", 0.5)))
    d1 = int(30 + 90 * size)
    return [f"aecho=0.8:0.9:{d1}|{d1 * 2}|{d1 * 3}:{fnum(amount)}|{fnum(amount * 0.6)}|{fnum(amount * 0.35)}"]


def _a_pitch(p: dict, c: Ctx) -> list[str]:
    semitones = num(p, "semitones", 0)
    if abs(semitones) < 1e-6:
        return []
    return [f"rubberband=pitch={fnum(2 ** (semitones / 12.0))}"]


def _a_gate(p: dict, c: Ctx) -> list[str]:
    return [
        f"agate=threshold={fnum(num(p, 'threshold', 0.02))}:ratio={fnum(num(p, 'ratio', 4))}"
        f":attack={fnum(num(p, 'attack', 20))}:release={fnum(num(p, 'release', 250))}"
    ]


def _a_censor(p: dict, c: Ctx) -> list[str]:
    """Copre intervalli di parlato: muto o voce resa incomprensibile.

    Gli intervalli arrivano da ``analyze.censor_spans``, che li ricava dai
    timestamp per parola della trascrizione.
    """
    en = enable_expr(p, c)
    if not en:
        return []
    if str(val(p, "mode", "mute")) == "scramble":
        shift = fnum(num(p, "shift", 400))
        return [f"afreqshift=shift={shift}{en}"]
    return [f"volume=volume=0{en}"]


def _a_dynnorm(p: dict, c: Ctx) -> list[str]:
    return [f"dynaudnorm=f={int(num(p, 'frame_ms', 200))}:g={int(num(p, 'gauss', 15))}:p={fnum(num(p, 'peak', 0.9))}"]


# --------------------------------------------------------------------------
# registro
# --------------------------------------------------------------------------

_DEFS: tuple[EffectDef, ...] = (
    EffectDef(
        "color", "video", "Correzione colore",
        (
            Param("brightness", 0.0, min=-1, max=1, anim=True, desc="-1..1"),
            Param("contrast", 1.0, min=0, max=4, anim=True),
            Param("saturation", 1.0, min=0, max=3, anim=True, desc="0 = bianco e nero"),
            Param("gamma", 1.0, min=0.1, max=10, anim=True),
        ),
        _f_color, "Luminosita', contrasto, saturazione, gamma. Tutti animabili.",
    ),
    EffectDef(
        "colorbalance", "video", "Bilanciamento colore",
        tuple(Param(k, 0.0, min=-1, max=1) for k in ("rs", "gs", "bs", "rm", "gm", "bm", "rh", "gh", "bh")),
        _f_colorbalance, "Ombre (s), mezzitoni (m), alte luci (h) per canale RGB.",
    ),
    EffectDef(
        "temperature", "video", "Temperatura colore",
        (Param("temperature", 6500, min=1000, max=40000), Param("mix", 1.0, min=0, max=1)),
        _f_temperature, "Kelvin: sotto 6500 raffredda, sopra scalda.",
    ),
    EffectDef(
        "curves", "video", "Curve",
        (
            Param("preset", "none", kind="enum",
                  choices=("none", "color_negative", "cross_process", "darker", "increase_contrast",
                           "lighter", "linear_contrast", "medium_contrast", "negative",
                           "strong_contrast", "vintage")),
            Param("master", "", kind="string", desc="punti 'x0/y0 x1/y1' se preset=none"),
        ),
        _f_curves,
    ),
    EffectDef(
        "lut", "video", "LUT 3D",
        (Param("file", "", kind="file", desc="file .cube"),
         Param("interp", "tetrahedral", kind="enum", choices=("nearest", "trilinear", "tetrahedral"))),
        _f_lut, "Applica una look-up table .cube.",
    ),
    EffectDef(
        "colormatch", "video", "Uniforma colore",
        tuple(Param(f"{ch}_{k}", 1.0 if k == "gain" else 0.0, min=-1, max=3)
              for ch in ("r", "g", "b") for k in ("gain", "off")),
        _f_colormatch,
        "Guadagno e offset per canale. Non si impostano a mano: li calcola "
        "match_color confrontando la clip con quella di riferimento.",
    ),
    EffectDef(
        "blur", "video", "Sfocatura",
        (Param("sigma", 8, min=0, max=100), Param("steps", 1, min=1, max=6)),
        _f_blur,
    ),
    EffectDef(
        "sharpen", "video", "Nitidezza",
        (Param("amount", 1.0, min=-2, max=5), Param("chroma", 0.0, min=-2, max=2)),
        _f_sharpen,
    ),
    EffectDef(
        "glow", "video", "Glow",
        (Param("sigma", 12, min=1, max=60), Param("amount", 0.5, min=0, max=1)),
        _f_glow, "Bagliore morbido sulle alte luci.",
    ),
    EffectDef(
        "vignette", "video", "Vignettatura",
        (Param("angle", 0.8, min=0, max=1.57),
         Param("mode", "forward", kind="enum", choices=("forward", "backward"))),
        _f_vignette,
    ),
    EffectDef("grain", "video", "Grana", (Param("strength", 12, min=0, max=100),), _f_grain),
    EffectDef("denoise", "video", "Riduzione rumore", (Param("strength", 4, min=0, max=20),), _f_denoise),
    EffectDef(
        "chromakey", "video", "Chroma key",
        (
            Param("color", "green", kind="color"),
            Param("similarity", 0.20, min=0.01, max=1),
            Param("blend", 0.05, min=0, max=1),
            Param("despill", True, kind="bool"),
            Param("despill_amount", 20, min=0, max=100),
        ),
        _f_chromakey, "Rimuove il fondale verde/blu rendendolo trasparente.",
    ),
    EffectDef(
        "crop", "video", "Ritaglio",
        (Param("w", 1920), Param("h", 1080), Param("x", 0), Param("y", 0)),
        _f_crop, "Ritaglia un rettangolo, il resto diventa trasparente.",
    ),
    EffectDef("pixelate", "video", "Pixel", (Param("size", 16, min=2, max=200),), _f_pixelate),
    EffectDef(
        "mask_blur", "video", "Maschera sfocata",
        (
            Param("x", 0, anim=True, desc="px, angolo in alto a sinistra"),
            Param("y", 0, anim=True),
            Param("w", 300, min=2), Param("h", 300, min=2),
            Param("sigma", 20, min=1, max=100),
            Param("ranges", "", kind="string", desc="'1.2-1.8;4-4.5' = solo in quegli istanti"),
        ),
        _f_mask_blur,
        "Sfoca solo un rettangolo (volto, targa, schermo). x/y animabili: con i "
        "keyframe la maschera segue il soggetto. ranges vuoto = sempre attiva.",
    ),
    EffectDef(
        "mask_pixelate", "video", "Maschera a mosaico",
        (
            Param("x", 0, anim=True), Param("y", 0, anim=True),
            Param("w", 300, min=2), Param("h", 300, min=2),
            Param("size", 16, min=2, max=200),
            Param("ranges", "", kind="string"),
        ),
        _f_mask_pixelate, "Come mask_blur ma a mosaico: censura evidente.",
    ),
    EffectDef(
        "mask_box", "video", "Barra piena",
        (
            Param("x", 0, anim=True), Param("y", 0, anim=True),
            Param("w", 300, min=2), Param("h", 120, min=2),
            Param("color", "black", kind="color"),
            Param("opacity", 1.0, min=0, max=1),
            Param("ranges", "", kind="string"),
        ),
        _f_mask_box, "Rettangolo pieno: censura netta o barra grafica.",
    ),
    EffectDef(
        "subtitles", "video", "Sottotitoli",
        (Param("file", "", kind="file", desc="file .ass (karaoke) o .srt"),
         Param("force_style", "", kind="string",
               desc="solo per .srt, es. 'Fontsize=48,Bold=1'")),
        _f_subtitles,
        "Imprime i sottotitoli nell'immagine. Generali con make_captions: il "
        "formato .ass porta anche l'evidenziazione parola per parola.",
    ),
    EffectDef(
        "mirror", "video", "Specchia",
        (Param("horizontal", True, kind="bool"), Param("vertical", False, kind="bool")),
        _f_mirror,
    ),
    EffectDef(
        "stabilize", "video", "Stabilizzazione",
        (Param("smoothing", 15, min=1, max=100), Param("zoom", 0, min=-10, max=10)),
        _f_stabilize, "Richiede analisi vidstab (fatta in automatico al render); senza analisi usa deshake.",
    ),
    EffectDef(
        "motionblur", "video", "Motion blur",
        (Param("mode", "blend", kind="enum", choices=("blend", "interpolate")), Param("frames", 3, min=2, max=9)),
        _f_fps_blend, "blend = scia morbida; interpolate = frame interpolati (lento).",
    ),
    # ---- audio ----
    EffectDef(
        "eq3", "audio", "Equalizzatore",
        (Param("bass", 0, min=-20, max=20, desc="dB"), Param("mid", 0, min=-20, max=20),
         Param("treble", 0, min=-20, max=20)),
        _a_eq3,
    ),
    EffectDef(
        "compressor", "audio", "Compressore",
        (Param("threshold", -18, min=-60, max=0, desc="dB"), Param("ratio", 3, min=1, max=20),
         Param("attack", 20, min=0.01, max=2000), Param("release", 250, min=0.01, max=9000),
         Param("makeup", 1, min=1, max=64)),
        _a_compressor,
    ),
    EffectDef("limiter", "audio", "Limiter", (Param("limit", 0.95, min=0.1, max=1),), _a_limiter),
    EffectDef(
        "adenoise", "audio", "Riduzione rumore",
        (Param("reduction", 12, min=0.01, max=97, desc="dB"), Param("floor", -40, min=-80, max=-20)),
        _a_denoise, "Toglie fruscio/ronzio di fondo.",
    ),
    EffectDef("highpass", "audio", "Passa-alto", (Param("freq", 80, min=10, max=2000),), _a_highpass,
              "Taglia le basse: rimuove rimbombo e rumore di traffico."),
    EffectDef("lowpass", "audio", "Passa-basso", (Param("freq", 16000, min=500, max=20000),), _a_lowpass),
    EffectDef("echo", "audio", "Eco", (Param("delay_ms", 300, min=10, max=5000), Param("decay", 0.4, min=0, max=1)), _a_echo),
    EffectDef("reverb", "audio", "Riverbero", (Param("amount", 0.3, min=0, max=0.9), Param("size", 0.5, min=0.1, max=1)), _a_reverb),
    EffectDef("pitch", "audio", "Pitch", (Param("semitones", 0, min=-24, max=24),), _a_pitch,
              "Cambia intonazione senza cambiare durata."),
    EffectDef(
        "gate", "audio", "Noise gate",
        (Param("threshold", 0.02, min=0, max=1), Param("ratio", 4, min=1, max=20),
         Param("attack", 20), Param("release", 250)),
        _a_gate,
    ),
    EffectDef(
        "censor", "audio", "Censura parlato",
        (
            Param("ranges", "", kind="string", desc="'12.4-12.9;30.1-30.4' dalla trascrizione"),
            Param("mode", "mute", kind="enum", choices=("mute", "scramble")),
            Param("shift", 400, min=50, max=2000, desc="Hz, solo per scramble"),
        ),
        _a_censor,
        "Copre gli intervalli indicati: mute li azzera, scramble sposta le "
        "frequenze e rende la voce incomprensibile ma presente. Gli intervalli "
        "arrivano da analyze.censor_spans (timestamp per parola).",
    ),
    EffectDef(
        "dynnorm", "audio", "Normalizzazione dinamica",
        (Param("frame_ms", 200, min=10, max=8000), Param("gauss", 15, min=3, max=31), Param("peak", 0.9, min=0.1, max=1)),
        _a_dynnorm, "Livella il volume nel tempo (per parlato irregolare).",
    ),
)

EFFECTS: dict[str, EffectDef] = {d.name: d for d in _DEFS}


def build_chain(effects, ctx: Ctx, kind: str) -> list[str]:
    """Compila la lista di Effect del modello nella catena di filtri."""
    out: list[str] = []
    for e in effects:
        if not getattr(e, "enabled", True):
            continue
        d = EFFECTS.get(e.type)
        if d is None or d.kind != kind:
            continue
        out.extend(f for f in d.build(dict(e.params or {}), ctx) if f)
    return out


def describe(kind: str | None = None) -> list[dict]:
    """Descrizione JSON del registro (usata da MCP e UI)."""
    out = []
    for d in _DEFS:
        if kind and d.kind != kind:
            continue
        out.append({
            "name": d.name,
            "kind": d.kind,
            "label": d.label,
            "desc": d.desc,
            "params": [
                {
                    "name": p.name, "default": p.default, "type": p.kind,
                    "min": p.min, "max": p.max, "animatable": p.anim,
                    "choices": list(p.choices), "desc": p.desc,
                }
                for p in d.params
            ],
        })
    return out


def validate_effect(type_: str, params: dict) -> dict:
    """Verifica nome effetto e parametri, ritorna i parametri normalizzati."""
    d = _spec(type_)
    known = {p.name for p in d.params}
    unknown = set(params or {}) - known
    if unknown:
        raise ValueError(
            f"parametri sconosciuti per {type_!r}: {sorted(unknown)}; ammessi: {sorted(known)}"
        )
    clean = {}
    for p in d.params:
        if p.name not in (params or {}):
            continue
        v = params[p.name]
        if kf.is_kf(v):
            if not p.anim:
                raise ValueError(f"{type_}.{p.name} non e' animabile")
            kf.validate(v)
        elif p.kind == "number" and (p.min is not None or p.max is not None):
            fv = float(v)
            if p.min is not None and fv < p.min:
                raise ValueError(f"{type_}.{p.name}={fv} sotto il minimo {p.min}")
            if p.max is not None and fv > p.max:
                raise ValueError(f"{type_}.{p.name}={fv} sopra il massimo {p.max}")
            v = fv
        elif p.kind == "enum" and p.choices and str(v) not in p.choices:
            raise ValueError(f"{type_}.{p.name}={v!r} non ammesso, scegli tra {list(p.choices)}")
        clean[p.name] = v
    return clean
