"""Compilazione della timeline in un filter_complex ffmpeg.

Modello di composizione: si parte da un canvas (sorgente ``color`` della durata
del progetto) e si sovrappone una clip alla volta con ``overlay``. E' l'unico
schema che regge multi-traccia, PiP, overlay grafici e dissolvenze senza casi
speciali; il costo e' un overlay per clip, trascurabile rispetto a decodifica e
scaling.

Posizionamento temporale: ogni clip viene allungata all'inizio con ``tpad``
(frame trasparenti) invece di spostare i PTS. Cosi' l'overlay ha sempre frame
disponibili su entrambi gli ingressi e non si blocca in attesa.

Ordine di disegno: le tracce video vanno dal basso verso l'alto secondo
l'ordine della lista. Dentro la stessa traccia le clip successive sono disegnate
*sotto* le precedenti, cosi' la dissolvenza in uscita di una clip scopre quella
dopo (cross-dissolve gratuito).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import effects as fx
from . import keyframes as kf
from .model import Clip, Media, Project, Track

DEFAULT_FONTS = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

MAX_PREPAD = 4.0  # limite al pre-ingrandimento usato per lo zoom animato


@dataclass
class Compiled:
    inputs: list[str]  # argomenti -i (in ordine)
    filtergraph: str
    video_label: str | None
    audio_label: str | None
    duration: float
    warnings: list[str] = field(default_factory=list)


@dataclass
class CompileOptions:
    width: int | None = None  # override risoluzione (preview)
    height: int | None = None
    fps: float | None = None
    use_proxy: bool = False
    audio: bool = True
    video: bool = True
    start: float | None = None  # taglio della porzione di timeline da rendere
    end: float | None = None
    workdir: str | None = None  # per i file di testo di drawtext
    hwaccel: bool = False
    stab_files: dict = field(default_factory=dict)  # clip_id -> file .trf di vidstab


# --------------------------------------------------------------------------
# utilita'
# --------------------------------------------------------------------------


def n(x: float) -> str:
    s = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return s or "0"


def _default_font() -> str | None:
    return next((f for f in DEFAULT_FONTS if Path(f).exists()), None)


def _atempo_chain(speed: float) -> list[str]:
    """atempo accetta 0.5..100 per istanza: decomponiamo i fattori estremi."""
    out: list[str] = []
    s = float(speed)
    if abs(s - 1.0) < 1e-6:
        return out
    while s > 2.0:
        out.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        out.append("atempo=0.5")
        s /= 0.5
    out.append(f"atempo={n(s)}")
    return out


def _simple_ramp(value) -> tuple[str, float, float] | None:
    """Riconosce l'opacita' animata che e' solo una comparsa o una scomparsa.

    Due keyframe lineari da 0 a 1 (o da 1 a 0) sono esattamente cio' che fa il
    filtro ``fade``, che lavora sul piano alpha senza valutare ogni pixel.
    """
    if not kf.is_kf(value):
        return None
    keys = sorted(value["kf"], key=lambda k: float(k.get("t", 0)))
    if len(keys) != 2 or str(keys[0].get("ease", "linear")) != "linear":
        return None
    t0, t1 = float(keys[0].get("t", 0)), float(keys[1].get("t", 0))
    v0, v1 = float(keys[0].get("v", 0)), float(keys[1].get("v", 0))
    if t1 - t0 <= 1e-6 or t0 < 0:
        return None
    if abs(v0) < 1e-6 and abs(v1 - 1) < 1e-6:
        return "in", t0, t1 - t0
    if abs(v0 - 1) < 1e-6 and abs(v1) < 1e-6:
        return "out", t0, t1 - t0
    return None


def clip_offset(clip: Clip) -> float:
    """Tempo locale del primo fotogramma visibile (>0 solo nei segmenti)."""
    return getattr(clip, "_slice_offset", 0.0)


def clip_visible(clip: Clip) -> float:
    """Quanto della clip resta visibile: nel progetto intero e' la sua durata."""
    return getattr(clip, "_slice_visible", None) or clip.duration


def clip_origin(clip: Clip) -> float:
    """Posizione originale in timeline, usata per l'ordine di sovrapposizione.

    Nei segmenti di anteprima piu' clip finiscono a start 0: senza questo dato
    l'ordine di disegno cambierebbe rispetto al render completo.
    """
    return getattr(clip, "_slice_origin", clip.start)


def slice_project(project: Project, start: float, end: float) -> Project:
    """Nuovo progetto contenente solo la porzione [start, end), riportata a 0.

    Serve per rendere segmenti di anteprima senza decodificare dall'inizio.

    Le clip tagliate mantengono ``duration``, ``fade_*`` e i keyframe originali:
    viene annotato solo *da dove* riprendere (``_slice_offset``) e *quanto*
    mostrare (``_slice_visible``). Cosi' una dissolvenza o una transizione
    inquadrata a meta' mostra esattamente il fotogramma che si vedrebbe nel
    render completo, invece di ripartire da capo. Sono annotazioni interne al
    compilatore: non finiscono nel file di progetto.
    """
    import copy

    out = copy.deepcopy(project)
    for track in out.tracks:
        kept: list[Clip] = []
        for c in track.clips:
            if c.end <= start or c.start >= end:
                continue
            head = max(0.0, start - c.start)  # quanto della clip cade prima del taglio
            tail = max(0.0, c.end - end)
            visible = c.duration - head - tail
            if visible <= 1e-6:
                continue
            c.in_ = c.in_ + head * abs(c.speed or 1.0)
            c._slice_origin = clip_origin(c)
            c.start = max(0.0, c.start - start)
            c._slice_offset = clip_offset(c) + head
            c._slice_visible = visible
            kept.append(c)
        track.clips = kept
    return out


# --------------------------------------------------------------------------
# compilatore
# --------------------------------------------------------------------------


class _Builder:
    def __init__(self, project: Project, opts: CompileOptions):
        self.p = project
        self.o = opts
        s = project.settings
        self.w = int(opts.width or s.width)
        self.h = int(opts.height or s.height)
        self.fps = float(opts.fps or s.fps)
        # in preview si rende piu' piccolo: tutto cio' che e' espresso in pixel
        # (posizioni, corpo del testo, raggi di sfocatura) va riscalato
        self.scale = self.w / float(s.width or self.w)
        self.sr = int(s.sample_rate)
        self.inputs: list[str] = []
        self.chains: list[str] = []
        self.warnings: list[str] = []
        self._n = 0
        self._text_files = 0

    # -- infrastruttura -------------------------------------------------
    def label(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def add_input(self, args: list[str]) -> int:
        idx = sum(1 for a in self.inputs if a == "-i")
        self.inputs.extend(args)
        return idx

    def chain(self, src: str, filters: list[str], dst: str) -> str:
        body = ",".join(f for f in filters if f) or "null"
        self.chains.append(f"[{src}]{body}[{dst}]")
        return dst

    def src_path(self, media: Media) -> str:
        if self.o.use_proxy and media.proxy and Path(media.proxy).exists():
            return media.proxy
        return media.path

    # -- ingressi -------------------------------------------------------
    def input_for(self, clip: Clip, media: Media) -> int:
        path = self.src_path(media)
        args: list[str] = []
        if self.o.hwaccel and media.kind == "video":
            args += ["-hwaccel", "auto"]
        visible = clip_visible(clip)
        if media.kind == "image":
            args += ["-loop", "1", "-framerate", n(self.fps), "-t", n(visible + 0.1)]
        else:
            src_dur = visible * abs(clip.speed or 1.0)
            if clip.in_ > 0:
                args += ["-ss", n(clip.in_)]
            args += ["-t", n(src_dur + 0.05)]
        args += ["-i", path]
        return self.add_input(args)

    # -- catena video di una clip ---------------------------------------
    def video_clip(self, clip: Clip, track: Track) -> str | None:
        """Ritorna l'etichetta del flusso pronto per l'overlay sul canvas."""
        media = self.p.media_by_id(clip.media) if clip.media else None
        ctx = fx.Ctx(width=self.w, height=self.h, fps=self.fps, sample_rate=self.sr,
                     tvar="t", duration=clip.duration, scale=self.scale,
                     extra={"clip": clip.id, "trf": self.o.stab_files.get(clip.id)})

        f: list[str] = []
        if clip.type == "media":
            if media is None or not media.has_video:
                return None
            idx = self.input_for(clip, media)
            src = f"{idx}:v"
            if clip.reverse:
                f.append("reverse")
                if clip.duration > 20:
                    self.warnings.append(
                        f"clip {clip.id}: reverse su {clip.duration:.0f}s tiene tutti i frame in RAM"
                    )
            f.append("setpts=PTS-STARTPTS")
            if abs(clip.speed - 1.0) > 1e-6:
                f.append(f"setpts=PTS/{n(clip.speed)}")
            f.append(f"fps={n(self.fps)}")
        else:
            # sorgenti generate: nessun ingresso, la catena parte da un filtro
            src = None
            dur = clip_visible(clip)
            if clip.type == "color":
                gen = f"color=c={clip.color}:s={self.w}x{self.h}:r={n(self.fps)}:d={n(dur)}"
            else:  # text
                gen = f"color=c=black@0:s={self.w}x{self.h}:r={n(self.fps)}:d={n(dur)}"
            f.append(gen)
            f.append("format=yuva420p")
            if clip.type == "text":
                f.append(self._drawtext(clip, ctx))

        # Nei segmenti di anteprima il tempo locale riparte dall'offset invece
        # che da zero, e va fatto subito: tutto quello che segue (effetti con
        # eval=frame, maschere di transizione, dissolvenze) legge il tempo del
        # fotogramma e deve vedere quello vero della clip.
        off = clip_offset(clip)
        if off > 0:
            f.append(f"setpts=PTS-STARTPTS+{n(off)}/TB")

        # inquadratura sul canvas
        if clip.type == "media":
            f.extend(self._fit(clip, media))
        f.append("setsar=1")

        # effetti video della clip
        f.extend(fx.build_chain(clip.effects, ctx, "video"))

        # trasformazioni
        f.append("format=yuva420p")
        f.extend(self._scale_transform(clip))
        f.extend(self._rotate(clip))
        f.extend(self._opacity(clip))

        # dissolvenze (tempo locale alla clip)
        if clip.fade_in > 0:
            f.append(f"fade=t=in:st=0:d={n(clip.fade_in)}:alpha=1")
        if clip.fade_out > 0:
            st = max(0.0, clip.duration - clip.fade_out)
            f.append(f"fade=t=out:st={n(st)}:d={n(clip.fade_out)}:alpha=1")

        f.extend(self._transition_mask(clip))

        # limite di durata e posizionamento in timeline
        f.append(f"trim={n(off)}:{n(off + clip_visible(clip))}")
        f.append("setpts=PTS-STARTPTS")
        if clip.start > 1e-6:
            f.append(f"tpad=start_duration={n(clip.start)}:start_mode=add:color=black@0")

        out = self.label("v")
        if src is None:
            self.chains.append(",".join(f) + f"[{out}]")
        else:
            self.chain(src, f, out)
        return out

    def _fit(self, clip: Clip, media: Media) -> list[str]:
        w, h = self.w, self.h
        mode = clip.fit
        if mode == "none":
            # dimensione nativa: in preview va comunque ridotta come il canvas
            if abs(self.scale - 1.0) > 1e-6:
                return [f"scale=iw*{n(self.scale)}:ih*{n(self.scale)}:flags=bicubic"]
            return []
        if mode == "stretch":
            return [f"scale={w}:{h}:flags=bicubic"]
        if mode == "cover":
            return [
                f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=bicubic",
                f"crop={w}:{h}",
            ]
        return [  # contain
            f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=bicubic",
            "format=yuva420p",
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0",
        ]

    def _scale_transform(self, clip: Clip) -> list[str]:
        s = clip.transform.scale
        if not kf.is_kf(s):
            v = float(kf.sample(s, 0, 1.0))
            if abs(v - 1.0) < 1e-6:
                return []
            return [f"scale=iw*{n(v)}:ih*{n(v)}:flags=bicubic"]

        # zoom animato: zoompan non scende sotto 1, quindi pre-ingrandiamo il
        # canvas di K e chiediamo zoom = K*s(t), che a video vale esattamente s(t).
        smin, smax = kf.bounds(s, 1.0)
        k = 1.0 if smin >= 1.0 else min(MAX_PREPAD, 1.0 / max(smin, 1e-3))
        if smin < 1.0 / MAX_PREPAD:
            self.warnings.append(
                f"clip {clip.id}: scala animata sotto {1 / MAX_PREPAD:.2f} limitata a {1 / MAX_PREPAD:.2f}"
            )
        # zoompan non espone il tempo: con d=1 vale un frame in uscita per frame
        # in ingresso, quindi il tempo e' il numero di frame diviso gli fps.
        expr = kf.expr(s, f"(on/{n(self.fps)}+{n(clip_offset(clip))})", 1.0)
        z = f"clip({n(k)}*({expr}),1,10)"
        out: list[str] = []
        if k > 1.0:
            bw, bh = int(self.w * k), int(self.h * k)
            bw += bw % 2
            bh += bh % 2
            out.append(f"pad={bw}:{bh}:(ow-iw)/2:(oh-ih)/2:color=black@0")
        out.append(
            f"zoompan=z={fx.quoted(z)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={self.w}x{self.h}:fps={n(self.fps)}"
        )
        # zoompan riscrive i timestamp partendo da zero e butta via l'offset
        # della fetta: senza rimetterlo il trim piu' avanti scarta ogni
        # fotogramma e la clip sparisce dall'anteprima (schermo nero).
        off = clip_offset(clip)
        if off > 0:
            out.append(f"setpts=PTS-STARTPTS+{n(off)}/TB")
        out.append("format=yuva420p")
        if k * smax > 10:
            self.warnings.append(f"clip {clip.id}: scala massima {smax:.2f} oltre il limite di zoompan (10x)")
        return out

    def _rotate(self, clip: Clip) -> list[str]:
        r = clip.transform.rotation
        if not kf.is_kf(r) and abs(float(kf.sample(r, 0, 0.0))) < 1e-6:
            return []
        expr = kf.expr(r, "t", 0.0)
        # rotate lavora in radianti; allarghiamo alla diagonale per non tagliare
        return [
            f"rotate=a={fx.quoted(f'({expr})*PI/180')}:ow='hypot(iw,ih)':oh='hypot(iw,ih)'"
            f":c=black@0:fillcolor=black@0"
        ]

    def _opacity(self, clip: Clip) -> list[str]:
        op = clip.transform.opacity
        if not kf.is_kf(op):
            v = float(kf.sample(op, 0, 1.0))
            if v >= 0.999:
                return []
            return [f"colorchannelmixer=aa={n(max(0.0, v))}"]
        # Caso comune (comparsa o scomparsa lineare): lo fa il filtro fade, che
        # non costa nulla. Solo le animazioni piu' complesse passano da geq.
        ramp = _simple_ramp(op)
        if ramp:
            kind, st, d = ramp
            return [f"fade=t={kind}:st={n(st)}:d={n(d)}:alpha=1"]

        # opacita' animata generica: geq sul solo piano alpha.
        # In geq la variabile temporale si chiama T, non t.
        expr = kf.expr(op, "T", 1.0)
        self.warnings.append(f"clip {clip.id}: opacita' animata usa geq, render piu' lento")
        return [
            "geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':"
            f"a='alpha(X,Y)*clip({expr},0,1)'"
        ]

    def _transition_mask(self, clip: Clip) -> list[str]:
        """Tendine e iris: maschera sul canale alpha che cancella la clip uscente.

        Con l'ordine di disegno adottato (la clip che inizia prima sta sopra),
        togliere pixel alla clip in uscita scopre quella successiva: una sola
        maschera realizza la transizione, senza secondo ramo del grafo.
        """
        tr = clip.transition_out
        if not tr or tr.duration <= 0 or tr.type in ("dissolve", ""):
            return []
        d = min(tr.duration, clip.duration)
        ts = max(0.0, clip.duration - d)
        # in geq il tempo si chiama T e W/H sono le dimensioni dell'immagine
        p = f"clip((T-{n(ts)})/{n(d)},0,1)"

        masks = {
            "wipe_right": f"gt(X,W*{p})",
            "wipe_left": f"lt(X,W*(1-{p}))",
            "wipe_down": f"gt(Y,H*{p})",
            "wipe_up": f"lt(Y,H*(1-{p}))",
            "iris": f"lt(hypot(X-W/2,Y-H/2),hypot(W/2,H/2)*(1-{p}))",
        }
        cond = masks.get(tr.type)
        if cond is None:
            return []  # slide: si realizza spostando l'overlay, non mascherando
        # geq costa (valuta ogni pixel): con enable lavora solo durante la
        # transizione, il resto della clip passa senza essere toccato
        return [
            "geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':"
            f"a='alpha(X,Y)*({cond})'"
            f":enable={fx.quoted(f'gte(t,{n(ts)})')}"
        ]

    def _slide_offset(self, clip: Clip) -> tuple[str, str]:
        """Spostamento (x, y) della clip uscente durante una transizione slide."""
        tr = clip.transition_out
        if not tr or tr.duration <= 0 or not tr.type.startswith("slide"):
            return "0", "0"
        d = min(tr.duration, clip.duration)
        ts = clip.start + max(0.0, clip.duration - d)
        p = f"clip((t-{n(ts)})/{n(d)},0,1)"
        return {
            "slide_left": (f"-W*{p}", "0"),
            "slide_right": (f"W*{p}", "0"),
            "slide_up": ("0", f"-H*{p}"),
            "slide_down": ("0", f"H*{p}"),
        }.get(tr.type, ("0", "0"))

    def _drawtext(self, clip: Clip, ctx: fx.Ctx) -> str:
        st = clip.text
        font = st.font_file or _default_font()
        args = []
        if font:
            args.append(f"fontfile='{fx.esc_path(font)}'")
        else:
            self.warnings.append("nessun font trovato: drawtext potrebbe fallire")

        # il testo passa da file: niente problemi di escape con apici, due punti,
        # virgole, percentuali o a capo
        if self.o.workdir:
            self._text_files += 1
            tf = Path(self.o.workdir) / f"text_{clip.id}_{self._text_files}.txt"
            tf.write_text(st.text, encoding="utf-8")
            args.append(f"textfile='{fx.esc_path(str(tf))}'")
        else:
            args.append(f"text='{fx.esc_str(st.text)}'")

        k = self.scale
        args += [
            f"fontsize={max(4, int(st.font_size * k))}",
            f"fontcolor={fx.esc_str(st.color)}",
            f"line_spacing={int(st.line_spacing * k)}",
            "expansion=none",
            "y=(h-text_h)/2",
        ]
        if st.align == "left":
            args.append("x=0.06*w")
        elif st.align == "right":
            args.append("x=0.94*w-text_w")
        else:
            args.append("x=(w-text_w)/2")
        if st.box:
            args += [
                "box=1",
                f"boxcolor={fx.esc_str(st.box_color)}@{n(st.box_opacity)}",
                f"boxborderw={max(0, int(st.box_padding * k))}",
            ]
        if st.border_width:
            args += [f"borderw={max(1, int(st.border_width * k))}",
                     f"bordercolor={fx.esc_str(st.border_color)}"]
        if st.shadow_x or st.shadow_y:
            args += [
                f"shadowx={int(st.shadow_x * k)}", f"shadowy={int(st.shadow_y * k)}",
                f"shadowcolor={fx.esc_str(st.shadow_color)}",
            ]
        return "drawtext=" + ":".join(args)

    # -- composizione video ---------------------------------------------
    def build_video(self, duration: float) -> str | None:
        bg = self.p.settings.background or "black"
        base = self.label("bg")
        self.chains.append(
            f"color=c={bg}:s={self.w}x{self.h}:r={n(self.fps)}:d={n(duration)},format=yuv420p[{base}]"
        )

        drawn = 0
        # live_tracks applica nascosto e solo: quello che resta e' esattamente
        # cio' che si compone, dal basso verso l'alto
        for track in self.p.live_tracks("video"):
            # Ordine di sovrapposizione dentro la traccia:
            #  - le clip che iniziano dopo vanno sotto, cosi' la transizione in
            #    uscita di una scopre la seguente;
            #  - titoli e colori pieni stanno comunque sopra i media: un titolo
            #    messo sulla stessa traccia di una ripresa deve vedersi.
            # A parita' di posizione vince l'ordine della lista (sort stabile).
            for clip in sorted(track.clips,
                               key=lambda c: (c.type in ("text", "color"), -clip_origin(c))):
                if not clip.enabled or clip.duration <= 0:
                    continue
                lab = self.video_clip(clip, track)
                if lab is None:
                    continue
                out = self.label("ov")
                # tempo locale della clip visto dal canvas, offset del segmento incluso
                origin = clip.start - clip_offset(clip)
                tvar = f"(t-{n(origin)})" if abs(origin) > 1e-9 else "t"
                x = kf.expr(clip.transform.x, tvar, 0.0)
                y = kf.expr(clip.transform.y, tvar, 0.0)
                k = n(self.scale)  # offset in pixel del progetto -> pixel di render
                sx, sy = self._slide_offset(clip)
                self.chains.append(
                    f"[{base}][{lab}]overlay="
                    f"x={fx.quoted(f'(W-w)/2+({x})*{k}+({sx})')}"
                    f":y={fx.quoted(f'(H-h)/2+({y})*{k}+({sy})')}"
                    f":eof_action=pass:repeatlast=0"
                    f":enable={fx.quoted(f'between(t,{n(clip.start)},{n(clip.start + clip_visible(clip))})')}"
                    f"[{out}]"
                )
                base = out
                drawn += 1

        tail = fx.build_chain(self.p.master.effects, fx.Ctx(
            width=self.w, height=self.h, fps=self.fps, sample_rate=self.sr,
            duration=duration, scale=self.scale), "video")
        tail.append("format=yuv420p")
        out = self.label("vout")
        self.chain(base, tail, out)
        return out

    # -- catena audio di una clip ---------------------------------------
    def audio_clip(self, clip: Clip, track: Track) -> str | None:
        if clip.type != "media" or clip.audio.mute:
            return None
        media = self.p.media_by_id(clip.media) if clip.media else None
        if media is None or not media.has_audio:
            return None

        # la clip video ha gia' creato il proprio ingresso: ne apriamo un altro
        # solo per l'audio, cosi' i due rami restano indipendenti
        idx = self.input_for(clip, media)
        off = clip_offset(clip)
        f = ["asetpts=PTS-STARTPTS"]
        f += _atempo_chain(clip.speed)
        if off > 0:  # come per il video: il tempo locale riparte dall'offset
            f.append(f"asetpts=PTS-STARTPTS+{n(off)}/TB")
        f.append(f"aformat=sample_fmts=fltp:sample_rates={self.sr}:channel_layouts=stereo")

        gain = clip.audio.gain_db
        tvol = kf.expr(track.volume, "t", 1.0)
        if kf.is_kf(gain):
            e = kf.expr(gain, "t", 0.0)
            f.append(f"volume=volume={fx.quoted(f'pow(10,({e})/20)')}:eval=frame")
        else:
            g = float(kf.sample(gain, 0, 0.0))
            if abs(g) > 1e-6:
                f.append(f"volume={n(10 ** (g / 20.0))}")
        if kf.is_kf(track.volume):
            f.append(f"volume=volume={fx.quoted(tvol)}:eval=frame")
        else:
            tv = float(kf.sample(track.volume, 0, 1.0))
            if abs(tv - 1.0) > 1e-6:
                f.append(f"volume={n(tv)}")

        pan = float(kf.sample(clip.audio.pan, 0, 0.0))
        if abs(pan) > 1e-6:
            left = max(0.0, 1.0 - max(0.0, pan))
            right = max(0.0, 1.0 + min(0.0, pan))
            f.append(f"pan=stereo|c0={n(left)}*c0|c1={n(right)}*c1")

        ctx = fx.Ctx(width=self.w, height=self.h, fps=self.fps, sample_rate=self.sr,
                     tvar="t", duration=clip.duration, scale=self.scale)
        f.extend(fx.build_chain(clip.effects, ctx, "audio"))

        f.append(f"atrim={n(off)}:{n(off + clip_visible(clip))}")
        f.append("asetpts=PTS-STARTPTS")
        if clip.audio.fade_in > 0:
            f.append(f"afade=t=in:st=0:d={n(clip.audio.fade_in)}")
        if clip.audio.fade_out > 0:
            f.append(f"afade=t=out:st={n(max(0.0, clip.duration - clip.audio.fade_out))}"
                     f":d={n(clip.audio.fade_out)}")
        if clip.start > 1e-6:
            ms = int(round(clip.start * 1000))
            f.append(f"adelay={ms}|{ms}:all=1")

        out = self.label("a")
        self.chain(f"{idx}:a", f, out)
        return out

    def build_audio(self, duration: float) -> str | None:
        labels: list[str] = []
        # Anche le clip su una traccia video portano il loro audio, quindi il mix
        # le comprende. Ma se una traccia audio e' in solo si ascolta solo quella:
        # e' il senso del solo, isolare un suono per sentirlo da solo.
        solo = [t for t in self.p.audio_tracks() if t.solo]
        sources = solo if solo else self.p.tracks
        for track in sources:
            if track.muted:
                continue
            for clip in track.clips:
                if not clip.enabled or clip.duration <= 0:
                    continue
                lab = self.audio_clip(clip, track)
                if lab:
                    labels.append(lab)

        if not labels:
            return None

        mixed = self.label("amix")
        if len(labels) == 1:
            self.chains.append(f"[{labels[0]}]anull[{mixed}]")
        else:
            ins = "".join(f"[{l}]" for l in labels)
            self.chains.append(
                f"{ins}amix=inputs={len(labels)}:duration=longest:normalize=0:dropout_transition=0[{mixed}]"
            )

        tail: list[str] = []
        mv = self.p.master.volume
        if kf.is_kf(mv):
            tail.append(f"volume=volume={fx.quoted(kf.expr(mv, 't', 1.0))}:eval=frame")
        elif abs(float(kf.sample(mv, 0, 1.0)) - 1.0) > 1e-6:
            tail.append(f"volume={n(float(kf.sample(mv, 0, 1.0)))}")

        ctx = fx.Ctx(width=self.w, height=self.h, fps=self.fps, sample_rate=self.sr,
                     duration=duration, scale=self.scale)
        tail.extend(fx.build_chain(self.p.master.effects, ctx, "audio"))

        ln = self.p.master.loudnorm
        if ln.enabled:
            args = [f"I={n(ln.i)}", f"TP={n(ln.tp)}", f"LRA={n(ln.lra)}"]
            m = ln.measured or {}
            if all(k in m for k in ("input_i", "input_tp", "input_lra", "input_thresh")):
                args += [
                    f"measured_I={m['input_i']}", f"measured_TP={m['input_tp']}",
                    f"measured_LRA={m['input_lra']}", f"measured_thresh={m['input_thresh']}",
                    "linear=true",
                ]
                if m.get("target_offset") is not None:
                    args.append(f"offset={m['target_offset']}")
            tail.append("loudnorm=" + ":".join(args))
            tail.append(f"aformat=sample_fmts=fltp:sample_rates={self.sr}:channel_layouts=stereo")

        tail.append("alimiter=limit=0.98:level=false")
        # durata esatta del progetto, anche se l'ultima clip finisce prima
        tail.append("apad")
        tail.append(f"atrim=0:{n(duration)}")
        tail.append("asetpts=PTS-STARTPTS")

        out = self.label("aout")
        self.chain(mixed, tail, out)
        return out


def compile_project(project: Project, opts: CompileOptions | None = None) -> Compiled:
    opts = opts or CompileOptions()
    proj = project
    if opts.start is not None or opts.end is not None:
        a = opts.start or 0.0
        b = opts.end if opts.end is not None else project.duration()
        proj = slice_project(project, a, b)
        duration = max(0.0, b - a)
    else:
        duration = project.duration()

    if duration <= 0:
        raise ValueError("timeline vuota: nessuna clip da rendere")

    b = _Builder(proj, opts)
    vlabel = b.build_video(duration) if opts.video else None
    alabel = b.build_audio(duration) if opts.audio else None
    return Compiled(
        inputs=b.inputs,
        filtergraph=";\n".join(b.chains),
        video_label=vlabel,
        audio_label=alabel,
        duration=duration,
        warnings=b.warnings,
    )
