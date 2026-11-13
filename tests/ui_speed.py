# Folio Reel, driven as a user would: R5-07, slow motion that keeps its sound in step.
# Run with run_ui.sh ui_speed.py.
import os
import tempfile
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())

import mkclap  # noqa: E402
from folio_reel import engine, model as _model  # noqa: E402


def wander(path):
    """(the gap between sound and picture at each clap, how much that gap moves along the film)."""
    off, f, b = mkclap.offsets(path)
    return off, (max(off) - min(off) if len(off) > 1 else 99.0), f, b


def export(name, fmt="mp4", size="720p"):
    out = os.path.join(T, name)
    ex = win.start_export(out, fmt, size)
    ok = wait(lambda: ex.done, 300)
    check(ok and ex.error is None and os.path.exists(out), "%s is made" % name, ex.error)
    return out


try:
    T = tempfile.mkdtemp(prefix="reel_speed_")
    CLAP = os.path.join(os.environ.get("REEL_MEDIA_DIR", "/tmp"), "reel_clap_media", "clap.mp4")
    os.makedirs(os.path.dirname(CLAP), exist_ok=True)
    if not os.path.exists(CLAP):
        mkclap.clapper(CLAP)
    CURI = _model.path_to_uri(CLAP)
    pump(0.4)

    # ---------------------------------------------------------------- the footage is honest
    off0, spread0, f0, b0 = wander(CLAP)
    check(len(f0) == 3 and len(b0) == 3, "the clapperboard flashes and beeps three times", (f0, b0))
    check(spread0 < 0.003, "and the two keep step all the way through it", (off0, spread0))

    # ---------------------------------------------------------------- picture and sound in one clip
    win.run("split-sound:off")      # the hardest case: one clip carries both
    win.import_uris([CURI])
    pump(0.5)
    win.mediabin.select_uri(CURI)
    win.run("add-to-timeline")
    pump(0.4)
    c = clips("video")[0]
    check(c is not None and abs(c.get("speed", 1.0) - 1.0) < 1e-9, "the clip starts at normal speed")
    check(engine.fix_settings(c) is None, "which asks for nothing to be rendered")

    win.timeline.selected = [c["id"]]
    win.run("speed:0.5")
    pump(0.4)
    c = win.project.clip(c["id"])
    check(abs(c["speed"] - 0.5) < 1e-9, "Speed 0.5x halves it", c["speed"])
    st = engine.fix_settings(c)
    check(st is not None and abs(st[3] - 0.5) < 1e-9, "so the clip asks for a copy that runs at half speed", st)
    check(st[4] == "av", "a copy of the whole of it, picture and sound", st)
    slow = engine.fixed_copy(c["media"], c)
    check(slow is not None, "and short footage is rendered there and then, without being asked")
    if slow:
        info = engine.probe(slow)
        check(abs(info["duration"] - 6.0) < 0.2, "the copy is twice as long as the footage", info["duration"])
        copy_off, copy_spread, _f, _b = wander(slow)
        check(copy_spread < 0.003, "and its own sound and picture keep step", (copy_off, copy_spread))

    out = export("slow.mp4")
    if os.path.exists(out):
        off, spread, f, b = wander(out)
        check(len(f) == 3 and len(b) == 3, "the exported film keeps all three claps", (f, b))
        check(spread <= 0.006, "sound and picture keep step along the whole of it", (off, spread))
        exact = spread

    # ---------------------------------------------------------------- without the copy, it wanders
    win.run("remove-fixes")
    pump(0.4)
    check(engine.fixed_copy(c["media"], win.project.clip(c["id"])) is None, "Remove Corrections throws the copy away")
    out2 = export("stretched.mp4")
    if os.path.exists(out2):
        off2, spread2, _f, _b = wander(out2)
        check(spread2 > exact, "stretching the sound to fit instead lets it wander", (off2, spread2, exact))

    # ---------------------------------------------------------------- long footage waits to be asked
    was, engine.RETIME_AUTO = engine.RETIME_AUTO, 0.5
    try:
        win.timeline.selected = [c["id"]]
        win.run("speed:2")
        pump(0.4)
        c2 = win.project.clip(c["id"])
        check(engine.fixed_copy(c2["media"], c2) is None, "long footage is not rendered behind your back")
        check("Render Correction" in win.notice_label.get_text(), "it says how to make it exact",
              win.notice_label.get_text())
    finally:
        engine.RETIME_AUTO = was
    win.timeline.selected = [c["id"]]
    win.run("steady-apply")
    pump(0.4)
    c2 = win.project.clip(c["id"])
    check(engine.fixed_copy(c2["media"], c2) is not None, "Render Correction makes it when asked")
    check(abs(engine.probe(engine.fixed_copy(c2["media"], c2))["duration"] - 1.5) < 0.2,
          "at twice the speed the copy is half as long")

    # ---------------------------------------------------------------- the sound on its own track
    win2 = win.run("new")
    win = win2 if win2 is not None else win
    pump(0.6)
    win.run("split-sound:on")
    win.import_uris([CURI])
    pump(0.5)
    win.mediabin.select_uri(CURI)
    win.run("add-to-timeline")
    pump(0.5)
    pic = clips("video")[0]
    snd = clips("audio")[0]
    check(pic is not None and snd is not None, "the clip arrives as a picture and a sound clip (R5-05)")
    win.timeline.select([pic["id"]])
    win.run("speed:0.5")
    pump(0.4)
    pic = win.project.clip(pic["id"])
    snd = win.project.clip(snd["id"])
    check(abs(snd["speed"] - 0.5) < 1e-9, "the sound slows with its picture", snd["speed"])
    sp_set, sn_set = engine.fix_settings(pic), engine.fix_settings(snd)
    check(sp_set[4] == "v" and sn_set[4] == "a", "each renders only the half it shows", (sp_set, sn_set))
    pcopy, scopy = engine.fixed_copy(pic["media"], pic), engine.fixed_copy(snd["media"], snd)
    check(pcopy is not None and scopy is not None and pcopy != scopy, "so they are two copies, not one")
    if pcopy and scopy:
        check(engine.probe(pcopy)["has_audio"] is False, "the picture's copy carries no sound to waste")
        check(engine.probe(scopy)["has_video"] is False, "and the sound's copy carries no picture")
    out3 = export("split.mp4")
    if os.path.exists(out3):
        off3, spread3, f3, b3 = wander(out3)
        check(len(f3) == 3 and len(b3) == 3, "that film keeps all three claps too", (f3, b3))
        check(spread3 <= 0.006, "and its sound keeps step with its picture as well", (off3, spread3))
    shot("01_slow")
except Exception:       # noqa: BLE001
    traceback.print_exc()
    FAILS.append("the test itself fell over")
finish()
