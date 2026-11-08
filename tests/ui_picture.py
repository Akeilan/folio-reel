# Reel noticing when a film would have no picture in it (R5-02): the warning before rendering, the
# look at the film afterwards, and the word when a clip's picture is dropped on a sound track.
# Run with run_ui.sh ui_picture.py.
import os
import tempfile
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())

from folio_reel import engine, model
from folio_reel.model import end_of

REAL = os.environ.get("REEL_REAL_MEDIA")


def answer(w, attr, response, delay=350, setup=None):
    """Answer a modal dialog that window w is holding (respond() only watches the first window)."""
    def go():
        d = getattr(w, attr, None)
        if d is None:
            return True
        if setup:
            setup(d)
        (d[0] if isinstance(d, tuple) else d).response(response)
        return False
    GLib.timeout_add(delay, go)

try:
    T = tempfile.mkdtemp(prefix="reel_pic_")
    pump(0.5)
    p = win.project

    # ------------------------------------------------ what the project says about its own picture
    check(p.dark_spans() == [] and win.picture_warnings() == [],
          "an empty project has nothing to warn about", (p.dark_spans(), win.picture_warnings()))
    win.add_uris([URI["music"]], track="music")
    settle()
    check(len(clips("music")) == 1, "a music bed on its own", len(clips("music")))
    spans = p.dark_spans()
    check(len(spans) == 1 and spans[0][0] == 0.0 and abs(spans[0][1] - p.duration()) < 0.01,
          "sound with no picture: the whole film is dark", spans)
    said = win.picture_warnings()
    check(len(said) == 1 and "no picture at all" in said[0], "and Reel says so in plain words", said)

    # a picture clip covers part of it: the tail is what is dark
    win.add_uris([URI["red"]], track="video")
    settle()
    vid = clips("video")[0]
    spans = p.dark_spans()
    check(len(spans) == 1 and abs(spans[0][0] - end_of(vid)) < 0.01, "picture first, then nothing to see",
          (spans, end_of(vid)))
    said = win.picture_warnings()
    check(len(said) == 1 and "last" in said[0] and "no picture" in said[0],
          "and the warning names the end of the film", said)

    # turned all the way down to black counts as nothing to see
    win.timeline.select([vid["id"]])
    for _ in range(12):
        win.run("color:darker")
    settle()
    vid = clips("video")[0]
    check(vid["color"]["brightness"] <= -0.99, "a clip can be turned right down to black",
          vid["color"]["brightness"])
    check(p.picture_spans() == [], "a clip that black shows nothing", p.picture_spans())
    check("no picture at all" in win.picture_warnings()[0], "so the whole film is black again",
          win.picture_warnings())
    win.run("color:reset")
    settle()
    check(p.picture_spans() != [], "and resetting its colour brings the picture back")

    # an empty title with nothing behind it shows nothing either
    win.project.add_clip("titles", "caption", at=0.0)
    settle()
    cap = clips("titles")[0]
    win.project.set(cap["id"], text="", bg_color="#00000000")
    settle()
    check(model.Project.clip_shows_nothing(win.project.clip(cap["id"])),
          "an empty see-through caption shows nothing")
    win.project.set(cap["id"], text="Hello")
    check(not model.Project.clip_shows_nothing(win.project.clip(cap["id"])),
          "a caption with words in it does")

    # ------------------------------------------------ the warning stops an export
    win2 = win.run("new")
    pump(0.6)
    check(win2 is not None and win2 is not win, "a fresh window to carry on in")
    settle()
    win2.add_uris([URI["music"]], track="music")
    pump(0.6)
    check(len(win2.project.track("music")) == 1, "sound only, no picture",
          len(win2.project.track("music")))
    answer(win2, "picture_dialog", Gtk.ResponseType.CANCEL)
    check(win2.export_as("mp4", "720p") is None, "Cancel on the warning stops the export there")
    check(not win2.exports and not win2.export_queue, "and nothing is queued",
          (len(win2.exports), len(win2.export_queue)))

    # ------------------------------------------------ Reel looks at the film it made
    black = os.path.join(T, "black.mp4")
    mkmedia.video(black, "black", 3, 440)
    check(os.path.exists(black), "a black film to look at")
    read, dark = engine.look_at_film(black, 3.0)
    check(read >= 5 and dark == read, "Reel can tell a film has no picture in it", (read, dark))
    read, dark = engine.look_at_film(MEDIA["red"], 4.0)
    check(read >= 5 and dark == 0, "and that one has", (read, dark))
    if REAL:
        read, dark = engine.look_at_film(os.path.join(REAL, "Project1.mp4"), 18.6)
        check(read >= 5 and dark == read, "the Product Owner's own black export is caught", (read, dark))
        read, dark = engine.look_at_film(os.path.join(REAL, "Project2.mp4"), 14.0)
        check(read >= 5 and dark < read, "and their good one is not", (read, dark))
    read, dark = engine.look_at_film(os.path.join(T, "not-there.mp4"), 3.0)
    check((read, dark) == (0, 0), "a film that isn't there reads as nothing", (read, dark))

    # an export with no picture says so when it is done
    out = os.path.join(T, "silent film.mp4")
    ex = win2.start_export(out, "mp4", "720p")
    check(ex is not None, "sound-only exports do run if that is what you want")
    ok = wait(lambda: ex.done, 240)
    check(ok and ex.error is None and os.path.exists(out), "the file is made", ex.error)
    pump(0.6)
    check("every frame of it is black" in win2.notice_label.get_text(),
          "Reel says the film it made came out black", win2.notice_label.get_text())
    check(win2.picture_dialog is None,
          "and does not put a box in the way: the question before the render already asked")
    if os.path.exists(out):
        read, dark = engine.look_at_film(out, win2.project.duration())
        check(read >= 5 and dark == read, "which is the truth: the film is black", (read, dark))

    # ------------------------------------------------ a film dropped on a sound track
    win2.add_uris([URI["red"]], track="audio")
    pump(0.5)
    txt = win2.notice_label.get_text()
    check("picture isn't" in txt, "dropping a film on a sound track says the picture is lost", txt)
    check(len(win2.project.track("audio")) == 1 and not win2.project.track("video"),
          "and leaves it where it was dropped",
          (len(win2.project.track("audio")), len(win2.project.track("video"))))

    # ------------------------------------------------ a normal film gets no warning at all
    win2.add_uris([URI["blue"]], track="video")
    settle()
    win2.project.delete([c["id"] for c in win2.project.track("music")])
    settle()
    check(win2.picture_warnings() == [], "a film that is all picture has nothing to warn about",
          win2.picture_warnings())
    good = os.path.join(T, "good.mp4")
    ex = win2.start_export(good, "mp4", "720p")
    ok = wait(lambda: ex is not None and ex.done, 240)
    check(ok and ex.error is None, "it exports with no questions asked", ex.error if ex else None)
    pump(0.5)
    check("Exported" in win2.notice_label.get_text() and "no picture" not in win2.notice_label.get_text(),
          "and is handed over plainly", win2.notice_label.get_text())
except Exception:
    traceback.print_exc()
    check(False, "the test ran to the end")
finish()
