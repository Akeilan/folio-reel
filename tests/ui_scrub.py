# Moving the playhead (R5-01): dragging the red bar, carrying the view along with a drag, and
# jumping to a typed time. Run with run_ui.sh ui_scrub.py.
import os
import tempfile
import time
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())

from folio_reel import timeline as tlmod
from folio_reel.model import end_of

REAL = os.environ.get("REEL_REAL_MEDIA")      # the Product Owner's own clips, when they are to hand

try:
    pump(0.5)
    t = win.timeline
    HEAD, RULER = tlmod.HEAD, tlmod.RULER

    def press(x, y, button=1):
        t._press(t.area, Ev(type=Gdk.EventType.BUTTON_PRESS, x=float(x), y=float(y), button=button,
                            state=Gdk.ModifierType(0)))

    def motion(x, y):
        t._motion(t.area, Ev(type=Gdk.EventType.MOTION_NOTIFY, x=float(x), y=float(y),
                             state=Gdk.ModifierType(Gdk.ModifierType.BUTTON1_MASK)))
        pump(0.02)

    def release(x, y):
        t._release(t.area, Ev(type=Gdk.EventType.BUTTON_RELEASE, x=float(x), y=float(y), button=1,
                              state=Gdk.ModifierType(0)))
        pump(0.05)

    # a film long enough that most of it is off screen at the normal zoom
    if REAL:
        for u, tr in (("Project2.mp4", "video"), ("Project2.mp4", "video"), ("HeadsWillRoll.mp3", "music")):
            win.add_uris(["file://" + REAL + "/" + u], track=tr)
            settle()
    else:
        long_clip = os.path.join(tempfile.mkdtemp(prefix="reel_scrub_"), "long.mp4")
        mkmedia.video(long_clip, "smpte", 40, 440)
        for _ in range(4):
            win.add_uris([_model.path_to_uri(long_clip)], track="video")
            settle()
    total = win.project.duration()
    W = t.area.get_allocated_width()
    seen = t.adj.get_page_size() / t.pps          # seconds the view shows at once
    check(total > seen * 1.5, "the test film is longer than the view shows", (total, seen))

    # ------------------------------------------------- dragging on the ruler
    win.seek(0.0)
    settle()
    press(HEAD + 100, 6)
    check(abs(win.playhead - t.t_of(HEAD + 100)) < 0.01, "a press on the ruler puts the playhead there",
          (win.playhead, t.t_of(HEAD + 100)))
    xs = [HEAD + 100 + k * 40 for k in range(1, 6)]
    followed = True
    for x in xs:
        motion(x, 6)
        if abs(win.playhead - t.t_of(x)) > 0.01:
            followed = False
    check(followed, "dragging the ruler: the playhead stays under the pointer", win.playhead)
    before = win.playhead
    release(xs[-1], 6)
    check(abs(win.playhead - before) < 0.01, "letting go leaves it where it was dropped", win.playhead)

    # ------------------------------------------------- the view travels when the drag reaches the edge
    win.seek(0.0)
    t.adj.set_value(0.0)
    settle()
    at_edge_t = t.t_of(W - 6)
    v0 = t.adj.get_value()
    press(HEAD + 40, 6)
    t._motion(t.area, Ev(type=Gdk.EventType.MOTION_NOTIFY, x=float(W - 6), y=6.0,
                         state=Gdk.ModifierType(Gdk.ModifierType.BUTTON1_MASK)))
    check(abs(win.playhead - at_edge_t) < 0.05, "the drag reaches the far side of the view",
          (win.playhead, at_edge_t))
    check(t._scroll_id is not None, "holding it at the edge sets the view travelling")
    check(t._edge_step(W - 6) > 0 and t._edge_step((HEAD + W) / 2) == 0.0,
          "only the band at the edge of the view travels", (t._edge_step(W - 6), t._edge_step((HEAD + W) / 2)))
    check(t._edge_step(W - tlmod.EDGE_SCROLL + 4) < t._edge_step(W - 1),
          "gently where the band begins, quicker at the very edge")
    # drive the travel by hand from here: the real thing runs on a 20ms timer, and a test that
    # waited on the clock would measure the machine rather than the timeline
    t._stop_auto_scroll()
    for _ in range(26):
        time.sleep(0.02)
        t.auto_scroll_tick()
    check(t.adj.get_value() > v0 + 100, "the view has travelled", (v0, t.adj.get_value()))
    check(abs(win.playhead - t.t_of(W - 6)) < 0.05, "the playhead is still under the pointer",
          (win.playhead, t.t_of(W - 6)))
    check(win.playhead > seen, "it has reached past what the view showed to begin with",
          (win.playhead, seen))
    for _ in range(100):
        time.sleep(0.01)
        if not t.auto_scroll_tick():
            break
    reached = win.playhead
    check(reached > at_edge_t + 8.0, "and keeps going, the longer it is held", (at_edge_t, reached))
    release(W - 6, 6)
    # the whole film in view: from there the far end is a short drag away
    win.run("zoom-fit")
    settle()
    press(HEAD + 40, 6)
    t._motion(t.area, Ev(type=Gdk.EventType.MOTION_NOTIFY, x=float(W - 2), y=6.0,
                         state=Gdk.ModifierType(Gdk.ModifierType.BUTTON1_MASK)))
    t._stop_auto_scroll()
    for _ in range(120):
        time.sleep(0.01)
        if not t.auto_scroll_tick():
            break
    check(abs(win.playhead - total) < 0.3, "zoomed to fit, a drag reaches the end of the film",
          (win.playhead, total))
    release(W - 2, 6)
    check(t._scroll_id is None, "letting go stops the view travelling")
    check(t.auto_scroll_tick() is False, "and nothing travels with no drag in hand")
    far = win.playhead
    pump(0.3)
    check(abs(win.playhead - far) < 0.01, "and the playhead stops with it", (far, win.playhead))

    # the same hard against the left edge brings it back
    t.set_zoom(40.0, 0.0)
    t.adj.set_value(500.0)
    settle()
    press(W - 200, 6)
    t._motion(t.area, Ev(type=Gdk.EventType.MOTION_NOTIFY, x=float(HEAD + 2), y=6.0,
                         state=Gdk.ModifierType(Gdk.ModifierType.BUTTON1_MASK)))
    t._stop_auto_scroll()
    for _ in range(120):
        time.sleep(0.01)
        if not t.auto_scroll_tick():
            break
    check(t.adj.get_value() < 1.0, "dragging to the left edge comes back to the start",
          (t.adj.get_value(), win.playhead))
    release(HEAD + 2, 6)

    # ------------------------------------------------- grabbing the red bar down in the tracks
    t.adj.set_value(0.0)
    win.seek(2.0)
    settle()
    c0 = clips("video")[0]
    check(c0["start"] < 2.0 < end_of(c0), "the playhead is over a clip", (c0["start"], c0["duration"]))
    y, h = t.track_rect("video")
    px = t.x_of(win.playhead)
    check(t.on_playhead(px, y + h / 2), "the red bar can be grabbed where it crosses a clip")
    check(not t.on_playhead(px + 30, y + h / 2), "a point away from it cannot")
    start0, dur0 = c0["start"], c0["duration"]
    press(px, y + h / 2)
    motion(px + 60, y + h / 2)
    release(px + 60, y + h / 2)
    c0 = clips("video")[0]
    check(abs(win.playhead - t.t_of(px + 60)) < 0.02, "dragging it scrubs", win.playhead)
    check(abs(c0["start"] - start0) < 1e-6 and abs(c0["duration"] - dur0) < 1e-6,
          "and leaves the clip under it alone", (c0["start"], c0["duration"]))

    # ------------------------------------------------- a clip drag can reach beyond the view too
    t.adj.set_value(0.0)
    settle()
    c1 = clips("video")[-1]        # the last one: there is open timeline to its right
    cid = c1["id"]
    y, h = t.track_rect("video")
    s0 = c1["start"]
    t.centre_on(s0 + 1.0)
    cx = t.x_of(s0 + 1.0)
    check(HEAD < cx < W, "the clip being dragged is in view", cx)
    press(cx, y + h / 2)
    t._motion(t.area, Ev(type=Gdk.EventType.MOTION_NOTIFY, x=float(W - 6), y=float(y + h / 2),
                         state=Gdk.ModifierType(Gdk.ModifierType.BUTTON1_MASK)))
    t._stop_auto_scroll()
    for _ in range(30):
        time.sleep(0.01)
        t.auto_scroll_tick()
    release(W - 6, y + h / 2)
    moved = win.project.clip(cid)
    check(moved is not None and moved["start"] > s0 + seen / 2,
          "a clip can be dragged to a time the view wasn't showing", (s0, moved["start"] if moved else None, seen))
    win.run("undo")
    settle()
    check(abs(win.project.clip(cid)["start"] - s0) < 1e-6, "and undo puts it back",
          win.project.clip(cid)["start"])

    # ------------------------------------------------- jumping to a typed time
    check(abs(win.run("go-to-time:1:05") - 65.0) < 0.01, "go-to-time takes minutes:seconds")
    check(abs(win.playhead - 65.0) < 0.01, "the playhead goes there", win.playhead)
    vx = t.x_of(65.0)
    check(HEAD < vx < W, "and the view comes with it", (vx, t.adj.get_value()))
    check(win.run("go-to-time:0:00:12:00") is not None and abs(win.playhead - 12.0) < 0.05,
          "and the timecode's own shape", win.playhead)
    check(win.run("go-to-time:nonsense") is None and abs(win.playhead - 12.0) < 0.05,
          "nonsense moves nothing", win.playhead)

    respond("time_dialog", Gtk.ResponseType.OK, setup=lambda d: d[1].set_text("1:45"))
    win.run("go-to-time")
    pump(0.6)
    check(abs(win.playhead - 105.0) < 0.05, "the Go to Time box jumps to what was typed", win.playhead)
    respond("time_dialog", Gtk.ResponseType.OK, setup=lambda d: d[1].set_text("half past four"))
    win.run("go-to-time")
    pump(0.6)
    check(abs(win.playhead - 105.0) < 0.05 and "isn't a time" in win.notice_label.get_text(),
          "a time it can't read says so and stays put", win.notice_label.get_text())
    respond("time_dialog", Gtk.ResponseType.CANCEL)
    win.run("go-to-time")
    pump(0.6)
    check(abs(win.playhead - 105.0) < 0.05, "Cancel leaves the playhead alone", win.playhead)

    # the timecode in the status bar is the way in
    check(win.timecode_box is not None and win.timecode_box.get_tooltip_text() == "Go to Time (Ctrl+J)",
          "the timecode offers it", win.timecode_box.get_tooltip_text() if win.timecode_box else None)
    respond("time_dialog", Gtk.ResponseType.OK, delay=250, setup=lambda d: d[1].set_text("0:30"))
    check(win.on_key(win, Ev(keyval=Gdk.keyval_from_name("j"), state=Gdk.ModifierType.CONTROL_MASK,
                             type=Gdk.EventType.KEY_PRESS)) is not None, "Ctrl+J is bound")
    pump(0.3)
    check(abs(win.playhead - 30.0) < 0.05, "and opens the box", win.playhead)

    # ------------------------------------------------- the playhead never leaves the film
    win.run("go-to-time:9:00:00")
    check(abs(win.playhead - total) < 0.01, "a time past the end stops at the end", (win.playhead, total))
    win.run("go-start")
    check(win.playhead == 0.0, "Home goes to the start", win.playhead)
    win.run("go-end")
    check(abs(win.playhead - total) < 0.01, "End goes to the end", win.playhead)

    shot("scrub_end")
except Exception:
    traceback.print_exc()
    check(False, "the test ran to the end")
finish()
