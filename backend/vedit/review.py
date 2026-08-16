"""Guardare il montaggio invece di indovinarlo.

Un fotogramma non basta per giudicare un montaggio: servono il ritmo degli
stacchi, l'andamento dell'audio e la prova che quello che c'e' nel file
renderizzato sia davvero quello che la timeline dichiara.

Tre strumenti, tre domande:

- :func:`contact_sheet` - *com'e' fatta questa sequenza?* Una griglia di
  fotogrammi con il loro tempo sopra: stacchi, continuita' e buchi si vedono
  tutti insieme.
- :func:`waveform` - *dove sta il suono?* Picchi di un intervallo, piu' i
  livelli: serve a capire se un taglio cade in mezzo a una parola.
- :func:`verify` - *quello che ho montato e' quello che esce?* Renderizza un
  tratto a bassa risoluzione e lo ri-analizza, poi confronta le misure con
  quello che la timeline prometteva. E' il controllo che chiude il ciclo.
"""

from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

from . import analyze, ffmpeg, render

CUT_TOLERANCE = 0.25       # uno stacco misurato entro questo scarto e' "quello li'"


# --------------------------------------------------------------------------
# contact sheet
# --------------------------------------------------------------------------


def _range(project, start: float | None, end: float | None) -> tuple[float, float]:
    dur = project.duration()
    a = max(0.0, start if start is not None else 0.0)
    b = min(dur, end if end is not None else dur)
    if b <= a:
        raise ValueError(f"intervallo vuoto: {a}-{b} (timeline lunga {dur:.3f}s)")
    return a, b


def sample_times(project, count: int, start: float | None = None,
                 end: float | None = None) -> list[float]:
    """Istanti da campionare: mai sul bordo esatto di uno stacco.

    Sul bordo si rischia di prendere il fotogramma della clip sbagliata, che e'
    proprio l'informazione che si sta cercando di leggere.
    """
    a, b = _range(project, start, end)
    n = max(1, int(count))
    passo = (b - a) / n
    return [round(a + passo * (i + 0.5), 3) for i in range(n)]


def _timecode(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):d}:{s:05.2f}"


def contact_sheet(project, output: str, count: int = 12, width: int = 320,
                  cols: int = 4, start: float | None = None,
                  end: float | None = None, use_proxy: bool = True) -> dict:
    """Griglia di fotogrammi della timeline, con il tempo stampato su ognuno."""
    from PIL import Image, ImageDraw

    tempi = sample_times(project, count, start, end)
    tmp = Path(tempfile.mkdtemp(prefix="vedit_sheet_"))
    frames = []
    for i, t in enumerate(tempi):
        f = tmp / f"{i:03d}.jpg"
        render.render_frame(project, t, str(f), width, use_proxy)
        frames.append((t, str(f)))

    prima = Image.open(frames[0][1])
    fw, fh = prima.size
    cols = max(1, min(cols, len(frames)))
    righe = math.ceil(len(frames) / cols)
    sheet = Image.new("RGB", (cols * fw, righe * fh), (12, 12, 14))
    disegna = ImageDraw.Draw(sheet)

    for i, (t, f) in enumerate(frames):
        img = Image.open(f)
        if img.size != (fw, fh):
            img = img.resize((fw, fh))
        x, y = (i % cols) * fw, (i // cols) * fh
        sheet.paste(img, (x, y))
        etichetta = f"{i}  {_timecode(t)}"
        # riquadro scuro dietro al testo: sul chiaro sarebbe illeggibile
        disegna.rectangle([x + 4, y + 4, x + 4 + 8 * len(etichetta), y + 22],
                          fill=(0, 0, 0))
        disegna.text((x + 8, y + 8), etichetta, fill=(255, 240, 120))

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(str(out), quality=88)
    return {"file": str(out.resolve()), "fotogrammi": len(frames),
            "tempi": tempi, "griglia": [cols, righe]}


# --------------------------------------------------------------------------
# anteprima guardabile
# --------------------------------------------------------------------------

MAX_PREVIEW = 30.0         # oltre, un'anteprima non e' piu' un'anteprima


def preview_clip(project, output: str | None = None, start: float | None = None,
                 end: float | None = None, height: int = 360,
                 max_seconds: float = MAX_PREVIEW, audio: bool = True) -> dict:
    """Renderizza un tratto e **lo tiene**: un file da guardare davvero.

    Il contact sheet mostra la struttura, questo mostra il risultato. E' l'unico
    modo perche' una persona possa dire "qui non funziona" invece di fidarsi.

    La durata e' limitata di proposito: un'anteprima lunga e' un render, e va
    chiesto con ``render_video``.
    """
    a, b = _range(project, start, end)
    tagliato = False
    if b - a > max_seconds:
        b, tagliato = a + max_seconds, True

    out = Path(output) if output else Path(tempfile.mkdtemp(prefix="vedit_prev_")) / "anteprima.mp4"
    w = int(round(height * project.settings.width / project.settings.height))
    w += w % 2
    render.render(project, render.RenderOptions(
        output=str(out), start=a, end=b, quality="draft", width=w, height=height,
        use_proxy=True, audio=audio and has_audio(project, a, b)))
    return {
        "file": str(out.resolve()),
        "inizio": round(a, 3), "fine": round(b, 3),
        "durata": round(b - a, 3),
        "risoluzione": f"{w}x{height}",
        "byte": out.stat().st_size if out.exists() else 0,
        "troncata": tagliato,
        "nota": (f"anteprima limitata a {max_seconds:.0f}s: per il resto usa "
                 "render_video") if tagliato else None,
    }


# --------------------------------------------------------------------------
# scopes: misurare il colore invece di guardarlo a occhio
# --------------------------------------------------------------------------


def scopes(project, t: float, width: int = 480) -> dict:
    """Misure del colore su un fotogramma: esposizione, clipping, dominante.

    Un jpeg su uno schermo non calibrato non dice se una ripresa e' sottoesposta
    o se le alte luci sono bruciate. Questi numeri si'.
    """
    import numpy as np
    from PIL import Image as PILImage

    tmp = Path(tempfile.mkdtemp(prefix="vedit_scope_")) / "f.png"
    render.render_frame(project, t, str(tmp), width, True)
    img = np.asarray(PILImage.open(tmp).convert("RGB")).astype(np.float32)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    # Rec.709: l'occhio pesa il verde molto piu' del blu
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    piatta = luma.ravel()

    def pct(q: float) -> float:
        return round(float(np.percentile(piatta, q)), 1)

    massimo = img.max(axis=2)
    minimo = img.min(axis=2)
    sat = np.where(massimo > 0, (massimo - minimo) / np.maximum(massimo, 1e-6), 0.0)

    medie = [round(float(c.mean()), 1) for c in (r, g, b)]
    grigio = sum(medie) / 3.0 or 1.0
    dominante = [round(m / grigio, 3) for m in medie]

    bruciato = round(float((piatta > 250).mean()), 4)
    spento = round(float((piatta < 5).mean()), 4)

    avvisi = []
    if pct(50) < 45:
        avvisi.append("sottoesposta: la mediana della luminanza e' bassa")
    if pct(50) > 200:
        avvisi.append("sovraesposta")
    if bruciato > 0.02:
        avvisi.append(f"alte luci bruciate sul {bruciato * 100:.1f}% dei pixel")
    if spento > 0.05 and pct(1) < 2:
        avvisi.append(f"ombre chiuse sul {spento * 100:.1f}% dei pixel")
    if max(dominante) > 1.12:
        canale = "rossa" if dominante[0] == max(dominante) else (
            "verde" if dominante[1] == max(dominante) else "blu")
        avvisi.append(f"dominante {canale} ({max(dominante):.2f}x sul grigio)")
    if float(piatta.std()) < 25:
        avvisi.append("contrasto molto basso: immagine piatta")

    return {
        "t": round(t, 3),
        "luma": {"min": pct(0), "p1": pct(1), "mediana": pct(50), "p99": pct(99),
                 "max": pct(100), "media": round(float(piatta.mean()), 1),
                 "contrasto": round(float(piatta.std()), 1)},
        "clipping": {"alte_luci": bruciato, "ombre": spento},
        "canali_medi": {"r": medie[0], "g": medie[1], "b": medie[2]},
        "dominante": {"r": dominante[0], "g": dominante[1], "b": dominante[2]},
        "saturazione_media": round(float(sat.mean()), 3),
        "avvisi": avvisi,
        "ok": not avvisi,
    }


# --------------------------------------------------------------------------
# forma d'onda
# --------------------------------------------------------------------------


def has_audio(project, start: float, end: float) -> bool:
    """C'e' almeno una clip con audio vero che suona in questo intervallo?"""
    for kind in ("video", "audio"):
        for track in project.live_tracks(kind):
            for c in track.clips:
                if not c.enabled or c.end <= start or c.start >= end:
                    continue
                if getattr(c, "audio", None) is not None and getattr(c.audio, "mute", False):
                    continue
                m = project.media_by_id(c.media) if c.media else None
                if m is not None and m.has_audio:
                    return True
    return False


def waveform(project, start: float | None = None, end: float | None = None,
             points: int = 120) -> dict:
    """Picchi audio del mix in un intervallo, piu' i livelli di picco e medio.

    L'audio viene renderizzato davvero: cosi' i picchi tengono conto di gain,
    dissolvenze ed effetti, non solo del file sorgente.
    """
    import array

    a, b = _range(project, start, end)
    if not has_audio(project, a, b):
        # senza sorgenti audio il render non avrebbe nessun filtro da costruire e
        # ffmpeg fallirebbe: il muto e' una risposta legittima, non un errore
        return {"picchi": [], "durata": round(b - a, 3), "inizio": round(a, 3),
                "picco_db": None, "medio_db": None, "silenzio_ratio": 1.0,
                "nota": "nessuna sorgente audio nell'intervallo"}
    tmp = Path(tempfile.mkdtemp(prefix="vedit_wave_")) / "mix.wav"
    render.render(project, render.RenderOptions(
        output=str(tmp), start=a, end=b, video=False, audio=True,
        audio_codec="pcm_s16le", quality="draft"))

    rate = 8000
    proc = subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(tmp), "-vn", "-ac", "1", "-ar", str(rate),
        "-f", "s16le", "-acodec", "pcm_s16le", "-",
    ], capture_output=True, timeout=900)
    raw = proc.stdout or b""
    campioni = array.array("h")
    campioni.frombytes(raw[: len(raw) - (len(raw) % 2)])
    if not campioni:
        return {"picchi": [], "durata": round(b - a, 3), "picco_db": None,
                "medio_db": None, "nota": "nessun audio nell'intervallo"}

    n = max(1, min(points, len(campioni)))
    blocco = max(1, len(campioni) // n)
    picchi, somma = [], 0.0
    for i in range(0, len(campioni), blocco):
        pezzo = campioni[i: i + blocco]
        if not pezzo:
            break
        p = max(abs(min(pezzo)), abs(max(pezzo))) / 32768.0
        picchi.append(round(p, 4))
        somma += sum(x * x for x in pezzo) / len(pezzo)

    def db(x: float) -> float | None:
        return round(20 * math.log10(x), 1) if x > 1e-6 else None

    blocchi = max(1, len(picchi))
    return {
        "picchi": picchi[:points],
        "durata": round(b - a, 3),
        "inizio": round(a, 3),
        "picco_db": db(max(picchi)),
        "medio_db": db(math.sqrt(somma / blocchi) / 32768.0),
        "silenzio_ratio": round(sum(1 for p in picchi if p < 0.01) / blocchi, 3),
    }


def cuts_on_speech(store, clip_id: str, model_size: str = "small",
                   language: str | None = None, margin: float = 0.06) -> dict:
    """Verifica che i bordi di una clip non cadano in mezzo a una parola.

    E' l'errore piu' comune del taglio automatico e il piu' fastidioso da
    ascoltare: la parola mozzata si sente subito.
    """
    _, clip = store.clip_or_die(clip_id)
    if not clip.media:
        raise ValueError(f"la clip {clip_id} non ha un file sorgente")
    path = store.media_or_die(clip.media).path
    tr = analyze.transcribe(path, model_size, language)

    inizio, fine = clip.in_, clip.in_ + clip.source_duration()
    problemi = []
    for seg in tr["segments"]:
        for w in seg["words"]:
            for nome, t in (("attacco", inizio), ("stacco", fine)):
                if w["t"] + margin < t < w["e"] - margin:
                    problemi.append({
                        "dove": nome, "t": round(t, 3), "parola": w["w"],
                        "parola_inizio": w["t"], "parola_fine": w["e"],
                        "suggerito": round(w["t"] if nome == "attacco" else w["e"], 3),
                    })
    return {"ok": not problemi, "problemi": problemi}


# --------------------------------------------------------------------------
# verifica del render
# --------------------------------------------------------------------------


def expected_cuts(project, start: float, end: float) -> list[float]:
    """Gli stacchi che la timeline promette: i bordi delle clip nell'intervallo."""
    bordi = set()
    for track in project.tracks:
        if track.kind != "video" or getattr(track, "hidden", False):
            continue
        for c in track.clips:
            for t in (c.start, c.end):
                if start + 0.05 < t < end - 0.05:
                    bordi.add(round(t - start, 3))
    return sorted(bordi)


def verify(project, start: float | None = None, end: float | None = None,
           height: int = 270, keep: bool = False) -> dict:
    """Renderizza un tratto e controlla che sia quello che la timeline dichiara.

    Confronta stacchi attesi e stacchi misurati, la durata e i tratti neri o
    muti. E' la differenza tra "credo di aver montato" e "ho verificato".
    """
    a, b = _range(project, start, end)
    tmp = Path(tempfile.mkdtemp(prefix="vedit_verify_")) / "check.mp4"
    w = int(round(height * project.settings.width / project.settings.height))
    w += w % 2
    render.render(project, render.RenderOptions(
        output=str(tmp), start=a, end=b, quality="draft", width=w, height=height,
        use_proxy=True))

    misurati = [t for t in analyze.scenes(str(tmp), force=True) if t > 0.05]
    attesi = expected_cuts(project, a, b)
    trovati, mancanti = [], []
    residui = list(misurati)
    for t in attesi:
        vicino = min(residui, key=lambda x: abs(x - t), default=None)
        if vicino is not None and abs(vicino - t) <= CUT_TOLERANCE:
            trovati.append({"atteso": t, "misurato": vicino,
                            "scarto": round(vicino - t, 3)})
            residui.remove(vicino)
        else:
            mancanti.append(t)

    rep = analyze.report(str(tmp))
    m = rep["measures"]
    durata_attesa = round(b - a, 3)
    esito = {
        "durata_attesa": durata_attesa,
        "durata_misurata": rep["duration"],
        "stacchi_attesi": attesi,
        "stacchi_confermati": trovati,
        "stacchi_mancanti": mancanti,
        "stacchi_inattesi": [round(t, 3) for t in residui],
        "nero": m["black"], "muto": m["silence"], "fuori_fuoco": m["blurry"],
        "file": str(tmp) if keep else None,
    }
    avvisi = []
    if abs(rep["duration"] - durata_attesa) > 0.2:
        avvisi.append(f"durata diversa dal previsto: {rep['duration']}s invece di "
                      f"{durata_attesa}s")
    if mancanti:
        avvisi.append(f"{len(mancanti)} stacchi non si vedono nel render: due clip "
                      "adiacenti troppo simili, oppure una transizione li ha fusi")
    if m["black"] > 0.1:
        avvisi.append(f"nero per il {m['black'] * 100:.0f}% del tratto: buchi in timeline?")
    if m["silence"] > 0.9:
        avvisi.append("tratto praticamente muto")
    esito["avvisi"] = avvisi
    esito["ok"] = not avvisi
    if not keep:
        try:
            tmp.unlink()
        except OSError:
            pass
    return esito
