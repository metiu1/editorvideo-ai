"""Preset pronti all'uso: look, ritocchi audio e transizioni.

Il catalogo effetti (``effects.describe()``) elenca i mattoni con tutti i loro
parametri: utile per regolare, inutile per scegliere. Qui ci sono combinazioni
gia' tarate con un nome riconoscibile, raggruppate come nella libreria di un
montatore: si trascinano su una clip e basta.

Un preset e' solo una lista di effetti con i parametri gia' scelti, quindi
applicarlo equivale a chiamare ``add_effect`` una volta per effetto: niente
formato nuovo da mantenere e resta tutto modificabile dal pannello proprieta'.
"""

from __future__ import annotations

from .model import TRANSITIONS

# --------------------------------------------------------------------------
# look video
# --------------------------------------------------------------------------

LOOKS: list[dict] = [
    {
        "id": "cinema_teal_orange",
        "name": "Cinema teal & orange",
        "group": "Colore",
        "desc": "Ombre fredde, incarnati caldi: il look da trailer.",
        "effects": [
            {"type": "colorbalance", "params": {"bs": 0.14, "gs": 0.04, "rh": 0.12, "gh": 0.03}},
            {"type": "color", "params": {"contrast": 1.12, "saturation": 1.08}},
        ],
    },
    {
        "id": "bianco_e_nero",
        "name": "Bianco e nero",
        "group": "Colore",
        "desc": "Desaturazione totale con un po' di contrasto in piu'.",
        "effects": [{"type": "color", "params": {"saturation": 0.0, "contrast": 1.15}}],
    },
    {
        "id": "bn_contrastato",
        "name": "Bianco e nero contrastato",
        "group": "Colore",
        "desc": "Neri profondi, stile reportage.",
        "effects": [
            {"type": "color", "params": {"saturation": 0.0, "contrast": 1.45, "brightness": -0.04}},
            {"type": "grain", "params": {"strength": 8}},
        ],
    },
    {
        "id": "caldo_tramonto",
        "name": "Caldo tramonto",
        "group": "Colore",
        "desc": "Temperatura verso l'arancio, luce di fine giornata.",
        "effects": [
            {"type": "temperature", "params": {"temperature": 8200}},
            {"type": "color", "params": {"saturation": 1.12, "brightness": 0.03}},
        ],
    },
    {
        "id": "freddo_notturno",
        "name": "Freddo notturno",
        "group": "Colore",
        "desc": "Blu, contrasto alto: notte o interni al neon.",
        "effects": [
            {"type": "temperature", "params": {"temperature": 4200}},
            {"type": "color", "params": {"contrast": 1.2, "brightness": -0.06, "saturation": 0.9}},
        ],
    },
    {
        "id": "sbiadito_pellicola",
        "name": "Sbiadito pellicola",
        "group": "Colore",
        "desc": "Neri alzati e grana: sembra girato su pellicola.",
        "effects": [
            {"type": "curves", "params": {"preset": "lighter"}},
            {"type": "color", "params": {"saturation": 0.82, "contrast": 0.92}},
            {"type": "grain", "params": {"strength": 14}},
        ],
    },
    {
        "id": "vhs",
        "name": "VHS anni '90",
        "group": "Stilizzati",
        "desc": "Grana grossa, colori slavati, bordi morbidi.",
        "effects": [
            {"type": "color", "params": {"saturation": 0.75, "contrast": 1.1}},
            {"type": "blur", "params": {"sigma": 2}},
            {"type": "grain", "params": {"strength": 26}},
            {"type": "vignette", "params": {"angle": 0.9}},
        ],
    },
    {
        "id": "sogno",
        "name": "Sogno",
        "group": "Stilizzati",
        "desc": "Alone luminoso diffuso, ricordo o flashback.",
        "effects": [
            {"type": "glow", "params": {"amount": 0.55, "sigma": 16}},
            {"type": "color", "params": {"brightness": 0.06, "saturation": 0.9}},
        ],
    },
    {
        "id": "nitido",
        "name": "Nitido",
        "group": "Ritocco",
        "desc": "Dettaglio in piu' senza toccare i colori.",
        "effects": [{"type": "sharpen", "params": {"amount": 1.1}}],
    },
    {
        "id": "pulisci_ripresa",
        "name": "Pulisci ripresa",
        "group": "Ritocco",
        "desc": "Riduzione rumore e recupero di contrasto: girato in poca luce.",
        "effects": [
            {"type": "denoise", "params": {"strength": 4}},
            {"type": "color", "params": {"contrast": 1.08, "brightness": 0.04}},
        ],
    },
    {
        "id": "vignettatura",
        "name": "Vignettatura",
        "group": "Ritocco",
        "desc": "Bordi scuriti, lo sguardo va al centro.",
        "effects": [{"type": "vignette", "params": {"angle": 0.85}}],
    },
    {
        "id": "censura",
        "name": "Censura (pixel)",
        "group": "Stilizzati",
        "desc": "Mosaico su tutta l'immagine: volti o targhe.",
        "effects": [{"type": "pixelate", "params": {"size": 24}}],
    },
    {
        "id": "specchia",
        "name": "Specchia",
        "group": "Ritocco",
        "desc": "Ribalta in orizzontale: risolve le riprese speculari.",
        "effects": [{"type": "mirror", "params": {"horizontal": True}}],
    },
    {
        "id": "stabilizza",
        "name": "Stabilizza",
        "group": "Ritocco",
        "desc": "Toglie il tremolio della camera a mano. Render piu' lento.",
        "effects": [{"type": "stabilize", "params": {}}],
    },
]

# --------------------------------------------------------------------------
# catene audio
# --------------------------------------------------------------------------

AUDIO: list[dict] = [
    {
        "id": "voce_pulita",
        "name": "Voce pulita",
        "group": "Voce",
        "desc": "Taglia i bassi di rimbombo, comprime, riduce il fruscio.",
        "effects": [
            {"type": "highpass", "params": {"freq": 90}},
            {"type": "adenoise", "params": {"reduction": 10}},
            {"type": "compressor", "params": {"threshold": -20, "ratio": 3.5}},
        ],
    },
    {
        "id": "voce_radio",
        "name": "Voce radiofonica",
        "group": "Voce",
        "desc": "Compressione decisa e presenza sui medi.",
        "effects": [
            {"type": "highpass", "params": {"freq": 110}},
            {"type": "compressor", "params": {"threshold": -24, "ratio": 6}},
            {"type": "eq3", "params": {"mid": 3.5, "treble": 2.0}},
            {"type": "limiter", "params": {"limit": 0.9}},
        ],
    },
    {
        "id": "telefono",
        "name": "Telefono",
        "group": "Effetti",
        "desc": "Banda stretta: voce al telefono o alla radio.",
        "effects": [
            {"type": "highpass", "params": {"freq": 400}},
            {"type": "lowpass", "params": {"freq": 3000}},
        ],
    },
    {
        "id": "sala_grande",
        "name": "Sala grande",
        "group": "Effetti",
        "desc": "Riverbero ampio.",
        "effects": [{"type": "reverb", "params": {"amount": 0.4, "size": 0.8}}],
    },
    {
        "id": "eco",
        "name": "Eco",
        "group": "Effetti",
        "desc": "Ripetizione ritmica.",
        "effects": [{"type": "echo", "params": {"delay_ms": 350, "decay": 0.4}}],
    },
    {
        "id": "musica_sotto_voce",
        "name": "Musica sotto la voce",
        "group": "Musica",
        "desc": "Abbassa e scurisce la base perche' non copra il parlato.",
        "effects": [
            {"type": "lowpass", "params": {"freq": 9000}},
            {"type": "compressor", "params": {"threshold": -18, "ratio": 2.5}},
        ],
    },
    {
        "id": "volume_costante",
        "name": "Volume costante",
        "group": "Musica",
        "desc": "Normalizzazione dinamica: livella i punti troppo alti o bassi.",
        "effects": [{"type": "dynnorm", "params": {}}],
    },
]

# --------------------------------------------------------------------------
# transizioni
# --------------------------------------------------------------------------

_TR_META = {
    "dissolve": ("Dissolvenza", "Classica", "Una sfuma nell'altra.", 1.0),
    "iris": ("Iris", "Classica", "Cerchio che si apre dal centro.", 1.0),
    "wipe_right": ("Tendina ▸", "Tendina", "Scopre da sinistra a destra.", 0.8),
    "wipe_left": ("Tendina ◂", "Tendina", "Scopre da destra a sinistra.", 0.8),
    "wipe_down": ("Tendina ▾", "Tendina", "Scopre dall'alto.", 0.8),
    "wipe_up": ("Tendina ▴", "Tendina", "Scopre dal basso.", 0.8),
    "slide_left": ("Scorri ◂", "Scorrimento", "La clip esce verso sinistra.", 0.7),
    "slide_right": ("Scorri ▸", "Scorrimento", "La clip esce verso destra.", 0.7),
    "slide_up": ("Scorri ▴", "Scorrimento", "La clip esce verso l'alto.", 0.7),
    "slide_down": ("Scorri ▾", "Scorrimento", "La clip esce verso il basso.", 0.7),
}


def transitions() -> list[dict]:
    """Transizioni del motore con nome leggibile, gruppo e durata consigliata."""
    out = []
    for t in TRANSITIONS:
        name, group, desc, dur = _TR_META.get(t, (t, "Altro", "", 1.0))
        out.append({"id": t, "name": name, "group": group, "desc": desc, "duration": dur})
    return out


def describe() -> dict:
    """Libreria completa per la UI."""
    return {
        "video": LOOKS,
        "audio": AUDIO,
        "transitions": transitions(),
    }


def find(preset_id: str) -> dict | None:
    for p in LOOKS + AUDIO:
        if p["id"] == preset_id:
            return p
    return None
