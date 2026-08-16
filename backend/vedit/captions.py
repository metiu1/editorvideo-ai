"""Sottotitoli: dalle parole trascritte a SRT, VTT e ASS con karaoke.

La trascrizione da' i tempi di ogni parola; qui diventano righe leggibili. Le
regole di raggruppamento sono quelle dei sottotitoli veri:

- una riga non supera ``max_chars`` caratteri (si legge in un colpo d'occhio);
- non dura piu' di ``max_dur`` secondi;
- si spezza sulle pause: una pausa lunga e' un cambio di frase.

Il formato ASS porta anche il karaoke parola per parola: il tag ``\\k`` dice per
quanti centesimi ogni parola resta "non ancora detta". ffmpeg colora con
SecondaryColour cio' che non e' stato ancora pronunciato e con PrimaryColour il
resto: e' esattamente l'effetto dei sottotitoli di TikTok/Reels.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MAX_CHARS = 42
MAX_DUR = 3.5
MAX_GAP = 0.7          # pausa che vale un cambio riga


@dataclass
class CaptionStyle:
    """Aspetto dei sottotitoli ASS. I colori sono ``#RRGGBB``."""

    font: str = "Arial"
    size: int = 64
    primary: str = "#FFE100"      # parola gia' pronunciata (karaoke: evidenziata)
    secondary: str = "#FFFFFF"    # parola non ancora pronunciata
    outline_color: str = "#000000"
    outline: float = 3.0
    shadow: float = 0.0
    bold: bool = True
    margin_v: int = 120           # distanza dal bordo basso, in px
    alignment: int = 2            # 2 = in basso al centro (numpad ASS)
    uppercase: bool = False


def _ass_color(hex_color: str, alpha: str = "00") -> str:
    """``#RRGGBB`` -> ``&HAABBGGRR``: ASS vuole i byte al contrario."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"colore non valido: {hex_color!r}, serve #RRGGBB")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


# --------------------------------------------------------------------------
# raggruppamento
# --------------------------------------------------------------------------


def group_words(transcript: dict, max_chars: int = MAX_CHARS, max_dur: float = MAX_DUR,
                max_gap: float = MAX_GAP, offset: float = 0.0) -> list[dict]:
    """Parole -> righe di sottotitolo. ``offset`` sposta tutti i tempi."""
    righe: list[dict] = []
    corrente: list[dict] = []

    def chiudi() -> None:
        if not corrente:
            return
        righe.append({
            "start": round(corrente[0]["t"] - offset, 3),
            "end": round(corrente[-1]["e"] - offset, 3),
            "text": " ".join(w["w"] for w in corrente),
            "words": [{"w": w["w"], "t": round(w["t"] - offset, 3),
                       "e": round(w["e"] - offset, 3)} for w in corrente],
        })
        corrente.clear()

    for seg in transcript.get("segments", []):
        parole = seg.get("words") or []
        if not parole:      # segmento senza timestamp per parola: riga intera
            chiudi()
            righe.append({"start": round(seg["start"] - offset, 3),
                          "end": round(seg["end"] - offset, 3),
                          "text": seg["text"], "words": []})
            continue
        for w in parole:
            if corrente:
                testo = " ".join(x["w"] for x in corrente)
                troppo_lunga = len(testo) + 1 + len(w["w"]) > max_chars
                troppo_durata = w["e"] - corrente[0]["t"] > max_dur
                pausa = w["t"] - corrente[-1]["e"] > max_gap
                if troppo_lunga or troppo_durata or pausa:
                    chiudi()
            corrente.append(w)
    chiudi()
    return [r for r in righe if r["end"] > r["start"] and r["text"].strip()]


# --------------------------------------------------------------------------
# formati
# --------------------------------------------------------------------------


def _ts_srt(t: float) -> str:
    # si arrotonda ai millisecondi prima di dividere: cosi' 0.9999 diventa 1.000
    # e non 0.000 con il secondo sbagliato
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ts_vtt(t: float) -> str:
    return _ts_srt(t).replace(",", ".")


def _ts_ass(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def to_srt(righe: list[dict]) -> str:
    out = []
    for i, r in enumerate(righe, 1):
        out.append(f"{i}\n{_ts_srt(r['start'])} --> {_ts_srt(r['end'])}\n{r['text'].strip()}\n")
    return "\n".join(out)


def to_vtt(righe: list[dict]) -> str:
    out = ["WEBVTT", ""]
    for r in righe:
        out.append(f"{_ts_vtt(r['start'])} --> {_ts_vtt(r['end'])}")
        out.append(r["text"].strip())
        out.append("")
    return "\n".join(out)


def to_ass(righe: list[dict], style: CaptionStyle | None = None, karaoke: bool = True,
           width: int = 1080, height: int = 1920) -> str:
    """ASS completo. Con ``karaoke`` ogni parola si accende quando viene detta."""
    st = style or CaptionStyle()
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour,"
        " BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle,"
        " BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: vedit,{st.font},{st.size},{_ass_color(st.primary)},"
        f"{_ass_color(st.secondary)},{_ass_color(st.outline_color)},&H80000000,"
        f"{-1 if st.bold else 0},0,0,0,100,100,0,0,1,{st.outline},{st.shadow},"
        f"{st.alignment},40,40,{st.margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for r in righe:
        if karaoke and r.get("words"):
            pezzi = []
            prev = r["start"]
            for w in r["words"]:
                vuoto = max(0, int(round((w["t"] - prev) * 100)))
                if vuoto:
                    pezzi.append(f"{{\\k{vuoto}}} ")
                dur = max(1, int(round((w["e"] - w["t"]) * 100)))
                testo = w["w"].upper() if st.uppercase else w["w"]
                pezzi.append(f"{{\\k{dur}}}{_esc_ass(testo)} ")
                prev = w["e"]
            testo = "".join(pezzi).strip()
        else:
            testo = _esc_ass(r["text"].upper() if st.uppercase else r["text"]).strip()
        head.append(f"Dialogue: 0,{_ts_ass(r['start'])},{_ts_ass(r['end'])},vedit,,0,0,0,,{testo}")
    return "\n".join(head) + "\n"


def _esc_ass(s: str) -> str:
    return s.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


FORMATS = {"srt": to_srt, "vtt": to_vtt, "ass": to_ass}


def write(path: str, righe: list[dict], fmt: str = "ass", **kw) -> str:
    """Scrive il file sottotitoli e ne ritorna il percorso."""
    if fmt not in FORMATS:
        raise ValueError(f"formato {fmt!r} sconosciuto; scegli tra {sorted(FORMATS)}")
    testo = FORMATS[fmt](righe, **kw) if fmt == "ass" else FORMATS[fmt](righe)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # ASS e SRT vogliono UTF-8 senza BOM: ffmpeg legge male il BOM
    p.write_text(testo, encoding="utf-8", newline="\n")
    return str(p.resolve())
