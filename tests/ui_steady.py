# Folio Reel, driven as a user would: R4-07 steadying and straightening.
# Run with run_ui.sh ui_steady.py.
import os
import tempfile
import time
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())

import mkshaky  # noqa: E402
from folio_reel import engine, model as _model  # noqa: E402

try:
    T = tempfile.mkdtemp(prefix="reel_steady_")
    FOOT = mkshaky.make(os.path.join(os.environ.get("REEL_MEDIA_DIR", "/tmp"), "reel_steady_media"))
    FURI = {k: _model.path_to_uri(v) for k, v in FOOT.items()}
    pump(0.4)
    win.run("split-sound:off")      # not what this test is about (R5-05)

    # the footage is what it says on the tin: one clip shakes, one is bowed by its lens
    shake0 = mkshaky.shake(FOOT["shaky"])
    bow0 = mkshaky.bow(FOOT["bent"])
    check(shake0 is not None and shake0 > 1.2, "the test footage really does shake", shake0)
    check(bow0 is not None and bow0 > 6, "and the other was shot through a bent lens", bow0)

    # ---------------------------------------------------------------- the settings live on the clip
    win.import_uris([FURI["shaky"], FURI["bent"]])
    pump(0.4)
    win.mediabin.select_uri(FURI["shaky"])
    win.run("add-to-timeline")
    pump(0.3)
    c = clips("video")[0]
    check(c.get("steady") is False and c.get("lens") == 0.0 and c.get("steady_amount") == 5,
          "a new clip is left as filmed", (c.get("steady"), c.get("lens"), c.get("steady_amount")))
    check(engine.fix_settings(c) is None, "so it asks for no correction")
    check(engine.fixed_copy(c["media"], c) is None, "and has no corrected copy")

    # ---------------------------------------------------------------- the panel
    win.timeline.selected = [c["id"]]
    win.selection_changed()
    pump(0.3)
    panel = win.clipset
    for k in ("steady", "steady_amount", "lens", "steady_apply", "steady_ready"):
        check(k in panel.controls, "Clip Settings has %s" % k)
    check(not panel.controls["steady"].get_active(), "Take the shake out starts off")
    check(abs(panel.controls["lens"].get_value()) < 1e-6, "Straighten starts at nothing")

    # ---------------------------------------------------------------- Steady, through the panel
    t0 = time.time()
    panel.controls["steady"].set_active(True)
    pump(0.3)
    c = win.project.clip(c["id"])
    check(c["steady"] is True, "ticking the box turns steadying on")
    check(engine.fix_settings(c) == (True, 5, 0.0, 1.0, "av"), "which is what the clip now asks for", engine.fix_settings(c))
    check(engine.fixed_copy(c["media"], c) is None, "but nothing is corrected until it is rendered")
    check("still plays as it was filmed" in panel.controls["steady_ready"].get_text(),
          "and the panel says so", panel.controls["steady_ready"].get_text())
    check(engine.have_ffmpeg(), "ffmpeg is installed, so this can be rendered")
    panel.controls["steady_apply"].clicked()
    pump(0.3)
    fixed = engine.fixed_copy(c["media"], win.project.clip(c["id"]))
    check(fixed is not None, "Render the corrected copy makes one", win.notice_label.get_text())
    check("corrected" in win.notice_label.get_text(), "and says it is ready", win.notice_label.get_text())
    panel.refresh()
    pump(0.2)
    check("ready" in panel.controls["steady_ready"].get_text(), "the panel agrees",
          panel.controls["steady_ready"].get_text())

    # the copy really is steadier
    shake1 = mkshaky.shake(fixed) if fixed else None
    check(shake1 is not None and shake1 < shake0 * 0.5,
          "the corrected copy is steadier than the footage (%.2f -> %.2f px a frame)" % (shake0, shake1 or -1),
          (shake0, shake1))

    # ---------------------------------------------------------------- the timeline plays the copy
    settle()
    tl = engine.make_timeline(win.project.width, win.project.height, win.project.fps)
    made = engine.build(win.project, tl)
    g = made[c["id"]]
    uri = g.get_asset().get_id() if hasattr(g, "get_asset") and g.get_asset() else ""
    check(os.path.basename(fixed) in (uri or ""),
          "the timeline is built from the corrected copy, not the original", uri)
    tl = None

    # ---------------------------------------------------------------- changing a setting needs it again
    before = engine.fix_path(c["media"], engine.fix_settings(win.project.clip(c["id"])))
    panel.controls["steady_amount"].set_value(9)
    pump(0.3)
    c = win.project.clip(c["id"])
    check(c["steady_amount"] == 9, "How much moves to 9")
    after = engine.fix_path(c["media"], engine.fix_settings(c))
    check(after != before, "a different setting means a different copy, not the old one")
    check(engine.fixed_copy(c["media"], c) is None, "so the clip waits to be rendered again")
    win.run("steady-apply")
    pump(0.3)
    check(engine.fixed_copy(c["media"], win.project.clip(c["id"])) is not None, "and Render Correction makes it")

    # asking twice doesn't render twice
    p2 = engine.fixed_copy(c["media"], win.project.clip(c["id"]))
    stamp = os.path.getmtime(p2)
    win.run("steady-apply")
    pump(0.2)
    check(os.path.getmtime(p2) == stamp and "ready" in win.notice_label.get_text(),
          "asking again uses the copy already made", win.notice_label.get_text())

    # ---------------------------------------------------------------- Straighten
    win.mediabin.select_uri(FURI["bent"])
    win.run("add-to-timeline")
    pump(0.3)
    b = clips("video")[1]
    win.timeline.selected = [b["id"]]
    win.selection_changed()
    pump(0.3)
    win.clipset.controls["lens"].set_value(100)
    pump(0.3)
    b = win.project.clip(b["id"])
    check(abs(b["lens"] - 1.0) < 1e-6, "Straighten to the end of the slider", b["lens"])
    check(engine.fix_settings(b) == (False, 5, 1.0, 1.0, "av"), "which asks for straightening alone", engine.fix_settings(b))
    win.run("steady-apply")
    pump(0.3)
    bfix = engine.fixed_copy(b["media"], win.project.clip(b["id"]))
    check(bfix is not None, "the straightened copy is made", win.notice_label.get_text())
    bow1 = mkshaky.bow(bfix) if bfix else None
    check(bow1 is not None and bow1 < bow0 * 0.6,
          "and the line in it is straighter (%.2f -> %.2f px of bend)" % (bow0, bow1 or -1), (bow0, bow1))

    # the other way round bends it further, so the slider's two ends do different things
    win.clipset.controls["lens"].set_value(-100)
    pump(0.3)
    win.run("steady-apply")
    pump(0.3)
    wrong = engine.fixed_copy(b["media"], win.project.clip(b["id"]))
    bow2 = mkshaky.bow(wrong) if wrong else None
    check(bow2 is not None and bow2 > bow1, "straightening the other way bends it more, as it should",
          (bow1, bow2))
    win.clipset.controls["lens"].set_value(100)
    pump(0.3)

    # ---------------------------------------------------------------- the ribbon sets, it doesn't render
    win.timeline.selected = [clips("video")[0]["id"]]
    win.selection_changed()
    pump(0.2)
    win.run("remove-fixes")
    pump(0.2)
    n = win.run("steady:on")
    pump(0.2)
    check(win.project.clip(clips("video")[0]["id"])["steady"] is True and "Render Correction" in win.notice_label.get_text(),
          "the ribbon's Steady turns it on and says what to do next", win.notice_label.get_text())
    check(engine.fixed_copy(clips("video")[0]["media"], clips("video")[0]) is None,
          "a ribbon click never starts a long render on its own")
    win.run("lens:60")
    pump(0.2)
    check(abs(win.project.clip(clips("video")[0]["id"])["lens"] - 0.6) < 1e-6,
          "and the Straighten menu sets the amount", win.project.clip(clips("video")[0]["id"])["lens"])
    win.run("lens:0")
    pump(0.2)
    win.run("steady-apply")
    pump(0.3)
    check(engine.fixed_copy(clips("video")[0]["media"], win.project.clip(clips("video")[0]["id"])) is not None,
          "Render Correction is what renders", win.notice_label.get_text())

    from folio_reel.ribbon_defs import Cmd
    cmds = set()
    for ctl in win.ribbon.controls:
        a = getattr(ctl, "action", None)
        if isinstance(a, str):
            cmds.add(a)
        for it in (getattr(ctl, "menu", None) or []):
            if isinstance(it, tuple) and len(it) >= 2 and isinstance(it[1], Cmd):
                cmds.add(it[1].cmd)
    for want in ("steady", "steady-apply", "remove-fixes"):
        check(want in cmds, "the ribbon has %s" % want, sorted(x for x in cmds if "stead" in x or "lens" in x))
    check(any(x.startswith("lens:") for x in cmds), "and a Straighten menu")

    # ---------------------------------------------------------------- saved with the project
    proj = os.path.join(T, "steady.reel")
    check(win.save(proj), "Save")
    again = _model.Project.load(proj)
    v = again.track("video")
    check(v[0]["steady"] is True and v[0]["steady_amount"] == 9 and abs(v[1]["lens"] - 1.0) < 1e-6,
          "the settings travel with the project", [(x.get("steady"), x.get("steady_amount"), x.get("lens")) for x in v])

    # ---------------------------------------------------------------- undo
    win.timeline.selected = [clips("video")[0]["id"]]
    win.selection_changed()
    pump(0.2)
    win.clipset.controls["steady"].set_active(False)
    pump(0.3)
    check(win.project.clip(clips("video")[0]["id"])["steady"] is False, "untick: steadying off")
    win.run("undo")
    pump(0.3)
    check(win.project.clip(clips("video")[0]["id"])["steady"] is True, "undo brings it back")

    # ---------------------------------------------------------------- export uses the copy
    out = os.path.join(T, "steadied.mp4")
    only = [x["id"] for x in clips("video")[1:]]
    win.edit(lambda p: p.delete(only))
    settle()
    check(len(clips("video")) == 1 and clips("video")[0]["steady"] is True, "one steadied clip left on the timeline")
    ex = win.start_export(out, "mp4", "720p")
    ok = ex is not None and wait(lambda: ex.done, 300)
    check(ok and ex.error is None and os.path.exists(out) and os.path.getsize(out) > 0,
          "the film exports", (ok, ex and ex.error, os.path.exists(out)))
    shake2 = mkshaky.shake(out) if os.path.exists(out) else None
    check(shake2 is not None and shake2 < shake0 * 0.6,
          "and the exported film is steady, not just the preview (%.2f -> %.2f px a frame)" % (shake0, shake2 or -1),
          (shake0, shake2))

    # ---------------------------------------------------------------- throwing the copies away
    n = win.run("remove-fixes")
    pump(0.2)
    check(n >= 1 and "removed" in win.notice_label.get_text(), "Remove Corrections throws them away",
          (n, win.notice_label.get_text()))
    check(engine.fixed_copy(clips("video")[0]["media"], clips("video")[0]) is None,
          "so the clip plays as it was filmed again, until it is rendered once more")

    # ---------------------------------------------------------------- no ffmpeg: it says so
    real = engine.ffmpeg_path
    engine.ffmpeg_path = lambda: None
    try:
        win.run("steady-apply")
        pump(0.2)
        check("ffmpeg" in win.notice_label.get_text() and "isn" in win.notice_label.get_text(),
              "without ffmpeg Reel says plainly what is missing", win.notice_label.get_text())
        win.clipset.refresh()
        pump(0.2)
        txt = win.clipset.controls.get("steady_ready")
        check(txt is not None and "ffmpeg" in txt.get_text(), "and the panel says it too",
              txt and txt.get_text())
    finally:
        engine.ffmpeg_path = real
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
finish()
