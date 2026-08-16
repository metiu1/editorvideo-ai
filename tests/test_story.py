"""Montaggio ragionato: scarti, ordine, ritmo."""

import subprocess

import pytest

from vedit import ffmpeg, story
from vedit.store import Store


@pytest.fixture(autouse=True)
def cache_isolata(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_CACHE", str(tmp_path / "cache"))


def _mk(path, sorgente, durata=3.0):
    # "testsrc2" -> "testsrc2=s=..."; "color=c=blue" -> "color=c=blue:s=..."
    sep = ":" if "=" in sorgente else "="
    subprocess.run([
        ffmpeg.binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"{sorgente}{sep}s=320x180:r=25:d={durata}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={durata}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ], check=True, capture_output=True)
    return str(path)


@pytest.fixture
def girato(tmp_path):
    """Una cartella come quella vera: roba buona, una nera, due gemelle."""
    d = tmp_path / "girato"
    d.mkdir()
    return {
        "movimento": _mk(d / "a_movimento.mp4", "testsrc2"),
        "statica": _mk(d / "b_statica.mp4", "color=c=blue"),
        "nera": _mk(d / "c_nera.mp4", "color=c=black"),
        "gemella": _mk(d / "d_gemella.mp4", "color=c=blue"),
        "dir": str(d),
    }


# --------------------------------------------------------------------------
# misure e regole
# --------------------------------------------------------------------------


def test_collect_legge_la_cartella(girato):
    files = story.collect(girato["dir"])
    assert len(files) == 4
    assert all(f.endswith(".mp4") for f in files)


def test_collect_rifiuta_un_file(girato):
    with pytest.raises(NotADirectoryError):
        story.collect(girato["movimento"])


def test_fingerprint_riconosce_le_gemelle(girato):
    st = story.STYLES["vlog"]
    a = story.shot_from(girato["statica"], st)
    b = story.shot_from(girato["gemella"], st)
    c = story.shot_from(girato["movimento"], st)
    assert story.similarity(a.fingerprint, b.fingerprint) > 0.995
    assert story.similarity(a.fingerprint, c.fingerprint) < 0.995


def test_clip_con_movimento_ha_punteggio_piu_alto(girato):
    st = story.STYLES["shortform"]
    mov = story.shot_from(girato["movimento"], st)
    fermo = story.shot_from(girato["statica"], st)
    assert mov.score > fermo.score


def test_drop_duplicates_tiene_la_migliore():
    a = story.Shot(path="a.mp4", duration=3, score=0.4, fingerprint=[1.0, 0.5])
    b = story.Shot(path="b.mp4", duration=3, score=0.9, fingerprint=[1.0, 0.5])
    keep, dropped = story.drop_duplicates([a, b])
    assert [s.path for s in keep] == ["b.mp4"]
    assert dropped[0].path == "a.mp4" and "identica" in dropped[0].reason


def test_arrange_mette_il_picco_prima_della_fine():
    shots = [story.Shot(path=f"{i}.mp4", duration=3, score=i / 10, fingerprint=[i, 1])
             for i in range(6)]
    out = story.arrange(shots, story.STYLES["documentary"])
    posizioni = {s.path: i for i, s in enumerate(out)}
    assert posizioni["5.mp4"] < len(out) - 1, "il picco non deve stare in fondo"
    assert out[-1].score < out[posizioni["5.mp4"]].score


def test_arrange_apre_col_meglio_in_shortform():
    shots = [story.Shot(path=f"{i}.mp4", duration=3, score=i / 10, fingerprint=[i, 1])
             for i in range(5)]
    out = story.arrange(shots, story.STYLES["shortform"])
    assert out[0].path == "4.mp4"
    assert "apertura" in out[0].reason


def test_avoid_monotony_separa_le_simili():
    same = [1.0, 0.5]
    shots = [
        story.Shot(path="a.mp4", duration=3, fingerprint=same),
        story.Shot(path="b.mp4", duration=3, fingerprint=same),
        story.Shot(path="c.mp4", duration=3, fingerprint=[0.1, 0.9]),
        story.Shot(path="d.mp4", duration=3, fingerprint=[0.4, 0.7]),
    ]
    out = story.avoid_monotony(shots)
    assert story.similarity(out[0].fingerprint, out[1].fingerprint) < 0.99
    assert {s.path for s in out} == {"a.mp4", "b.mp4", "c.mp4", "d.mp4"}


def test_avoid_monotony_con_tre_clip_la_chiusura_vince():
    """Con tre clip non c'e' spazio: meglio due simili di fila che l'arco rotto."""
    same = [1.0, 0.5]
    shots = [
        story.Shot(path="a.mp4", duration=3, fingerprint=same),
        story.Shot(path="b.mp4", duration=3, fingerprint=same),
        story.Shot(path="chiusura.mp4", duration=3, fingerprint=[0.1, 0.9]),
    ]
    out = story.avoid_monotony(shots)
    assert [s.path for s in out] == ["a.mp4", "b.mp4", "chiusura.mp4"]


def test_avoid_monotony_non_rimette_il_picco_in_fondo():
    """L'anti-monotonia non deve annullare l'arco: la chiusura resta ultima."""
    same = [1.0, 0.5]
    shots = [
        story.Shot(path="salita.mp4", duration=3, score=0.3, fingerprint=same),
        story.Shot(path="picco.mp4", duration=3, score=0.9, fingerprint=same,
                   reason="picco"),
        story.Shot(path="chiusura.mp4", duration=3, score=0.1, fingerprint=[0.1, 0.9],
                   reason="chiusura, si atterra"),
    ]
    out = story.avoid_monotony(shots)
    assert out[-1].path == "chiusura.mp4"
    assert "chiusura" in out[-1].reason


def test_pace_rispetta_i_limiti_dello_stile():
    st = story.STYLES["shortform"]
    shots = [story.Shot(path="a.mp4", duration=30, out=30, score=1.0),
             story.Shot(path="b.mp4", duration=30, out=30, score=0.0)]
    out = story.pace(shots, st)
    assert out[0].used > out[1].used            # piu' punteggio, piu' tempo
    assert all(s.used <= st.shot_max + 1e-6 for s in out)


def test_pace_verso_una_durata_richiesta():
    st = story.STYLES["vlog"]
    shots = [story.Shot(path=f"{i}.mp4", duration=20, out=20, score=0.5) for i in range(4)]
    out = story.pace(shots, st, target=12.0)
    assert abs(sum(s.used for s in out) - 12.0) < 1.5


# --------------------------------------------------------------------------
# piano completo
# --------------------------------------------------------------------------


def test_plan_scarta_il_nero_e_i_doppioni(girato):
    p = story.plan(girato["dir"], style="vlog")
    dentro = {c["nome"] for c in p["clip"]}
    fuori = {s["nome"] for s in p["scartate"]}
    assert "c_nera.mp4" in fuori
    assert "a_movimento.mp4" in dentro
    # blu e gemella sono la stessa inquadratura: ne resta una sola
    assert len({"b_statica.mp4", "d_gemella.mp4"} & dentro) == 1


def test_plan_motiva_ogni_clip(girato):
    p = story.plan(girato["dir"], style="documentary")
    assert all(c["perche"] for c in p["clip"])
    assert all(s["perche"] for s in p["scartate"])


def test_plan_rispetta_la_durata_richiesta(girato):
    p = story.plan(girato["dir"], style="shortform", target_duration=4.0)
    assert abs(p["durata_totale"] - 4.0) < 1.5


def test_collect_chrono_ignora_i_nomi(tmp_path):
    """IMG_9987 girato ieri deve precedere IMG_0001 girato oggi."""
    import os
    import time

    d = tmp_path / "crono"
    d.mkdir()
    vecchio = _mk(d / "IMG_9987.mp4", "color=c=red", 1.0)
    nuovo = _mk(d / "IMG_0001.mp4", "color=c=blue", 1.0)
    ieri = time.time() - 86400
    os.utime(vecchio, (ieri, ieri))

    per_nome = story.collect(str(d), order="name")
    per_data = story.collect(str(d), order="chrono")
    assert per_nome[0].endswith("IMG_0001.mp4")
    assert per_data[0].endswith("IMG_9987.mp4"), "l'ordine cronologico non e' vero"
    assert per_data[1] == nuovo


def test_recorded_at_dichiara_la_fonte(girato):
    from vedit import probe

    info = probe.recorded_at(girato["movimento"])
    assert info["quando"]
    assert info["fonte"] in ("file:mtime",) or info["fonte"].startswith("tag:")


def test_plan_chrono_conserva_l_ordine_del_corpo(tmp_path):
    """Con order=chrono il corpo centrale segue il tempo, non il punteggio."""
    import os
    import time

    d = tmp_path / "seq"
    d.mkdir()
    nomi = []
    for i, colore in enumerate(("red", "green", "blue", "yellow", "magenta")):
        f = _mk(d / f"clip{i}.mp4", f"color=c={colore}", 2.0)
        t = time.time() - (10 - i) * 3600     # uno all'ora, in ordine
        os.utime(f, (t, t))
        nomi.append(f"clip{i}.mp4")

    p = story.plan(str(d), style="documentary", order="chrono", dedupe=False)
    assert p["ordine"] == "chrono"
    uscita = [c["nome"] for c in p["clip"]]
    assert uscita == sorted(uscita, key=nomi.index), f"cronologia rotta: {uscita}"


def test_plan_chrono_shortform_apre_col_gancio_poi_torna_in_ordine(tmp_path):
    """Il gancio in apertura e' una scelta dichiarata; il resto resta in ordine."""
    import os
    import time

    d = tmp_path / "seq2"
    d.mkdir()
    nomi = []
    for i, sorgente in enumerate(("color=c=navy", "color=c=teal", "testsrc2",
                                  "color=c=olive", "color=c=maroon")):
        f = _mk(d / f"s{i}.mp4", sorgente, 2.0)
        t = time.time() - (10 - i) * 3600
        os.utime(f, (t, t))
        nomi.append(f"s{i}.mp4")

    p = story.plan(str(d), style="shortform", order="chrono", dedupe=False)
    uscita = [c["nome"] for c in p["clip"]]
    assert "apertura" in p["clip"][0]["perche"]
    resto = uscita[1:]
    assert resto == sorted(resto, key=nomi.index), f"dopo il gancio l'ordine salta: {resto}"


def test_plan_order_sconosciuto(girato):
    with pytest.raises(ValueError, match="order sconosciuto"):
        story.plan(girato["dir"], order="boh")


def test_plan_stile_sconosciuto(girato):
    with pytest.raises(ValueError, match="stile sconosciuto"):
        story.plan(girato["dir"], style="boh")


def test_plan_senza_dedupe_tiene_tutto(girato):
    p = story.plan(girato["dir"], style="vlog", dedupe=False)
    nomi = {c["nome"] for c in p["clip"]}
    assert {"b_statica.mp4", "d_gemella.mp4"} <= nomi


def test_le_clip_non_si_sovrappongono(girato):
    p = story.plan(girato["dir"], style="vlog")
    t = 0.0
    for c in p["clip"]:
        assert abs(c["inizio_timeline"] - t) < 1e-6
        assert c["out"] > c["in"]
        t += c["durata"]


def test_apply_plan_costruisce_la_timeline(girato, tmp_path):
    s = Store.create("auto", "1080p", path=str(tmp_path / "p.json"))
    p = story.plan(girato["dir"], style="vlog")
    res = story.apply_plan(s, p)
    assert len(res["clip"]) == len(p["clip"])
    riepilogo = s.summary()
    assert riepilogo["duration"] > 0
    assert len(s.project.tracks[0].clips) == len(p["clip"])


def test_apply_plan_con_transizioni(girato, tmp_path):
    s = Store.create("cine", "1080p", path=str(tmp_path / "p.json"))
    p = story.plan(girato["dir"], style="cinematic")
    story.apply_plan(s, p)
    clips = s.project.tracks[0].clips
    if len(clips) > 1:
        assert any(getattr(c, "transition_out", None) for c in clips[:-1])
