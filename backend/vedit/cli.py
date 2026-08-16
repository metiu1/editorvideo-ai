"""Interfaccia da riga di comando.

Serve per le cose che si fanno meglio da terminale: creare un progetto, lanciare
un render, generare i proxy, controllare che il sistema sia a posto. Il montaggio
vero si fa dalla UI o dall'agente via MCP.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import effects as fx
from . import ffmpeg, hw, probe, proxy, render
from .store import EditError, Store


def _bar(state: dict) -> None:
    pct = state["percent"]
    filled = int(pct / 2.5)
    speed = state["seconds"] / state["elapsed"] if state["elapsed"] > 0 else 0
    sys.stdout.write(
        f"\r[{'#' * filled}{'.' * (40 - filled)}] {pct:5.1f}%  "
        f"{state['seconds']:.1f}/{state['duration']:.1f}s  {speed:.1f}x  "
    )
    sys.stdout.flush()


def cmd_new(a) -> int:
    s = Store.create(name=a.name or Path(a.path).stem, preset=a.preset, path=a.path)
    print(f"creato {s.path}  {s.project.settings.width}x{s.project.settings.height} "
          f"@{s.project.settings.fps}fps")
    return 0


def cmd_info(a) -> int:
    s = Store.open(a.project)
    if a.json:
        print(json.dumps(s.summary(a.detail), indent=2, ensure_ascii=False))
        return 0
    p = s.project
    print(f"{p.name}  {p.settings.width}x{p.settings.height}@{p.settings.fps}  "
          f"durata {p.duration():.2f}s")
    print(f"media ({len(p.media)}):")
    for m in p.media:
        print(f"  {m.id}  {m.kind:5}  {m.duration:7.2f}s  {m.name}")
    for t in p.tracks:
        flags = "".join(c for c, on in (("H", t.hidden), ("M", t.muted)) if on)
        print(f"traccia {t.id} [{t.kind}] {flags}")
        for c in sorted(t.clips, key=lambda x: x.start):
            extra = []
            if abs(c.speed - 1) > 1e-6:
                extra.append(f"{c.speed}x")
            if c.effects:
                extra.append("+".join(e.type for e in c.effects))
            print(f"  {c.id}  {c.start:7.2f} -> {c.end:7.2f}  {c.type:5} {c.name[:28]:28} "
                  f"{' '.join(extra)}")
    return 0


def cmd_import(a) -> int:
    s = Store.open(a.project)
    for m in s.import_media(a.files):
        print(f"{m.id}  {m.kind:5}  {m.duration:7.2f}s  {m.width}x{m.height}  {m.name}")
    return 0


def cmd_add(a) -> int:
    s = Store.open(a.project)
    c = s.add_clip(a.media, a.track, a.start, a.in_point, a.duration)
    print(f"{c.id}  {c.start:.2f} -> {c.end:.2f}")
    return 0


def cmd_render(a) -> int:
    s = Store.open(a.project)
    opts = render.RenderOptions(
        output=a.output, quality="draft" if a.preview else a.quality, codec=a.codec,
        start=a.start, end=a.end, bitrate=a.bitrate,
        width=960 if a.preview else a.width, use_proxy=a.preview or a.proxy,
        prefer_hw=not a.no_hw,
    )
    t0 = time.time()
    res = render.render(s.project, opts, on_progress=None if a.quiet else _bar)
    if not a.quiet:
        print()
    for w in res.warnings:
        print(f"avviso: {w}")
    print(f"{res.output}  {res.size / 1e6:.1f} MB  {res.duration:.2f}s di video  "
          f"in {time.time() - t0:.1f}s  ({res.encoder})")
    return 0


def cmd_frame(a) -> int:
    s = Store.open(a.project)
    print(render.render_frame(s.project, a.time, a.output, a.width, not a.no_proxy))
    return 0


def cmd_proxy(a) -> int:
    s = Store.open(a.project)
    done = proxy.ensure(s.project, a.height, a.force)
    s.save()
    print(f"{len(done)} proxy pronti a {a.height}p in {proxy.cache_dir('proxy')}")
    return 0


def cmd_effects(a) -> int:
    for e in fx.describe(a.kind):
        ps = ", ".join(
            f"{p['name']}={p['default']}" + ("*" if p["animatable"] else "")
            for p in e["params"]
        )
        print(f"{e['name']:14} [{e['kind']:5}] {e['label']}")
        if ps:
            print(f"               {ps}")
        if e["desc"]:
            print(f"               {e['desc']}")
    print("\n* = parametro animabile con keyframe")
    return 0


def cmd_probe(a) -> int:
    m = probe.probe(a.file)
    print(json.dumps({k: v for k, v in vars(m).items() if k != "id"}, indent=2, ensure_ascii=False))
    return 0


def cmd_normalize(a) -> int:
    s = Store.open(a.project)
    print("misuro il mix...")
    measured = render.measure_loudness(s.project)
    s.set_loudnorm(True, a.lufs, measured=measured)
    print(f"misurato {float(measured['input_i']):.1f} LUFS, "
          f"picco {float(measured['input_tp']):.1f} dBTP -> target {a.lufs} LUFS")
    return 0


def cmd_doctor(a) -> int:
    print(f"ffmpeg: {ffmpeg.version()}")
    info = hw.detect(force=a.force)
    for codec, enc in info.encoders.items():
        tag = "GPU" if info.is_hw(enc) else "CPU"
        print(f"  {codec:5} -> {enc:14} [{tag}]")
    if info.hwaccel:
        print(f"decodifica: {info.hwaccel} (provata insieme all'encoder qui sopra)")
    elif info.working:
        print("decodifica: software — nessun metodo hardware regge insieme all'encoder; "
              "la codifica resta su GPU, che e' la meta' che fa risparmiare tempo")
    else:
        print("decodifica: software (nessun metodo hardware ha superato la prova)")
    print(f"cache: {proxy.cache_dir()}")
    mancanti = [f for f in ("vidstabdetect", "rubberband", "loudnorm", "zoompan")
                if f not in ffmpeg.filters()]
    print("filtri mancanti: " + (", ".join(mancanti) if mancanti else "nessuno"))
    return 0


def cmd_ui(a) -> int:
    from .api import serve

    serve(host=a.host, port=a.port, project=a.project, open_browser=not a.no_browser)
    return 0


def cmd_mcp(a) -> int:
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vedit", description="Editor video da riga di comando")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="crea un progetto")
    n.add_argument("path")
    n.add_argument("--preset", default="1080p",
                   help="1080p, 1080p60, 4k, 720p, vertical, vertical60, square")
    n.add_argument("--name")
    n.set_defaults(func=cmd_new)

    i = sub.add_parser("info", help="mostra la timeline")
    i.add_argument("project")
    i.add_argument("--json", action="store_true")
    i.add_argument("--detail", default="normal", choices=["normal", "full"])
    i.set_defaults(func=cmd_info)

    im = sub.add_parser("import", help="importa file nel progetto")
    im.add_argument("project")
    im.add_argument("files", nargs="+")
    im.set_defaults(func=cmd_import)

    ad = sub.add_parser("add", help="aggiunge una clip in timeline")
    ad.add_argument("project")
    ad.add_argument("media", help="id del media (vedi 'vedit info')")
    ad.add_argument("--track")
    ad.add_argument("--start", type=float)
    ad.add_argument("--in-point", type=float, default=0.0, dest="in_point")
    ad.add_argument("--duration", type=float)
    ad.set_defaults(func=cmd_add)

    r = sub.add_parser("render", help="renderizza il progetto")
    r.add_argument("project")
    r.add_argument("output")
    r.add_argument("--quality", default="high", choices=["draft", "medium", "high", "max"])
    r.add_argument("--codec", default="h264", choices=["h264", "hevc", "av1", "vp9"])
    r.add_argument("--bitrate")
    r.add_argument("--width", type=int)
    r.add_argument("--start", type=float)
    r.add_argument("--end", type=float)
    r.add_argument("--preview", action="store_true", help="960px con proxy, per controllare")
    r.add_argument("--proxy", action="store_true", help="usa i proxy anche a qualita' piena")
    r.add_argument("--no-hw", action="store_true", help="forza la codifica su CPU")
    r.add_argument("--quiet", action="store_true")
    r.set_defaults(func=cmd_render)

    f = sub.add_parser("frame", help="estrae un fotogramma della timeline")
    f.add_argument("project")
    f.add_argument("time", type=float)
    f.add_argument("output")
    f.add_argument("--width", type=int, default=1280)
    f.add_argument("--no-proxy", action="store_true")
    f.set_defaults(func=cmd_frame)

    px = sub.add_parser("proxy", help="genera i proxy a bassa risoluzione")
    px.add_argument("project")
    px.add_argument("--height", type=int, default=540)
    px.add_argument("--force", action="store_true")
    px.set_defaults(func=cmd_proxy)

    e = sub.add_parser("effects", help="elenco effetti disponibili")
    e.add_argument("kind", nargs="?", choices=["video", "audio"])
    e.set_defaults(func=cmd_effects)

    pr = sub.add_parser("probe", help="metadati di un file")
    pr.add_argument("file")
    pr.set_defaults(func=cmd_probe)

    nm = sub.add_parser("normalize", help="normalizza l'audio del progetto (EBU R128)")
    nm.add_argument("project")
    nm.add_argument("--lufs", type=float, default=-14.0)
    nm.set_defaults(func=cmd_normalize)

    d = sub.add_parser("doctor", help="verifica ffmpeg e accelerazione hardware")
    d.add_argument("--force", action="store_true", help="rifa' il test degli encoder")
    d.set_defaults(func=cmd_doctor)

    u = sub.add_parser("ui", help="avvia l'interfaccia web")
    u.add_argument("--host", default="127.0.0.1")
    u.add_argument("--port", type=int, default=8760)
    u.add_argument("--project", help="progetto da aprire all'avvio")
    u.add_argument("--no-browser", action="store_true")
    u.set_defaults(func=cmd_ui)

    m = sub.add_parser("mcp", help="avvia il server MCP su stdio")
    m.set_defaults(func=cmd_mcp)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (EditError, ffmpeg.FFmpegError, FileNotFoundError, ValueError, KeyError) as exc:
        print(f"errore: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrotto", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
