# Folio Reel, driven as a user would (R3-01..R3-06, R3-09, R3-10). Run with run_ui.sh ui_basic.py.
import os
import time
import tempfile
import traceback

exec(open(os.path.join(os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"]),
                       "uicommon.py")).read())

try:
    T = tempfile.mkdtemp(prefix="reel_ui_")
    pump(0.5)
    # ---------------------------------------------------------------- the window (R3-09, R3-10)
    check(win.get_title() == "Project1 - Folio Reel", "a new window is Project1", win.get_title())
    check([t.name for t in win.ribbon.tabs] == ["Home", "Insert", "Transitions", "Effects", "Audio", "View"],
          "ribbon tabs", [t.name for t in win.ribbon.tabs])
    check(win.header.get_style_context().has_class("folio-titlebar"), "the title bar is the suite's")
    img = shot("01_new")
    r, g, b = pixel(img, 300, 4)
    check(b > 80 and r < 60 and g < 90, "the title bar is navy blue", (r, g, b))
    r, g, b = pixel(img, 5, 50)
    check(r > 200 and g > 200 and b > 200, "the ribbon isn't coloured", (r, g, b))
    tips = [c for c in win.ribbon.controls if (c.get_tooltip_markup() or "").count("<b>")]
    check(len(tips) > 20, "ScreenTips: the ribbon's buttons have a title and a description", len(tips))

    # ---------------------------------------------------------------- media bin (R3-01)
    ms = win.import_uris([URI[k] for k in ("red", "blue", "photo", "music", "speech", "silent")])
    pump(0.5)
    check(len(ms) == 6 and len(win.mediabin.store) == 6, "Import Media: six files in the bin", len(win.mediabin.store))
    check(not win.mediabin.empty.get_visible(), "the bin's hint goes away")
    bad = os.path.join(T, "notmedia.mp4")
    open(bad, "w").write("x" * 500)
    win.import_uris(["file://" + bad])
    check("Couldn't import" in win.notice_label.get_text(), "a file that isn't media says so", win.notice_label.get_text())
    win.mediabin.select_uri(URI["red"])
    win.run("add-to-timeline")
    path = [r.path for r in win.mediabin.store if r[2] == URI["blue"]][0]
    win.mediabin.view.item_activated(path)
    pump(0.3)
    v = clips("video")
    check(len(v) == 2 and v[1]["start"] > 3.9, "double-click / Add to Timeline: two clips one after another",
          [(c["name"], c["start"]) for c in v])
    win.add_media_to_timeline([URI["music"]], track="music", at=0)
    check(len(clips("music")) == 1, "music on the Music track")
    win.add_media_to_timeline([URI["silent"]], track="audio", at=0)
    check(not clips("audio") and len(clips("video")) == 3, "a silent video dropped on Audio goes to the Video track")
    win.run("undo")
    pump(0.2)
    settle()
    # R4-01: the music clip's waveform is read and drawn
    mclip = clips("music")[0]
    win.timeline._wave(mclip)
    check(wait(lambda: win.timeline._wave(mclip), 20), "the timeline reads the sound of a clip")
    peaks = win.timeline._wave(mclip)
    check(peaks and 0.2 < max(peaks) <= 1.0, "with peaks to draw", peaks and max(peaks))
    settle()
    shot("02_clips")

    # ---------------------------------------------------------------- the timeline: select, move, snap, trim
    win.timeline.zoom_fit()
    pump(0.2)
    red, blue = clips("video")
    x, y = clip_xy(blue)
    tl_click(x, y)
    check(win.timeline.selected == [blue["id"]], "clicking a clip selects it")
    check(win.clipset.cid == blue["id"], "Clip Settings shows it")
    pps = win.timeline.pps
    tl_click(x, y, dx=2.0 * pps)
    blue = win.project.clip(blue["id"])
    check(abs(blue["start"] - 6.0) < 0.15, "drag a clip later", blue["start"])
    x, y = clip_xy(blue)
    tl_click(x, y, dx=-(blue["start"] - red["duration"]) * pps + 4)
    blue = win.project.clip(blue["id"])
    check(abs(blue["start"] - red["duration"]) < 0.01, "and back: it snaps to the end of the clip before", blue["start"])
    x0 = win.timeline.x_of(blue["start"] + blue["duration"]) - 2
    tl_click(x0, y, dx=-1.0 * pps)
    blue = win.project.clip(blue["id"])
    check(abs(blue["duration"] - 3.0) < 0.15, "drag the end to trim", blue["duration"])
    win.run("undo")
    blue = win.project.clip(blue["id"])
    check(abs(blue["duration"] - 4.0) < 0.1, "Undo")
    # Ctrl+click adds to the selection
    rx, ry = clip_xy(red)
    tl_click(rx, ry, ctrl=True)
    check(set(win.timeline.selected) == {red["id"], blue["id"]}, "Ctrl+click selects more")
    def _labels(w):
        if isinstance(w, Gtk.Label):
            yield w.get_text()
        elif isinstance(w, Gtk.Container):
            for ch in w.get_children():
                yield from _labels(ch)
    check(any("2 clips selected" in t for t in _labels(win.clipset)), "Clip Settings says so")
    # click on the ruler moves the playhead
    tl_click(win.timeline.x_of(1.5), 10)
    check(abs(win.playhead - 1.5) < 0.05, "a click on the ruler moves the playhead", win.playhead)
    check(win.timecode.get_text().startswith("0:00:01:15"), "the timecode shows it (frames)", win.timecode.get_text())

    # ---------------------------------------------------------------- split, delete, ripple delete
    win.timeline.select([red["id"]])
    key("s")
    v = clips("video")
    check(len(v) == 3 and abs(v[0]["duration"] - 1.5) < 0.05, "S splits at the playhead", [c["duration"] for c in v])
    key("Delete")
    v = clips("video")
    check(len(v) == 2 and v[1]["start"] > 1.4, "Delete leaves a gap", [c["start"] for c in v])
    key("z", ctrl=True)
    win.timeline.select([clips("video")[1]["id"]])
    key("Delete", shift=True)
    v = clips("video")
    check(len(v) == 2 and abs(v[1]["start"] - 1.5) < 0.05, "Shift+Delete ripples", [c["start"] for c in v])
    key("z", ctrl=True)
    key("z", ctrl=True)
    v = clips("video")
    check(len(v) == 2 and abs(v[0]["duration"] - 4.01) < 0.05, "Undo back to two clips", [c["duration"] for c in v])
    red, blue = v
    # Trim Start / Trim End at the playhead
    win.seek(1.0)
    win.timeline.select([red["id"]])
    win.run("trim-start")
    red = win.project.clip(red["id"])
    check(abs(red["start"] - 1.0) < 0.01 and abs(red["inpoint"] - 1.0) < 0.01, "Trim Start at the playhead")
    win.run("undo")
    red = win.project.clip(red["id"])

    # ---------------------------------------------------------------- cut, copy, paste
    win.timeline.select([red["id"]])
    key("c", ctrl=True)
    win.seek(win.project.duration())
    key("v", ctrl=True)
    v = clips("video")
    check(len(v) == 3 and v[2]["name"] == red["name"], "Copy and Paste at the playhead", [c["name"] for c in v])
    key("x", ctrl=True)
    check(len(clips("video")) == 2, "Cut")
    win.run("undo")
    win.run("undo")
    check(len(clips("video")) == 2 and len(clips("music")) == 1, "undone", len(clips("video")))

    # ---------------------------------------------------------------- preview (R3-02)
    settle()
    c1 = snap_rgb(1.0)
    c2 = snap_rgb(6.0)
    check(c1 and c1[0] > 150 and c1[2] < 80, "the preview shows the red clip at 1 s", c1)
    check(c2 and c2[2] > 150 and c2[0] < 80, "and the blue one at 6 s", c2)
    win.seek(2.0)
    win._do_seek()
    key("Right")
    check(abs(win.playhead - (2.0 + 1 / 30.0)) < 0.01, "Right: one frame on", win.playhead)
    key("Left")
    key("Left")
    check(abs(win.playhead - (2.0 - 1 / 30.0)) < 0.01, "Left: one frame back", win.playhead)
    key("Right", shift=True)
    check(abs(win.playhead - (3.0 - 1 / 30.0)) < 0.01, "Shift+Right: a second on", win.playhead)
    win.seek(0.5)
    win._do_seek()
    key("space")
    check(win.playing, "Space plays")
    pump(1.2)
    p1 = win.playhead
    check(p1 > 1.0, "the playhead moves while playing", p1)
    # R4-01: the level meter follows the sound coming out
    check(wait(lambda: max(win.levels) > 0.05, 6), "the level meter shows the output while it plays", win.levels)
    shot("02b_playing")
    check(max(win.level_hold) >= max(win.levels) - 1e-6, "and holds the loudest reading", (win.levels, win.level_hold))
    key("k")
    check(not win.playing, "K stops")
    check(max(win.levels) == 0.0, "the meter falls back to nothing when it stops", win.levels)
    p2 = win.playhead
    key("l")
    key("l")
    check(win.shuttle == 2 and win.preview.rate == 2.0, "L L: twice the speed", (win.shuttle, win.preview.rate))
    t0 = time.time()
    pump(2.0)
    elapsed = time.time() - t0
    # faster than real time, with room for a machine that is busy with something else
    check(win.playhead - p2 > elapsed * 1.25, "and it goes faster than real time",
          (round(win.playhead - p2, 2), round(elapsed, 2)))
    key("k")
    p3 = win.playhead
    key("j")
    pump(0.8)
    check(win.playhead < p3 - 0.3, "J plays backwards", (p3, win.playhead))
    key("k")
    check(win.shuttle == 0 and not win.playing, "K stops that too")
    key("Home")
    check(win.playhead == 0.0, "Home: the start")
    key("End")
    check(abs(win.playhead - win.project.duration()) < 0.01, "End: the end")
    # full screen
    win.run("full-screen")
    pump(0.6)
    check(win.full is not None and win.preview_widget.get_parent() is win.full.frame, "Full Screen: the preview fills the screen")
    key("Escape", w=win.full)
    pump(0.3)
    check(win.full is None and win.preview_widget.get_parent() is win.preview_frame, "Esc comes back")

    # ---------------------------------------------------------------- transitions and effects (R3-03)
    red, blue = clips("video")
    win.timeline.select([blue["id"]])
    win.run("transition:crossfade")
    blue = win.project.clip(blue["id"])
    check(blue["transition"] and blue["transition"]["type"] == "crossfade" and blue["start"] < red["duration"] - 0.9,
          "Transitions > Crossfade overlaps the clips", blue["transition"])
    win.run("transition-duration:0.5")
    blue = win.project.clip(blue["id"])
    check(abs(blue["transition"]["duration"] - 0.5) < 1e-6, "Duration 0.5 s")
    check(win.clipset.controls.get("transition").get_active_text() == "Crossfade", "Clip Settings shows the transition")
    settle()
    mid = snap_rgb(blue["start"] + 0.25)
    check(mid and mid[0] > 70 and mid[2] > 70, "halfway through, both pictures", mid)
    win.run("transition:wipe-right")
    check(win.project.clip(blue["id"])["transition"]["type"] == "wipe-right", "Wipe Right")
    win.run("transition:none")
    check(win.project.clip(blue["id"])["transition"] is None, "None")
    win.timeline.select([red["id"]])
    win.run("color:bw")
    settle()
    g = snap_rgb(1.0)
    check(g and max(g) - min(g) < 30, "Black and White", g)
    win.run("color:reset")
    win.run("speed:2")
    red = win.project.clip(red["id"])
    check(abs(red["duration"] - 2.0) < 0.05 and abs(win.project.clip(blue["id"])["start"] - 2.0) < 0.05,
          "Speed 2×: the clip halves and the next follows", red["duration"])
    win.run("undo")
    win.run("fade-in:1")
    check(win.project.clip(red["id"])["fade_in"] == 1.0, "Fade In 1 s")
    settle()
    f0 = snap_rgb(0.05)
    check(f0 and sum(f0) < 120, "the clip starts from black", f0)
    win.run("undo")
    ph = win.add_media_to_timeline([URI["photo"]], track="video", at=win.project.duration())
    win.run("panzoom:in")
    check(win.project.clip(ph[0])["panzoom"] == "in", "Pan and Zoom on a picture")
    respond("crop_dialog", Gtk.ResponseType.OK, setup=lambda d: d[1]["l"].set_value(10))
    win.run("crop")
    check(abs(win.project.clip(ph[0])["crop"]["l"] - 0.1) < 1e-6, "Crop: 10% off the left")
    win.run("undo")
    win.run("undo")
    win.run("undo")

    # ---------------------------------------------------------------- titles (R3-04)
    win.seek(0.5)
    win._do_seek()
    win.run("insert-title")
    pump(0.3)
    t = clips("titles")
    check(len(t) == 1 and t[0]["kind"] == "title", "Insert > Title at the playhead", t)
    tv = win.clipset.controls.get("text")
    # is_focus(): the window's focus is on the box. has_focus() also needs the window to be the
    # active one, which a headless Wayland compositor doesn't hand out.
    check(tv is not None and (tv.has_focus() or tv.is_focus()), "its text is ready to type over")
    tv.get_buffer().set_text("My Holiday")
    pump(0.2)
    check(clips("titles")[0]["text"] == "My Holiday" and clips("titles")[0]["name"] == "My Holiday", "typing changes the title")
    fb = win.clipset.controls["font"]
    fb.set_font("Serif Bold 72")
    fb.emit("font-set")
    check(clips("titles")[0]["font"] == "Serif Bold 72", "the font")
    settle()
    tc = snap_rgb(1.0)
    check(tc and tc[0] < 140, "a title card covers the picture", tc)
    win.seek(6.0)
    win.run("insert-lower-third")
    lt = [c for c in clips("titles") if c["kind"] == "lower-third"]
    check(lt and lt[0]["valign"] == "bottom", "a lower third")
    settle()
    lt_rgb = snap_rgb(7.0)
    check(lt_rgb and lt_rgb[2] > 150, "it leaves the picture showing", lt_rgb)
    win.run("insert-caption")
    check(any(c["kind"] == "caption" for c in clips("titles")), "a caption (after the lower third: no overlap)",
          [c["start"] for c in clips("titles")])

    # ---------------------------------------------------------------- R4-04 preview size, proxies
    check(win.run("preview-quality:2") == 2 and win.preview.preview_size() ==
          (win.project.width // 2, win.project.height // 2), "Half Size draws a smaller preview",
          win.preview.preview_size())
    check(win.app.settings.get("preview_quality") == 2, "and it is remembered")
    win.run("preview-quality:1")
    check(win.preview.preview_size() == (win.project.width, win.project.height), "Full Size again",
          win.preview.preview_size())
    from folio_reel import engine as _eng
    _eng.forget_proxies()
    win.run("use-proxies:on")
    check(win.app.settings.get("use_proxies") and win.preview.proxies, "the preview can be told to use small copies")
    check(win.playing is False and win.preview.duration() > 0, "with none made yet, it plays as before",
          win.preview.duration())
    win.mediabin.select_uri(URI["red"])
    n = win.run("make-proxies")
    pump(0.3)
    check(n == 1 and os.path.exists(_eng.proxy_path(URI["red"])), "Make Small Copies makes one for the chosen film", n)
    check(win.preview.duration() > 0, "and the preview still plays", win.preview.duration())
    check(win.run("remove-proxies") >= 1 and not os.path.exists(_eng.proxy_path(URI["red"])),
          "Remove Small Copies throws them away")
    check(not win.app.settings.get("use_proxies") and not win.preview.proxies, "and goes back to the originals")

    # ---------------------------------------------------------------- R4-03 subtitles
    srt_in = os.path.join(OUT, "in.srt")
    open(srt_in, "w").write("1\n00:00:00,500 --> 00:00:02,000\nFirst subtitle\n\n"
                            "2\n00:00:02,500 --> 00:00:04,000\nSecond subtitle\n")
    before = len([c for c in clips("titles") if c["kind"] == "caption"])
    win.run("import-subtitles:%s" % srt_in)
    pump(0.3)
    caps = [c for c in clips("titles") if c["kind"] == "caption"]
    check(len(caps) == before + 2, "Import Subtitles puts them on the Titles track", len(caps))
    check(any(c["text"] == "First subtitle" for c in caps), "with their words", [c["text"] for c in caps])
    srt_out = os.path.join(OUT, "out.srt")
    win.run("export-subtitles:%s" % srt_out)
    pump(0.3)
    written = open(srt_out).read()
    check("First subtitle" in written and "-->" in written, "Export Subtitles writes an .srt", written[:40])
    from folio_reel import subtitles as _subs
    check(len(_subs.parse(written)) == len(caps), "holding every caption", len(_subs.parse(written)))
    win.run("undo")
    pump(0.2)
    check(len([c for c in clips("titles") if c["kind"] == "caption"]) == before, "undo takes them off again")

    # ---------------------------------------------------------------- R4-02 chroma key
    vid = clips("video")[0]
    win.timeline.select([vid["id"]])
    settle()
    ck = win.clipset.controls.get("chroma")
    check(ck is not None and not ck.get_active(), "Clip Settings has a chroma key, off to begin with")
    ck.set_active(True)
    pump(0.3)
    check(win.project.clip(vid["id"])["chroma"], "ticking it keys the clip")
    tol = win.clipset.controls.get("chroma_tolerance")
    tol.set_value(35)
    pump(0.3)
    check(abs(win.project.clip(vid["id"])["chroma_tolerance"] - 35) < 0.01, "and the tolerance follows the slider",
          win.project.clip(vid["id"])["chroma_tolerance"])
    win.run("undo")
    win.run("undo")
    pump(0.2)
    check(not win.project.clip(vid["id"])["chroma"], "undo takes the key off again")

    # ---------------------------------------------------------------- sound (R3-05)
    mus = clips("music")[0]
    win.timeline.select([mus["id"]])
    win.run("volume:0.5")
    check(win.project.clip(mus["id"])["volume"] == 0.5, "Volume 50%")
    win.run("music-bed")
    check(win.project.clip(mus["id"])["music_bed"], "Music Bed")
    check(win.clipset.controls["music_bed"].get_active(), "Clip Settings shows it")
    win.add_media_to_timeline([URI["speech"]], track="audio", at=2.0)
    from folio_reel import engine as _eng
    gp = _eng.gain_points(win.project, win.project.clip(mus["id"]))
    check(_eng._piecewise(gp, 3.0) < 0.2 and _eng._piecewise(gp, 0.5) > 0.4, "the music dips under the voice-over", gp)
    win.timeline.select([mus["id"]])
    win.seek(9.0)
    win.run("keyframe-dip")
    kf = win.project.clip(mus["id"])["keyframes"]
    check(len(kf) == 4, "Dip Here: volume points around the playhead", kf)
    win.clipset.refresh()
    k1 = win.clipset.controls.get("kf1")
    check(k1 is not None, "the points are in Clip Settings")
    n_undo = len(win.project.undo_stack)
    for v in (25, 20, 15, 10):
        k1.set_value(v)
    check(len(win.project.undo_stack) == n_undo + 1, "dragging a level is one undo step", len(win.project.undo_stack) - n_undo)
    win.run("keyframe-clear")
    check(not win.project.clip(mus["id"])["keyframes"], "Clear Points")
    red = clips("video")[0]
    win.timeline.select([red["id"]])
    win.run("mute")
    check(win.project.clip(red["id"])["muted"], "Mute")
    vol = win.clipset.controls.get("volume")
    n_undo = len(win.project.undo_stack)
    for v in (90, 80, 70):
        vol.set_value(v)
    check(abs(win.project.clip(red["id"])["volume"] - 0.7) < 1e-6 and len(win.project.undo_stack) == n_undo + 1,
          "the volume slider: one undo step")
    shot("03_edited")

    # ---------------------------------------------------------------- export while editing (R3-06)
    settle()
    out = os.path.join(T, "film.mp4")
    ex = win.start_export(out, "mp4", "720p")
    pump(0.3)
    check(ex is not None and win.export_box.get_visible(), "Export: progress in the status bar")
    win.timeline.select([clips("video")[1]["id"]])
    win.run("color:darker")
    check(win.project.clip(clips("video")[1]["id"])["color"]["brightness"] < 0, "editing carries on while it renders")
    ok = wait(lambda: ex.done, 240)
    check(ok and ex.error is None and os.path.exists(out), "the video is made", ex.error)
    if os.path.exists(out):
        d, size = mkmedia.media_duration(out)
        check(abs(d - win.project.duration()) < 0.3 and size == (1280, 720), "720p, the project's length",
              (d, size, win.project.duration()))
        fc = mkmedia.frame_color(out, 6.0)
        check(fc and fc[2] > 150, "the render is the project as it was when Export started (not darker)", fc)
    check("Exported film.mp4" in win.notice_label.get_text(), "it says so", win.notice_label.get_text())
    check(not win.export_box.get_visible(), "the progress goes away")
    out2 = os.path.join(T, "film.webm")
    ex = win.start_export(out2, "webm", "720p")
    pump(0.5)
    win.cancel_exports()
    pump(0.5)
    check(ex.done and not os.path.exists(out2) and "cancelled" in win.notice_label.get_text(), "Cancel stops an export")
    win.app.settings["export_format"] = "webm"
    win.show_backstage("export")
    pump(0.3)
    check(win.backstage.fmt.get_active_id() == "webm", "File > Export remembers the format")
    key("Escape")
    check(not win.backstage_open(), "Esc closes File")

    # ---------------------------------------------------------------- R4-05 markers
    win.run("marker-clear")
    win.seek(1.0)
    pump(0.1)
    key("m")
    check(len(win.project.markers()) == 1 and abs(win.project.markers()[0]["t"] - 1.0) < 0.01,
          "M puts a marker at the playhead", win.project.markers())
    win.seek(3.0)
    key("m")
    check(len(win.project.markers()) == 2, "and another one further along", win.project.markers())
    # Shift+M names it; the box is answered as a user would
    respond("marker_dialog", Gtk.ResponseType.OK, setup=lambda d: d[1]["name"].set_text("Chorus"))
    key("m", shift=True)
    pump(0.2)
    here = win.project.marker_at(3.0, 0.1)
    check(here is not None and here["name"] == "Chorus", "Shift+M names the marker", win.project.markers())
    # , and . walk between them
    win.seek(0.0)
    key("period")
    check(abs(win.playhead - 1.0) < 0.01, "'.' goes to the next marker", win.playhead)
    key("period")
    check(abs(win.playhead - 3.0) < 0.01, "and on to the one after", win.playhead)
    key("comma")
    check(abs(win.playhead - 1.0) < 0.01, "',' goes back", win.playhead)
    # the flag shows on the ruler, in its colour
    win.timeline.set_zoom(60)
    win.timeline.show_time(1.0)
    pump(0.2)
    shot("20_markers")
    # the flag itself: the timeline drawn into a picture, so this reads the same on X and Wayland
    import cairo
    tw = win.timeline.area.get_allocated_width()
    th = win.timeline.area.get_allocated_height()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(tw, 1), max(th, 1))
    win.timeline._draw(win.timeline.area, cairo.Context(surf))
    data, stride = surf.get_data(), surf.get_stride()

    def tl_pixel(x, y):
        o = int(y) * stride + int(x) * 4
        return data[o + 2], data[o + 1], data[o]

    mx = int(win.timeline.x_of(3.0))
    seen = []
    found = None
    for dx in range(1, 9):
        r, g, b = tl_pixel(mx + dx, 18)
        seen.append((r, g, b))
        if r > 180 and 120 < g < 230 and b < 130:
            found = (r, g, b)
            break
    check(found is not None, "the marker's flag is drawn on the ruler in yellow", seen)
    # clicking the flag goes to it
    win.seek(0.0)
    pump(0.1)
    tl_click(win.timeline.x_of(3.0) + 2, 18)
    check(abs(win.playhead - 3.0) < 0.01, "clicking the flag goes to that marker", win.playhead)
    check(win.notice_label.get_text() == "Chorus", "and says its name", win.notice_label.get_text())
    # a clip snaps to a marker
    check(3.0 in win.project.snap_points(), "clips snap to markers", win.project.snap_points()[:6])
    # delete this one, then all of them
    win.seek(3.0)
    win.run("marker-delete")
    check(len(win.project.markers()) == 1, "Delete This Marker takes one away", win.project.markers())
    win.run("marker-clear")
    check(win.project.markers() == [], "Delete All Markers empties the ruler")
    win.run("undo")
    win.run("undo")
    check(len(win.project.markers()) == 2, "and undo brings them back", win.project.markers())

    # ---------------------------------------------------------------- save and open
    proj = os.path.join(T, "My Film.reel")
    check(win.save(proj), "Save")
    check(win.get_title() == "My Film.reel - Folio Reel", "the title follows", win.get_title())
    w2 = win.app.new_window()
    pump(0.5)
    w2.open_file(proj)
    pump(0.5)
    check(len(w2.project.track("video")) == len(clips("video")) and len(w2.project.media) == 6 and
          w2.project.track("titles")[0]["text"] == "My Holiday", "Open: the project comes back")
    check(w2.path == proj and w2.app.recent()[0] == proj, "and is in Recent")
    w2.destroy()
    w2.app.window_closed(w2)

    # ---------------------------------------------------------------- KeyTips and search
    key_release("Alt_L")
    win._alt_alone = True
    key_release("Alt_L")
    check(win.keytips.active, "Alt shows KeyTips")
    key("n")
    check(win.ribbon.current.name == "Insert", "N: the Insert tab", win.ribbon.current.name)
    if win.keytips.active:
        key("Escape")
        key("Escape")
    win.search.set_text("zoom to fit")
    win.on_search(win.search)
    check(win.search.get_text() == "", "Search runs a command")
    shot("04_final")

    # ---------------------------------------------------------------- closing with changes
    win.timeline.select([clips("video")[0]["id"]])
    win.run("volume:0.3")
    respond("close_dialog", Gtk.ResponseType.CANCEL)
    kept = win.on_delete(win, None)
    check(kept, "Close with changes asks; Cancel keeps the window")
    respond("close_dialog", Gtk.ResponseType.YES)
    closed = not win.on_delete(win, None)
    from folio_reel import model as _m
    check(closed and _m.Project.load(proj).track("video")[0]["volume"] == 0.3, "Save on close")
except Exception:
    traceback.print_exc()
    FAILS.append("exception")
finish()
