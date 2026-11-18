# Backlog 9 in the window: opening awkward files, Clip Settings for a clip with its sound split off,
# keys, the export queue, dragging several clips, the recovery copy. Run with run_ui.sh ui_backlog9.py.
import json
import os
import shutil
import subprocess
import tempfile
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())
from folio_reel import engine, model, recovery, window as _window  # noqa: E402

MSGS = []
_window.ReelWindow.message = lambda self, *a, **k: MSGS.append(" / ".join(str(x) for x in a[:2]))


def note(w=None):
    return (w or win).notice_label.get_text()


def line(w=None, tracks=("video", "audio")):
    p = (w or win).project
    return " | ".join("%s: %s" % (t[0], " ".join("%.2f-%.2f" % (c["start"], model.end_of(c)) for c in p.track(t)))
                      for t in tracks)


try:
    T = tempfile.mkdtemp(prefix="reel_ui9_")
    pump(0.5)
    # an ordinary film: 4:2:0 H.264 with AAC sound, a colour and a tone for each of its 8 seconds
    FILM = os.path.join(T, "film.mp4")
    ins, fc = [], ""
    for n, col in enumerate(("red", "green", "blue", "yellow", "magenta", "cyan", "white", "gray")):
        ins += ["-f", "lavfi", "-t", "1", "-i", "color=c=%s:s=640x360:r=25" % col,
                "-f", "lavfi", "-t", "1", "-i", "sine=frequency=%d:sample_rate=48000" % (300 + 100 * n)]
        fc += "[%d:v][%d:a]" % (2 * n, 2 * n + 1)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + ins +
                   ["-filter_complex", fc + "concat=n=8:v=1:a=1[v][a]", "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-preset", "veryfast", "-g", "25", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", FILM], check=True)
    FURI = model.path_to_uri(FILM)

    def centre(path, t):
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ss", str(t), "-frames:v", "1", "-vf", "scale=1:1",
                            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        return tuple(r[:3]) if len(r) >= 3 else None

    # ---------------------------------------------------------------- R9-07: Clip Settings for an ordinary clip
    win.import_uris([FURI, URI["photo"]])
    for at_ in (0.0, 8.0, 16.0):
        win.seek(at_)
        win.add_media_to_timeline([FURI])
    settle()
    check(line() == "v: 0.00-8.00 8.00-16.00 16.00-24.00 | a: 0.00-8.00 8.00-16.00 16.00-24.00", "three clips, sound split off", line())
    win.timeline.zoom_fit()
    pump(0.2)
    x, y = clip_xy(clips("video")[0])
    tl_click(x, y)
    pump(0.3)
    check(len(win.timeline.selected) == 2, "a click picks the picture and its sound")
    cs = win.clipset.controls
    check(all(k in cs for k in ("speed", "brightness", "zoom", "crop_l", "chroma")),
          "R9-07: Clip Settings shows the picture's settings for it", sorted(cs)[:12])
    check("snd_volume" in cs and "snd_muted" in cs, "R9-07: with its sound's volume and mute")
    cs["snd_volume"].set_value(50)
    pump(0.2)
    check(abs(clips("audio")[0]["volume"] - 0.5) < 1e-6 and clips("video")[0]["volume"] == 1.0,
          "R9-07: the volume there sets the sound clip's volume")
    cs["fade_in"].set_value(1.0)
    pump(0.2)
    check(clips("video")[0]["fade_in"] == 1.0 and clips("audio")[0]["fade_in"] == 1.0, "R9-07: a fade there fades both")
    win.run("undo")
    win.run("undo")
    x, y = clip_xy(clips("video")[1])
    tl_click(x, y)
    pump(0.3)
    check("transition" in win.clipset.controls, "R9-07: the second clip's transition is there too")
    win.run("transition:crossfade")
    settle()
    check(clips("video")[1].get("transition") and "sound" not in note(), "R9-07: a transition asked for with the pair selected is made, without a complaint about sound",
          note())
    win.run("undo")
    settle()

    # ---------------------------------------------------------------- R9-04, R9-29: speed, one Undo
    x, y = clip_xy(clips("video")[0])
    tl_click(x, y)
    pump(0.2)
    depth = len(win.project.undo_stack)
    win.run("speed:2")
    settle()
    check(line() == "v: 0.00-4.00 4.00-12.00 12.00-20.00 | a: 0.00-4.00 4.00-12.00 12.00-20.00",
          "R9-04: 2× on the first clip: the others follow once", line())
    check(len(win.project.undo_stack) == depth + 1, "R9-29: as one step", len(win.project.undo_stack) - depth)
    check(note().startswith("Speed 2"), "the status bar says what was done, not a stale progress line", note())
    win.run("undo")
    settle()
    check(line() == "v: 0.00-8.00 8.00-16.00 16.00-24.00 | a: 0.00-8.00 8.00-16.00 16.00-24.00", "R9-29: one Undo puts it back", line())

    # ---------------------------------------------------------------- R9-24: keys while a slider has them
    x, y = clip_xy(clips("video")[0])
    tl_click(x, y)
    pump(0.3)
    win.seek(4.0)
    win._do_seek()
    sl = win.clipset.controls["brightness"]
    sl.grab_focus()
    pump(0.1)
    n, ph = len(clips("video")), win.playhead
    r1, r2 = key("Delete"), key("Right")
    check(len(clips("video")) == n and r1 is False, "R9-24: Delete with a Clip Settings slider focused doesn't delete the clip")
    check(win.playhead == ph and r2 is False, "R9-24: the arrow keys are the slider's")
    win.timeline.area.grab_focus()
    pump(0.1)
    check(key("Right") is True and win.playhead > ph, "with the timeline focused they step the film as before")

    # ---------------------------------------------------------------- R9-26: several clips drag together
    win.timeline.set_zoom(20.0)
    pump(0.2)
    v = clips("video")
    x, y = clip_xy(v[1])
    tl_click(x, y)
    x2, y2 = clip_xy(v[2])
    tl_click(x2, y2, ctrl=True)
    check(len(win.timeline.selected) == 4, "two clips and their sounds selected")
    tl_click(x2, y2, dx=400)
    settle()
    check(line() == "v: 0.00-8.00 28.00-36.00 36.00-44.00 | a: 0.00-8.00 28.00-36.00 36.00-44.00",
          "R9-26: dragging one of them takes both, 20 s along", line())
    win.run("undo")
    settle()

    # ---------------------------------------------------------------- R9-27: Trim Start off the clip
    x, y = clip_xy(clips("video")[0])
    tl_click(x, y)
    win.seek(20.0)
    win.run("trim-start")
    check(clips("video")[0]["duration"] == 8.0 and "playhead" in note(), "R9-27: Trim Start with the playhead elsewhere says so and trims nothing",
          note())

    # ---------------------------------------------------------------- R9-01, R9-22, R9-23: exports
    del MSGS[:]
    size = os.path.getsize(FILM)
    check(win.start_export(FILM, "mp4", "720p") is None and MSGS and os.path.getsize(FILM) == size,
          "R9-01: an export onto the project's own footage is refused in a message; the file is whole", MSGS)
    a, b = os.path.join(T, "a.mp4"), os.path.join(T, "b.mp4")
    win.start_export(a, "mp4", "720p")
    win.start_export(b, "mp4", "720p")
    win.project.set(clips("video")[0]["id"], color={"saturation": 0.0})       # after both were asked for
    check(wait(lambda: not win.exports and not win.export_queue, 180), "two exports, one after the other")
    pump(0.5)
    ca, cb = centre(a, 0.5), centre(b, 0.5)
    check(ca and cb and ca[0] > 200 and cb[0] > 200 and cb[1] < 60, "R9-22: the queued film is the project as it was when asked for",
          (ca, cb))
    win.run("undo")
    win.start_export(a, "mp4", "1080p")
    pump(0.5)
    win.cancel_exports()
    pump(1.0)
    check(os.path.exists(a) and centre(a, 0.5) == ca, "R9-23: cancelling an export over a film leaves that film")
    check(not [f for f in os.listdir(T) if f.endswith(".part")], "and nothing half-written beside it", os.listdir(T))

    # ---------------------------------------------------------------- R9-11: the lossless sound is made unasked
    check(wait(lambda: engine.sound_copy(FURI) is not None, 60), "R9-11: the film's sound has its lossless copy for clean cuts")

    # ---------------------------------------------------------------- R9-25, R9-35: subtitles, drops on the bin
    srt = os.path.join(T, "subs.srt")
    open(srt, "wb").write("1\r\n00:00:01,000 --> 00:00:02,000\r\nCaf\xe9 & <i>cr\xe8me</i>\r\n\r\n2\r\nnonsense\r\nlost\r\n".encode("cp1252"))
    win.run("import-subtitles:" + srt)
    caps = [c for c in clips("titles") if c["kind"] == "caption"]
    check(len(caps) == 1 and caps[0]["text"] == "Café & crème", "R9-25: a Windows-encoded .srt comes in right, tags off",
          [c["text"] for c in caps])
    check("1 couldn't be read" in note(), "R9-25: and the line that couldn't be read is counted", note())
    settle()

    def caption_pixels():
        win.flush()
        win.seek(1.5)
        win._do_seek()
        pump(0.4)
        pb = win.preview.snapshot()
        n_ = 0
        if pb is not None:
            px_, rs, nch = pb.get_pixels(), pb.get_rowstride(), pb.get_n_channels()
            for yy in range(int(pb.get_height() * 0.8), pb.get_height(), 3):
                for xx in range(0, pb.get_width(), 3):
                    o = yy * rs + xx * nch
                    n_ += px_[o] > 200 and px_[o + 1] > 200 and px_[o + 2] > 200
        return n_
    wait(lambda: caption_pixels() > 20, 20)
    lit = caption_pixels()
    check(lit > 20, "R9-06: the caption, ampersand and all, is drawn in the preview", lit)
    win.run("undo")
    folder = os.path.join(T, "shoot")
    os.makedirs(os.path.join(folder, "day2"))
    shutil.copy(MEDIA["red"], os.path.join(folder, "one.mp4"))
    shutil.copy(MEDIA["photo"], os.path.join(folder, "day2", "two.png"))
    open(os.path.join(folder, "notes.txt"), "w").write("not media")
    n = len(win.project.media)
    got = win.import_uris([model.path_to_uri(folder)])
    check(len(got) == 2 and len(win.project.media) == n + 2, "R9-35: a folder dropped on the bin brings in the media inside it", len(got))
    win.import_uris(["https://example.com/film.mp4"])
    check("not a file on this computer" in note(), "R9-35: a web link says what is wrong with it", note())

    # ---------------------------------------------------------------- R9-02: a project with a file gone
    d = os.path.join(T, "proj")
    os.makedirs(d)
    shutil.copy(FILM, os.path.join(d, "clip.mp4"))
    w2 = app.new_window()
    pump(0.4)
    w2.import_uris([model.path_to_uri(os.path.join(d, "clip.mp4")), URI["photo"]])
    w2.add_media_to_timeline([model.path_to_uri(os.path.join(d, "clip.mp4"))], at=0.0)
    w2.add_media_to_timeline([URI["photo"]], at=8.0)
    pf = os.path.join(d, "film.reel")
    check(w2.save(pf), "a project saved")
    w2.run("close")
    pump(0.5)
    os.rename(os.path.join(d, "clip.mp4"), os.path.join(T, "elsewhere.mp4"))
    del MSGS[:]
    w3 = app.open_path(pf)
    pump(1.0)
    check(w3 is not None and w3 in app.windows and w3.get_title().startswith("film.reel"), "R9-02: with a file gone the project still opens",
          w3 and w3.get_title())
    check(len(w3.project.track("video")) == 2 and len(w3.mediabin.store) == 2, "R9-02: with everything in it")
    check("couldn't be found" in note(w3) and "clip.mp4" in note(w3) and "Find File" in note(w3),
          "R9-02: and says which file is missing and what to do", note(w3))
    check(any("(missing)" in r[1] for r in w3.mediabin.store), "R9-02: the bin marks it")
    check(w3.missing_warnings(), "R9-02: an export would warn that its clips are left out", w3.missing_warnings())
    w3.mediabin.select_uri([m["uri"] for m in w3.project.media if m["name"] == "clip.mp4"][0])
    w3.run("find-media:" + os.path.join(T, "elsewhere.mp4"))
    pump(0.5)
    check(not w3.project.missing_media() and not w3.missing_warnings() and not any("(missing)" in r[1] for r in w3.mediabin.store),
          "R9-02: Find File puts it right", note(w3))
    w3.flush()
    pump(0.5)
    w3.seek(1.5)
    w3._do_seek()
    pump(0.4)
    pb = w3.preview.snapshot()
    px1 = tuple(pb.scale_simple(1, 1, 2).get_pixels()[:3]) if pb is not None else None
    check(px1 and px1[1] > 90 and px1[0] < 60, "R9-02: and the clip plays again", px1)
    w3.project.dirty = False
    w3.run("close")
    pump(0.5)

    # ---------------------------------------------------------------- R9-15: files that aren't projects
    for name, txt in (("empty.reel", ""), ("object.reel", "{}"), ("list.reel", "[]"), ("shape.reel", '{"tracks": []}')):
        fp = os.path.join(T, name)
        open(fp, "w").write(txt)
        del MSGS[:]
        n = len(app.windows)
        try:
            app.open_path(fp)
            ok = True
        except Exception:
            ok = False
        pump(0.3)
        check(ok and len(MSGS) == 1 and "couldn't be opened" in MSGS[0] and len(app.windows) == n,
              "R9-15: %s is refused with a message, and no stray window" % name, (ok, MSGS, len(app.windows) - n))

    # ---------------------------------------------------------------- R9-30: the preview after opening
    pf2 = os.path.join(T, "show.reel")
    win.project.set(clips("video")[0]["id"], color={"saturation": 1.0})
    check(win.save(pf2), "saved")
    w4 = app.new_window(pf2)
    pump(1.5)
    img = shot("b9_opened", w4)
    a_ = w4.preview_widget.get_allocation()
    wx, wy = w4.preview_widget.translate_coordinates(w4, a_.width // 2, a_.height // 2)
    r, g, b_ = pixel(img, wx, wy)
    check(r > 150 and g < 80 and b_ < 80, "R9-30: a project just opened shows its first picture", (r, g, b_))
    w4.run("close")
    pump(0.5)

    # ---------------------------------------------------------------- R9-31: nothing to save after undoing back
    win.project.set(clips("video")[0]["id"], volume=0.5)
    was_dirty = win.project.dirty
    win.run("undo")
    check(was_dirty and not win.project.dirty, "R9-31: a change undone leaves the saved project as it was saved")

    # ---------------------------------------------------------------- the recovery copy
    win.project.set(clips("video")[0]["id"], volume=0.5)
    win._keep_recovery()
    f = os.path.join(recovery.folder(), win.recovery_id + ".json")
    check(os.path.exists(f) and recovery.pending() == [], "with unsaved changes a recovery copy is kept; it isn't offered while Reel runs")
    win.save()
    check(not os.path.exists(f), "saving removes it")
    win.project.set(clips("video")[0]["id"], volume=0.7)
    win._keep_recovery()
    dd = json.load(open(f))
    dd["pid"] = 2 ** 22 + 4321                      # as if that Reel had died
    os.rename(f, os.path.join(recovery.folder(), "dead.json"))
    json.dump(dd, open(os.path.join(recovery.folder(), "dead.json"), "w"))
    win._recovery_stamp = None
    n = len(app.windows)
    app._recovery_asked = False
    respond_app = {"done": False}

    def answer():
        d_ = getattr(app, "recovery_dialog", None)
        if d_ is None:
            return True
        respond_app["done"] = True
        d_.response(Gtk.ResponseType.YES)
        return False
    GLib.timeout_add(300, answer)
    app.offer_recovery()
    pump(1.0)
    w5 = app.windows[-1]
    check(respond_app["done"] and len(app.windows) == n + 1 and len(w5.project.track("video")) == 3
          and abs(w5.project.track("video")[0]["volume"] - 0.7) < 1e-6 and w5.project.dirty,
          "a copy left by a Reel that died is offered at the next start, and Recover opens it with its changes",
          (respond_app, len(app.windows) - n))
    check(recovery.pending() == [], "once answered it isn't offered again")
    w5.project.dirty = False
    w5.run("close")
    win.project.dirty = False
    shutil.rmtree(T, ignore_errors=True)
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
finish()
