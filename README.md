# vedit

**A non-linear video editor an AI agent can actually drive** — web timeline, chat assistant
and MCP server on one deterministic ffmpeg engine. Python + React, Windows / macOS / Linux,
MIT.

### Editing eats your time. This gives it back.

Cutting a two-minute video is twenty minutes of work and two hours of dragging rectangles:
finding the good take inside forty minutes of footage, trimming frame by frame, matching the
cuts to the music, tweaking the same volume curve for the tenth time. None of that is a
creative decision. All of it is time.

vedit is a real non-linear video editor whose entire project is a JSON document, and whose
render is a pure function of that document compiled into a single ffmpeg `filter_complex`.
That one design choice is what lets you drive it **three ways at once** — a web timeline you
edit by hand, a chat assistant inside the editor, and an **MCP server** so a coding agent
(Claude Code, Cursor, Codex…) can cut the video for you while you watch the timeline move.

```bash
claude mcp add vedit -- uvx vedit-mcp     # that is the whole install
```

![vedit demo](docs/vedit-demo.gif)

[![ci](https://github.com/metiu1/editorvideo-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/metiu1/editorvideo-ai/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/vedit-mcp.svg)](https://pypi.org/project/vedit-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/vedit-mcp.svg)](https://pypi.org/project/vedit-mcp/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> 🇮🇹 Questo README in italiano: [README.it.md](README.it.md). Code, comments and UI messages
> are in Italian — that is the project convention.

---

## Why this exists

Most "AI video" tools generate a video for you and give you back a file you cannot fix.
An editor gives you every knob and none of the time back.

vedit sits in the middle, and it does so honestly:

| | |
|---|---|
| **An agent can actually edit** | 77 MCP tools that are the *same* operations as the buttons: cut, split, speed, keyframes, effects, transitions, render. Nothing is agent-only, nothing is UI-only. |
| **The agent can see what it did** | `preview_frame` returns the **real rendered frame**, `preview_grid` the whole edit as a contact sheet. An agent that guesses produces garbage; this one looks. |
| **It cuts on the beat, for real** | `music_beats` returns BPM, beat and bar length, first-beat offset and an energy profile, so cuts land on the music instead of near it. |
| **It picks the takes** | `plan_edit` splits shots longer than 12s into their own segments and scores them individually — three minutes of continuous footage becomes dozens of candidates with a real in-point. |
| **Same project, same file** | The render is deterministic. No hidden state, no "works in the preview, breaks on export". |
| **You keep the timeline** | Whatever the agent does shows up in the web UI, on the same in-memory project, and undoes with one Ctrl+Z. |

---

## Table of contents

- [Install](#install)
- [Quick start](#quick-start)
- [Driving it from an agent (MCP)](#driving-it-from-an-agent-mcp)
- [The web interface, panel by panel](#the-web-interface-panel-by-panel)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Command line](#command-line)
- [What it can do](#what-it-can-do)
- [Keyframes](#keyframes)
- [How it works](#how-it-works)
- [Tests](#tests)
- [Known limits](#known-limits)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)

---

## Install

### Just to use it — nothing to clone

The package is on PyPI as **`vedit-mcp`** (the name `vedit` was taken; the Python module is
still `vedit`). The compiled web interface ships **inside the package**, so there is no build
step:

```bash
claude mcp add vedit -- uvx vedit-mcp        # Claude Code: one line
uvx --from vedit-mcp vedit ui                # or just the web editor
```

Same JSON for every other client (Cursor `.cursor/mcp.json`, Codex, VS Code):

```json
{ "mcpServers": { "vedit": { "command": "uvx", "args": ["vedit-mcp"] } } }
```

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) (`pipx install uv`,
`winget install astral-sh.uv`, `brew install uv`). Prefer a classic install?
`pipx install vedit-mcp`, then `vedit` and `vedit-mcp` are on your `PATH`.

**ffmpeg** is the one thing pip cannot bring along — it is a program, not a Python package.
If it is missing, don't go hunting: `vedit install-ffmpeg` downloads a static build of ffmpeg
*and* ffprobe into `~/.vedit/bin`. No administrator rights, no system changes, uninstalled by
deleting the folder. The agent has the same thing as the `install_ffmpeg` tool. If ffmpeg is
already on your `PATH`, that one wins — it usually has more hardware encoders.

### To hack on it — one command

```bash
git clone https://github.com/metiu1/editorvideo-ai.git
cd editorvideo-ai
python scripts/setup.py
```

The script does everything: Python dependencies, compiled web interface, MCP server
registered, then `vedit doctor` and the fast tests as verification. It prints one line per
step and ends by telling you what is still missing and how to fix it. Re-running it is safe —
anything already in place is skipped.

```bash
python scripts/setup.py --venv             # dependencies in .venv instead of the current interpreter
python scripts/setup.py --install-ffmpeg   # try winget / brew / apt
python scripts/setup.py --no-frontend      # CLI and MCP only, no web interface
python scripts/setup.py --rebuild          # rebuild the UI after touching frontend/src
python scripts/setup.py --json             # machine-readable result, for scripts and agents
```

Then `vedit ui` → <http://127.0.0.1:8760>.

### Requirements

| | |
|---|---|
| Python | 3.10+ |
| ffmpeg + ffprobe | on `PATH`, downloaded with `vedit install-ffmpeg`, or pointed at with `VEDIT_FFMPEG` / `VEDIT_FFPROBE` |
| Node.js | 18+, **only** to compile the interface from source the first time |
| GPU | optional. NVIDIA / Intel / AMD are detected and used for rendering automatically |

### Optional extras

Everything below is optional; without them the rest of the editor behaves identically and the
tools that need them say what to install.

```bash
pip install -e ".[chat]"        # anthropic — the chat assistant inside the UI (+ ANTHROPIC_API_KEY)
pip install -e ".[vision]"      # ultralytics — detect_subjects, track_mask, auto_reframe (pulls torch)
pip install -e ".[transcribe]"  # faster-whisper — transcribe, make_captions, tighten_speech, censor_speech
```

`numpy` and Pillow are **not** extras: footage analysis, music-timed editing, `preview_grid`
and `color_scopes` stand on them, and looking at your edit is rule number one.

---

## Quick start

End to end, three commands:

```bash
vedit new film.json --preset 1080p
vedit import film.json shots/*.mp4 music.mp3 && vedit info film.json   # prints media ids
vedit add film.json <media_id> --duration 3 && vedit render film.json out.mp4
```

Or open the editor and do it by hand:

```bash
vedit ui                                     # http://127.0.0.1:8760
vedit ui --project film.json                 # opening a project directly
vedit ui --port 9000 --no-browser
```

The `.json` **is** the project: your video files stay where they are, nothing is copied.
Format presets: `1080p`, `1080p60`, `4k`, `720p`, `vertical` (9:16, for reels and shorts),
`vertical60`, `square`.

---

## Driving it from an agent (MCP)

`.mcp.json` is already in the repo, so opening this folder in Claude Code offers the `vedit`
server on first launch (approve it once). Anywhere else:

```bash
claude mcp add vedit -- uvx vedit-mcp
```

Typical tool flow:

```
project_create → import_media → plan_edit (choose the material) → add_clips
   → refine (set_transition, set_speed, set_transform, add_effect, set_audio)
   → preview_grid to look at it → render_video
```

Times are in seconds. Every animatable parameter also accepts a keyframe block —
`{"kf": [{"t": 0, "v": 0}, {"t": 2, "v": 1, "ease": "ease_in_out"}]}`, with `t` relative to
the start of the clip. `project_info` returns the timeline state with ids.

**Cutting many clips:** use `add_clips`, which places all cuts in a single atomic call. One
call per cut is slow, floods the undo history for what is one gesture, and leaves half a
timeline behind if something breaks midway.

```json
[{"media": "m1b1a", "start": 0.0, "in": 122.5, "duration": 1.5},
 {"media": "m9155", "start": 1.5, "in": 98.5,  "duration": 0.75}]
```

**Showing the result:** `open_ui` starts the web interface **inside the MCP server process**
and returns the address. It is not a second instance — the UI works on the *same* `Store`
object as the agent, and every change shows up in the browser live. One writer, no file
contention. `close_ui` shuts it down.

**The editing rules ship with the server.** `mcp_server.ISTRUZIONI` states them, so they reach
any client, and they are there because they are the actual defects of videos that come out of
here — decisions not made, not tool limits:

1. **the music must move** — a fixed volume for the whole duration is the first thing that
   makes a video feel flat; automate the gain with keyframes and pick the section with
   `music_beats`;
2. **not every cut is a hard cut** — the hard cut is the default, not the only option; every
   transition still needs a reason;
3. **never the same shot twice** — if the material is not enough, make the video shorter;
4. **after ten seconds you owe the viewer new information** — cutting faster on the same
   images saves nothing;
5. **cinematic is a choice, not a filter** — one strong moment held for three seconds beats
   ten half-seconds.

Full agent contract, including the code map and the rules for modifying it:
[`AGENTS.md`](AGENTS.md) (imported by `CLAUDE.md`, so it applies to Claude Code, Codex, Cursor
and the rest).

> **One project per file at a time.** The UI and the MCP server both autosave; if you keep the
> same `.json` open in two processes, the last one to save wins. With `open_ui` the problem
> does not arise.

---

## The web interface, panel by panel

```
┌──────────────────────────────────────────────────────────────────────┐
│  bar: new · open · save · ↶↷ · +video +audio +text · export          │
├───────────────┬──────────────────────────────────┬───────────────────┤
│ media         │  program / source                │ properties        │
│ library       │  ┌────────────────────────────┐  │ assistant         │
│               │  │        preview             │  │                   │
│  (tabs)       │  └────────────────────────────┘  │   (tabs)          │
│               │  ▶ ⏮  0:01.2/0:13.0  zoom tracks │                   │
│               ├──────────────────────────────────┤                   │
│               │  timeline: V3 V2 V1 A1 …         │                   │
└───────────────┴──────────────────────────────────┴───────────────────┘
```

Panels resize by dragging the dividers, and the sizes are remembered.

**1. Media.** `+` imports files *leaving them where they are*. Dragging files from the desktop
**copies** them into `media/` next to the project (the browser does not hand over the source
path) — for heavy files use `+`. `📁+` creates a folder, which is just a label on the media.
Click opens a media in the *source* monitor, double click appends it to the timeline, drag
puts it exactly where you want.

**2. Library.** Pre-tuned looks, audio chains and transitions, with a name instead of twenty
parameters: colour looks (cinema teal & orange, black and white, warm sunset, faded film…),
stylised (VHS, dream, censor), retouch (sharpen, clean up, vignette, stabilise); voice and
music chains; dissolve, iris, wipe and slide in four directions. Click applies to the selected
clip — a video look with nothing selected goes on the **master**, i.e. the whole video. Drag a
preset **onto a clip** to apply it there. A preset is only a chain of effects: one Ctrl+Z
undoes it and every parameter stays editable.

**3. Monitor and preview.** Two tabs: *program* (the timeline) and *source* (one media alone).
When paused, the preview is the frame **rendered by ffmpeg**, so it is identical to the final
result, effects included. ▶ plays 12-second segments while preparing the next one in the
background; hit **proxy** in the top bar to make everything much faster. With a clip selected
you get the transform box: drag the image to move it, the corners to scale it. In the *source*
monitor, `[` and `]` mark in and out, then **insert** puts just that piece at the playhead.

**4. Timeline and tracks.** Track count is **not fixed**: a new project has one video and one
audio track, and you add more with `+ video` / `+ audio`. Every track header carries: rename
(double click), ▲▼ to reorder (for video, order **is** the stacking — higher = drawn on top),
👁/🔊 hide or mute, **S** for solo, 🔒 lock (protects clips from moves, cuts, effects and
deletion), ✕ delete, and a volume slider. A track excluded from the render is visibly faded
with a struck-through name; a locked one is hatched. Clips drag between tracks, edges trim,
snapping catches other clips and the playhead, video clips show filmstrips and audio clips
their waveform.

**5. Properties.** With a clip selected: name, start, duration, in-point, framing, speed and
reverse, fades, outgoing transition, position / scale / rotation / opacity, audio (gain in dB,
pan, fades), effects. The **◆** button next to a parameter makes it **animated** and opens the
keyframe editor, with times relative to the start of the clip. With nothing selected you get
the project: resolution, fps, background, EBU R128 normalisation of the mix, master effects.

**6. Assistant.** Ask for a change in plain language and it happens on the project — "drop the
first 2 seconds of the first clip", "dissolve between the two shots", "move the music to its
own track and take it down 6 dB". Its tools **are the same operations as the buttons**: what it
does appears in the timeline and undoes with Ctrl+Z, exactly like your own edit. Requires
`ANTHROPIC_API_KEY`; without it, the tab explains why it is off and nothing else is affected.

**7. Export.** Destination file, quality (`draft` / `medium` / `high` / `max`), codec (H.264,
HEVC, AV1, VP9), optionally just a portion of the timeline. The extension picks the container:
`.mp4` `.mov` `.mkv` `.webm` `.gif` `.mp3` `.wav`. The progress bar is ffmpeg's real progress.
The final render **always uses the originals**, never the proxies.

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `space` | play / pause |
| `←` `→` | one frame (with `shift`: one second) |
| `Home` / `End` | start / end |
| `S` | split at the playhead |
| `Del` | delete the clip (with `shift`: close the gap) |
| `Ctrl+Z` / `Ctrl+Y` | undo / redo |
| `+` `-` | timeline zoom |

---

## Command line

Everything the interface does is also available in the terminal, on the same project file.

```bash
vedit new project.json --preset 1080p
vedit import project.json shots/*.mp4 music.mp3
vedit info project.json                  # media and timeline with ids
vedit add project.json m1a2b3c4 --duration 8
vedit proxy project.json                 # 540p proxies: much faster previews
vedit frame project.json 12.5 check.jpg
vedit normalize project.json --lufs -14
vedit render project.json final.mp4 --quality high
vedit effects video                      # effect catalogue with parameters
vedit doctor                             # ffmpeg, encoders, filters
vedit install-ffmpeg                     # download ffmpeg + ffprobe into ~/.vedit/bin
vedit ui                                 # web interface
```

---

## What it can do

**Editing** — cut, split, trim, move (across tracks too), ripple delete, close gaps, any number
of video and audio tracks with ordering, solo and lock, bin folders, undo/redo.

**Transitions** — dissolve, wipe in four directions, slide in four directions, iris. The next
clip is pulled in and overlapped automatically; audio always crossfades.

**Speed** — 0.01x to 100x with pitch-correct audio (chained `atempo`), reverse, motion blur or
frame interpolation for slow motion.

**Colour** — brightness, contrast, saturation, gamma (all animatable), shadow/midtone/highlight
balance, temperature, curves, `.cube` LUTs, `match_color` between shots, `color_scopes`.

**Composition** — position, scale, rotation and opacity per clip, all animatable with keyframes
and easing; PiP, graphic overlays, text with box/outline/shadow, chroma key, crop, mirror,
pixelate, vignette, grain, glow, stabilisation.

**Audio** — gain in dB (animatable), pan, fades, EQ, compressor, limiter, noise reduction, gate,
reverb, echo, pitch shift, dynamic normalisation, and two-pass EBU R128 normalisation of the
mix; `duck_music`, `jl_cut`, `detach_audio`.

**Footage and rhythm** — `plan_edit` (segment and score the takes), `inspect_footage`,
`music_beats` (BPM, bars, energy profile, cut grid), `check_cuts`, `smooth_cuts`,
`preview_grid`, `verify_edit`.

**Speech and subject** *(extras)* — `transcribe`, `make_captions`, `tighten_speech`,
`censor_speech`; `detect_subjects`, `track_mask`, `auto_reframe`.

---

## Keyframes

Any animatable parameter accepts a keyframe block instead of a number:

```json
{"kf": [{"t": 0, "v": 1.0, "ease": "ease_in_out"}, {"t": 3, "v": 1.4}]}
```

`t` is **relative to the start of the clip**. Easing: `linear`, `hold`, `ease_in`, `ease_out`,
`ease_in_out` and the `_cubic` variants.

Keyframes become ffmpeg expressions evaluated frame by frame, so animation does not cost an
extra render pass.

---

## How it works

```
backend/vedit/
  model.py       project document (dataclass ↔ JSON)
  keyframes.py   keyframes → ffmpeg expressions
  effects.py     effect registry: parameters, validation, filters
  presets.py     pre-tuned looks, audio chains and transitions
  graph.py       timeline → filter_complex
  render.py      execution, progress, analysis (loudness, stabilisation)
  proxy.py       proxies, waveforms, thumbnails
  store.py       editing operations + undo/redo + atomic save
  chat.py        assistant: its tools are Store's operations
  mcp_server.py  MCP tools
  api.py         REST/WebSocket API for the UI
  cli.py         command line
frontend/        web interface (React + Vite)
tests/           tests, including real renders of every effect
```

**One source of truth.** The interface, the assistant and the MCP agent all call methods on
`Store`. There is no privileged path for modifying the project, so there is no "works from
here, breaks from there". Add an operation to `store.py` first, then expose it where needed —
never write into the document from `api.py`, `mcp_server.py` or `cli.py`.

The less obvious choices, and why:

- **Composition**: a canvas plus one `overlay` per clip. Handles multi-track, PiP and
  dissolves with no special cases.
- **Placement**: `tpad` with transparent frames instead of shifting PTS, so `overlay` never
  sits waiting for frames.
- **Draw order**: video tracks stack in list order. Inside a track the clip that starts first
  is on top (so its outgoing transition reveals the next one); titles and solid colours are the
  exception and always sit above media.
- **Preview**: `slice_project` cuts out the requested portion, so rendering second 300 costs no
  more than second 3. Sliced clips keep their original timing, so a dissolve framed halfway
  shows the right frame — there is a test comparing preview against final render.
- **Transitions**: they exploit the draw order. Wipes and iris erase pixels of the outgoing
  clip with a `geq` alpha mask; slides add a term to the overlay's `x`/`y` expressions. No
  second branch in the graph, no extra composition cost.
- **Filmstrips**: one image per media (`tile`), positioned with CSS from in-point, speed and
  zoom. Zooming the timeline issues no requests at all.
- **Preview cache**: every frame and segment is written to a temporary file and moved into
  place only when finished. Otherwise the player would get an mp4 with no `moov` atom yet and
  playback would not start.
- **Saving**: same idea, atomic `os.replace`. An interruption cannot leave a truncated project.
- **Filtergraph from file** (`-filter_complex_script`): long timelines blow past Windows'
  32k command-line limit.

---

## Tests

```bash
pytest                  # everything, real renders included (3–5 min)
pytest -m "not slow"    # logic and API, no renders (2–3 min)

cd frontend
node test-util.mjs                       # pure UI functions
npm run build && node smoke.mjs          # mounts the built UI in jsdom
```

**ffmpeg is needed even by the fast tests**: `tests/conftest.py` generates synthetic sources
with it, and half the suite reads media with ffprobe. The `slow` marker separates real
*renders*, not the use of ffmpeg.

The suite covers keyframes, editing operations, graph compilation, a real render for each
effect and each transition, preview-versus-final-render agreement, MCP tools, the UI API and
the command line. `tests/test_dipendenze.py` reads the backend's imports and requires each one
to be declared in `pyproject.toml`, so a package that happens to sit on a developer's machine
cannot silently go missing from the wheel.

---

## Known limits

- Animated opacity and wipes use `geq` (per-pixel evaluation): they work, but they slow the
  render down. Dissolves and slides do not carry that cost.
- Animated scale goes through `zoompan`: below 0.25x the value is clamped.
- Preview playback is segmented: the first segment has to be waited for, the following ones are
  prepared while you watch.
- Files dragged from the desktop are copied (the browser does not pass the source path); for
  large files use the import button.
- The transform box does not edit animated parameters — for those, use the keyframes.
- If two processes hold the same `.json` open, one autosave can overwrite the other's work.
  There is no project-file lock yet.

---

## FAQ

**Does it upload my footage anywhere?**
No. Everything runs on your machine: ffmpeg does the work, the project is a local `.json`, the
media never leaves the folder it is in. The only thing that talks to the network is the
optional chat assistant (your own Anthropic key) and `install-ffmpeg`, which downloads ffmpeg.

**Do I need a GPU?**
No. If you have one (NVIDIA / Intel / AMD) it is detected and used for encoding automatically;
without one everything still works, renders just take longer.

**Which agents can drive it?**
Any MCP client: Claude Code, Claude Desktop, Cursor, Codex, VS Code, or your own via the MCP
SDK. `claude mcp add vedit -- uvx vedit-mcp`, or the equivalent JSON in the client's config.

**Is this "AI generated video"?**
No. Nothing is generated — it edits *your* footage with ffmpeg. The AI part is the agent
deciding *where to cut*, and you can see and undo every decision in the timeline.

**Does the agent edit blind?**
It doesn't have to: `preview_frame` returns the real rendered frame and `preview_grid` the
whole edit as a contact sheet, so the agent looks at its own work before rendering.

**What if ffmpeg is missing?**
`vedit install-ffmpeg` puts a static ffmpeg + ffprobe in `~/.vedit/bin`. No admin rights, no
system changes, removed by deleting the folder.

**Can I use it without the agent, as a normal editor?**
Yes — `vedit ui` is a full timeline editor with tracks, keyframes, effects and export. MCP is
one of three front ends, not a requirement.

---

## Contributing

Issues and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). In short:

- read [`AGENTS.md`](AGENTS.md) — it is the contract for humans and coding agents alike;
- code, comments and user-facing messages are **in Italian**, like the rest of the project
  (this README and the docs are the English front door);
- every new behaviour comes with a test; real renders go behind the `slow` marker;
- new effect → `effects.py`; new MCP tool → a method in `store.py`, a wrapper in
  `mcp_server.py`, a test in `tests/test_mcp.py`; UI change → `npm run build`;
- before claiming it works: `pytest -m "not slow"` plus the part of `slow` it touches, and
  `cd frontend && npm test` if you changed the UI.

No new dependencies without a reason: the core stands on ffmpeg, the standard library, `numpy`
and Pillow.

---

## License

MIT — see [LICENSE](LICENSE).
