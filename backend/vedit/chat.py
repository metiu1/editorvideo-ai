"""Assistente di montaggio dentro l'editor.

Le stesse operazioni che usa la UI (i metodi di ``Store``) vengono esposte a
Claude come strumenti: l'assistente non ha una strada privata per modificare il
progetto, fa esattamente quello che faresti tu cliccando. Ogni turno ritorna un
flusso di eventi che la UI mostra mentre arrivano.

Serve una credenziale Anthropic nell'ambiente (``ANTHROPIC_API_KEY``, oppure un
profilo creato con ``ant auth login``).
"""

from __future__ import annotations

import json
from typing import Any, Callable, Iterator

from . import presets

MODEL = "claude-opus-5"
# il ragionamento e' attivo di default su questo modello e pesa sullo stesso
# tetto della risposta: senza margine le risposte si troncano a meta'
MAX_TOKENS = 32000
MAX_TURNS = 12   # quanti giri di strumenti prima di fermarsi

SYSTEM = """Sei l'assistente di montaggio dentro vedit, un editor video non lineare.

Lavori sul progetto aperto usando gli strumenti: sono le stesse operazioni dei
pulsanti dell'interfaccia, quindi l'utente vede il risultato comparire in
timeline e puo' annullarlo con Ctrl+Z.

Come lavorare:
- Lo stato del progetto (media, tracce, clip con i loro id e tempi) ti viene
  passato a ogni turno. Usa quegli id, non inventarli. Se ti serve lo stato
  aggiornato dopo una modifica, chiama project_info.
- Fai il lavoro richiesto e basta: non aggiungere effetti, titoli o tagli che
  non sono stati chiesti. Se una richiesta e' ambigua in modo che cambierebbe
  il risultato, chiedi; per le scelte di poco conto decidi tu e dillo.
- I tempi sono in secondi dall'inizio della timeline. La durata delle clip e'
  in timeline, non nella sorgente.
- Per un "look" o una catena audio preferisci apply_preset: sono combinazioni
  gia' tarate. add_effect serve quando serve un parametro preciso.
- Se un'operazione fallisce, leggi l'errore e correggi invece di ripeterla.

Rispondi in italiano, in modo breve. Dopo aver modificato la timeline di' in una
frase cosa hai fatto, senza rielencare ogni chiamata."""


# --------------------------------------------------------------------------
# strumenti
# --------------------------------------------------------------------------

def _tool(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"name": name, "description": desc,
            "input_schema": {"type": "object", "properties": props, "required": required}}


_NUM = {"type": "number"}
_STR = {"type": "string"}


def build_tools() -> list[dict]:
    look_ids = [p["id"] for p in presets.LOOKS + presets.AUDIO]
    tr_ids = [t["id"] for t in presets.transitions()]
    return [
        _tool("project_info",
              "Stato aggiornato della timeline: media, tracce, clip con id, tempi ed "
              "effetti. Chiamalo quando ti serve verificare il risultato di una modifica "
              "o quando non hai un id che ti serve.",
              {}, []),
        _tool("import_media",
              "Aggiunge file dal disco al progetto (non li mette in timeline). "
              "Usalo solo con percorsi che l'utente ha indicato.",
              {"paths": {"type": "array", "items": _STR}}, ["paths"]),
        _tool("add_clip",
              "Mette un media in timeline. start assente = accoda alla fine della traccia.",
              {"media_id": _STR, "track_id": _STR, "start": _NUM,
               "in_": {**_NUM, "description": "punto di attacco nella sorgente"},
               "duration": _NUM}, ["media_id"]),
        _tool("add_text",
              "Aggiunge un titolo in sovrimpressione sulla traccia video.",
              {"text": _STR, "start": _NUM, "duration": _NUM,
               "font_size": {"type": "integer"}, "color": _STR,
               "box": {"type": "boolean", "description": "riquadro dietro al testo"}},
              ["text"]),
        _tool("split_clip",
              "Taglia una clip in due al tempo di timeline indicato.",
              {"clip_id": _STR, "at": _NUM}, ["clip_id", "at"]),
        _tool("remove_clip",
              "Elimina una clip. ripple=true chiude anche il buco che lascia.",
              {"clip_id": _STR, "ripple": {"type": "boolean"}}, ["clip_id"]),
        _tool("move_clip",
              "Sposta una clip nel tempo e/o su un'altra traccia.",
              {"clip_id": _STR, "start": _NUM, "track_id": _STR}, ["clip_id"]),
        _tool("trim_clip",
              "Cambia attacco e durata di una clip senza spostarla.",
              {"clip_id": _STR, "in_": _NUM, "duration": _NUM}, ["clip_id"]),
        _tool("set_speed",
              "Cambia la velocita' di una clip. 2 = doppia, 0.5 = slow motion.",
              {"clip_id": _STR, "speed": _NUM}, ["clip_id", "speed"]),
        _tool("set_fades",
              "Dissolvenza in entrata e/o in uscita, in secondi.",
              {"clip_id": _STR, "fade_in": _NUM, "fade_out": _NUM}, ["clip_id"]),
        _tool("crossfade",
              "Transizione tra due clip consecutive della stessa traccia: accosta B ad A "
              "e le sovrappone. E' il modo giusto quando le clip sono attaccate.",
              {"clip_a": _STR, "clip_b": _STR, "duration": _NUM,
               "type": {"type": "string", "enum": tr_ids}}, ["clip_a", "clip_b"]),
        _tool("set_transition",
              "Cambia la transizione in uscita di una clip senza spostare niente. "
              "Usalo quando le clip si sovrappongono gia'.",
              {"clip_id": _STR, "type": {"type": "string", "enum": tr_ids}, "duration": _NUM},
              ["clip_id"]),
        _tool("apply_preset",
              "Applica un look video o una catena audio gia' tarata. Preferiscilo a "
              "add_effect quando la richiesta e' di stile ('piu' cinematografico', "
              "'voce piu' pulita') invece che di un parametro preciso. "
              "clip_id assente = applica al master, cioe' a tutto il video.",
              {"preset_id": {"type": "string", "enum": look_ids}, "clip_id": _STR},
              ["preset_id"]),
        _tool("add_effect",
              "Applica un singolo effetto con parametri espliciti. clip_id assente = master.",
              {"effect": _STR, "params": {"type": "object"}, "clip_id": _STR}, ["effect"]),
        _tool("set_transform",
              "Posizione, scala, rotazione e opacita' della clip sul canvas. x/y in pixel "
              "dal centro, scale 1 = naturale. Ogni valore accetta anche keyframe: "
              "{\"kf\":[{\"t\":0,\"v\":1},{\"t\":3,\"v\":1.2}]} con t relativo all'inizio clip.",
              {"clip_id": _STR, "x": {}, "y": {}, "scale": {}, "rotation": {}, "opacity": {}},
              ["clip_id"]),
        _tool("set_audio",
              "Volume in dB, muto, pan e dissolvenze audio di una clip.",
              {"clip_id": _STR, "gain_db": {}, "mute": {"type": "boolean"},
               "pan": _NUM, "fade_in": _NUM, "fade_out": _NUM}, ["clip_id"]),
        _tool("set_text",
              "Cambia il testo o lo stile di una clip di tipo testo.",
              {"clip_id": _STR, "text": _STR, "font_size": {"type": "integer"},
               "color": _STR, "box": {"type": "boolean"}}, ["clip_id"]),
        _tool("add_track",
              "Aggiunge una traccia video o audio. Serve ogni volta che due cose devono "
              "stare insieme nello stesso istante: un titolo sopra una ripresa, un "
              "riquadro PiP, musica sotto il parlato, un secondo microfono. Le tracce "
              "video si sovrappongono: l'ultima della lista sta sopra tutte.",
              {"kind": {"type": "string", "enum": ["video", "audio"]}, "name": _STR},
              ["kind"]),
        _tool("set_track",
              "Stato di una traccia: name, hidden (nasconde il video), muted (silenzia), "
              "solo (isola: le altre tacciono), locked (protegge dalle modifiche), "
              "volume (1 = invariato). E' anche l'unico modo di sbloccare una traccia.",
              {"track_id": _STR, "name": _STR, "hidden": {"type": "boolean"},
               "muted": {"type": "boolean"}, "solo": {"type": "boolean"},
               "locked": {"type": "boolean"}, "volume": {}}, ["track_id"]),
        _tool("move_track",
              "Cambia l'ordine di una traccia tra quelle dello stesso tipo. Per il video "
              "l'ordine e' la sovrapposizione: indice 0 sta sotto, l'ultimo sta sopra. "
              "Usalo quando un titolo o un PiP finisce dietro invece che davanti.",
              {"track_id": _STR, "index": {"type": "integer"}}, ["track_id", "index"]),
        _tool("remove_track",
              "Elimina una traccia con tutte le sue clip. Chiedi conferma se non e' vuota.",
              {"track_id": _STR}, ["track_id"]),
        _tool("close_gaps",
              "Compatta una traccia eliminando i buchi tra le clip.",
              {"track_id": _STR}, ["track_id"]),
        _tool("undo", "Annulla l'ultima modifica.", {}, []),
    ]


# --------------------------------------------------------------------------
# esecuzione
# --------------------------------------------------------------------------

# strumenti che non sono metodi di Store
_SPECIAL = {"project_info", "apply_preset"}


def execute(store: Any, name: str, args: dict) -> str:
    """Esegue uno strumento sul progetto e descrive il risultato a parole."""
    from .model import to_dict

    if name == "project_info":
        return json.dumps(store.summary("full"), ensure_ascii=False)

    if name == "apply_preset":
        p = presets.find(args["preset_id"])
        if p is None:
            raise ValueError(f"preset sconosciuto: {args['preset_id']}")
        clip_id = args.get("clip_id")
        store.add_effects(clip_id, p["effects"])
        dove = f"clip {clip_id}" if clip_id else "master"
        return f"preset '{p['name']}' applicato a {dove} ({len(p['effects'])} effetti)"

    result = getattr(store, name)(**args)
    if result is None:
        return "fatto"
    if isinstance(result, (str, int, float, bool)):
        return str(result)
    if isinstance(result, (list, tuple)):
        return json.dumps([to_dict(r) if hasattr(r, "__dataclass_fields__") else r
                           for r in result], ensure_ascii=False, default=str)
    if hasattr(result, "__dataclass_fields__"):
        return json.dumps(to_dict(result), ensure_ascii=False, default=str)
    return json.dumps(result, ensure_ascii=False, default=str)


class ChatUnavailable(RuntimeError):
    """Manca la credenziale o il pacchetto: e' un problema di setup, non un bug."""


def client():
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - dipende dall'ambiente
        raise ChatUnavailable(
            "il pacchetto 'anthropic' non e' installato: pip install anthropic"
        ) from exc
    cl = anthropic.Anthropic()
    # il costruttore non protesta se manca la chiave: fallirebbe alla prima
    # richiesta, e la UI mostrerebbe la chat come se funzionasse
    if not getattr(cl, "api_key", None) and not getattr(cl, "auth_token", None):
        raise ChatUnavailable(
            "nessuna credenziale Anthropic: imposta ANTHROPIC_API_KEY nell'ambiente "
            "e riavvia vedit ui"
        )
    return cl


def _state_block(store: Any) -> str:
    return ("Stato attuale del progetto (usa questi id):\n"
            + json.dumps(store.summary("full"), ensure_ascii=False))


def run(store: Any, history: list[dict], question: str,
        run_op: Callable[[str, dict], str]) -> Iterator[dict]:
    """Un turno di conversazione. Restituisce eventi man mano che arrivano.

    ``history`` viene esteso sul posto, cosi' il chiamante conserva i blocchi
    ``tool_use``/``tool_result`` che i turni successivi devono rimandare intatti.
    """
    cl = client()
    tools = build_tools()

    # Lo stato va nel turno utente, non nel prompt di sistema: cosi' il prefisso
    # resta identico tra un turno e l'altro e la cache non viene invalidata.
    history.append({"role": "user", "content": [
        {"type": "text", "text": _state_block(store)},
        {"type": "text", "text": question},
    ]})

    for _ in range(MAX_TURNS):
        try:
            with cl.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM,
                tools=tools,
                messages=history,
                extra_body={"output_config": {"effort": "high"}},
            ) as stream:
                for event in stream:
                    if event.type == "content_block_start" and event.content_block.type == "thinking":
                        yield {"type": "thinking"}
                    elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield {"type": "text", "text": event.delta.text}
                message = stream.get_final_message()
        except ChatUnavailable:
            raise
        except Exception as exc:  # errori di rete, credenziali, rate limit
            yield {"type": "error", "message": str(exc)}
            return

        history.append({"role": "assistant", "content": message.content})

        if message.stop_reason == "refusal":
            yield {"type": "error", "message": "la richiesta e' stata rifiutata"}
            return
        if message.stop_reason != "tool_use":
            yield {"type": "done"}
            return

        results = []
        for block in message.content:
            if block.type != "tool_use":
                continue
            yield {"type": "tool", "name": block.name, "input": block.input}
            try:
                out = run_op(block.name, dict(block.input))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                yield {"type": "tool_done", "name": block.name}
            except Exception as exc:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": f"errore: {exc}", "is_error": True})
                yield {"type": "tool_error", "name": block.name, "message": str(exc)}
        history.append({"role": "user", "content": results})

    yield {"type": "error", "message": f"fermato dopo {MAX_TURNS} giri di strumenti"}
