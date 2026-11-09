"""Clip Settings: the selected clip's speed, sound, colour, picture, transition and text
(R3-03, R3-04, R3-05). Every change is an undoable edit; a slider being dragged is one step."""
from gi.repository import Gdk, Gtk, Pango

from . import model
from .model import TRANSITIONS

POSITIONS = [("Top left", "left", "top"), ("Top", "center", "top"), ("Top right", "right", "top"),
             ("Left", "left", "center"), ("Middle", "center", "center"), ("Right", "right", "center"),
             ("Bottom left", "left", "bottom"), ("Bottom", "center", "bottom"), ("Bottom right", "right", "bottom")]
PANZOOM = [("None", None), ("Zoom In", "in"), ("Zoom Out", "out"), ("Pan Left to Right", "right"),
           ("Pan Right to Left", "left")]
SPEEDS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]


def _rgba(hexstr):
    h = hexstr.lstrip("#")
    if len(h) == 6:
        h = "ff" + h
    a, r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4, 6))
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def _hex(rgba):
    return "#%02x%02x%02x%02x" % tuple(int(round(v * 255)) for v in (rgba.alpha, rgba.red, rgba.green, rgba.blue))


class ClipSettings(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.get_style_context().add_class("reel-props")
        self.set_size_request(270, -1)
        title = Gtk.Label(label="Clip Settings", xalign=0)
        title.get_style_context().add_class("reel-pane-title")
        self.pack_start(title, False, False, 0)
        self.sw = Gtk.ScrolledWindow()
        self.sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.pack_start(self.sw, True, True, 0)
        self.cid = None
        self.controls = {}
        self._quiet = False
        self.refresh()

    # ------------------------------------------------------------ building
    def refresh(self, force=True):
        clips = self.win.timeline.selected_clips() if hasattr(self.win, "timeline") else []
        c = clips[0] if len(clips) == 1 else None
        if not force and c is not None and c["id"] == self.cid:
            self._update_values(c)
            return
        self.cid = c["id"] if c else None
        child = self.sw.get_child()
        if child is not None:
            self.sw.remove(child)
        self.controls = {}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(10)
        box.set_margin_end(10)
        box.set_margin_bottom(10)
        if c is None:
            hint = Gtk.Label(label="Select a clip on the timeline to change it." if len(clips) != 1 else "")
            if len(clips) > 1:
                hint.set_text("%d clips selected. Volume, speed, fades and colour on the ribbon change all of them." % len(clips))
            hint.set_line_wrap(True)
            hint.set_max_width_chars(28)
            hint.get_style_context().add_class("reel-hint")
            hint.set_margin_top(12)
            box.pack_start(hint, False, False, 0)
        else:
            self._build(box, c)
        self.sw.add(box)
        self.sw.show_all()

    def _section(self, box, text):
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s</b>" % text)
        lab.set_margin_top(10)
        box.pack_start(lab, False, False, 0)

    def _row(self, box, label, widget):
        row = Gtk.Box(spacing=6)
        lab = Gtk.Label(label=label, xalign=0)
        lab.set_size_request(86, -1)
        row.pack_start(lab, False, False, 0)
        row.pack_start(widget, True, True, 0)
        box.pack_start(row, False, False, 0)
        return widget

    def _scale(self, key, lo, hi, step, value, fmt, on_change):
        sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        sc.set_value(value)
        sc.set_digits(2 if step < 0.1 else 0)
        sc.set_value_pos(Gtk.PositionType.RIGHT)
        sc.connect("format-value", lambda s, v: fmt(v))
        sc.connect("value-changed", lambda s: self._quiet or on_change(s.get_value()))
        self.controls[key] = sc
        return sc

    def _spin(self, key, lo, hi, step, value, on_change, digits=1):
        sp = Gtk.SpinButton.new_with_range(lo, hi, step)
        sp.set_digits(digits)
        sp.set_value(value)
        sp.connect("value-changed", lambda s: self._quiet or on_change(s.get_value()))
        self.controls[key] = sp
        return sp

    def _combo(self, key, items, active, on_change):
        cb = Gtk.ComboBoxText()
        for it in items:
            cb.append_text(it)
        cb.set_active(active)
        cb.connect("changed", lambda w: self._quiet or on_change(w.get_active()))
        self.controls[key] = cb
        return cb

    def _set(self, label, **props):
        self.win.edit(lambda p: p.set(self.cid, label=label, merge=True, **props), own=True)

    def _build(self, box, c):
        p = self.win.project
        track = p.find(c["id"])[0]
        m = p.media_by_uri(c["media"]) if c["kind"] == "media" else None
        name = Gtk.Label(xalign=0)
        name.set_markup("<b>%s</b>" % (c["name"].replace("&", "&amp;").replace("<", "&lt;")))
        name.set_ellipsize(Pango.EllipsizeMode.END)
        box.pack_start(name, False, False, 0)
        times = Gtk.Label(xalign=0)
        times.get_style_context().add_class("reel-hint")
        self.controls["times"] = times
        box.pack_start(times, False, False, 0)
        if c["kind"] == "media" and m is None:
            warn = Gtk.Label(label="The media file for this clip is missing.", xalign=0)
            box.pack_start(warn, False, False, 0)
        # ---- text (R3-04)
        if c["kind"] != "media":
            self._section(box, "Text")
            tv = Gtk.TextView()
            tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
            tv.get_buffer().set_text(c.get("text", ""))
            tv.set_size_request(-1, 60)
            tv.get_buffer().connect("changed", lambda b: self._quiet or self._set(
                "Title Text", text=b.get_text(b.get_start_iter(), b.get_end_iter(), False)))
            self.controls["text"] = tv
            frame = Gtk.Frame()
            frame.add(tv)
            box.pack_start(frame, False, False, 0)
            fb = Gtk.FontButton.new_with_font(c.get("font", "Sans Bold 48"))
            fb.connect("font-set", lambda b: self._set("Font", font=b.get_font()))
            self.controls["font"] = fb
            self._row(box, "Font", fb)
            tc = Gtk.ColorButton.new_with_rgba(_rgba(c.get("text_color", "#ffffffff")))
            tc.set_use_alpha(True)
            tc.connect("color-set", lambda b: self._set("Text Colour", text_color=_hex(b.get_rgba())))
            self.controls["text_color"] = tc
            self._row(box, "Text colour", tc)
            bc = Gtk.ColorButton.new_with_rgba(_rgba(c.get("bg_color", "#ff000000")))
            bc.set_use_alpha(True)
            bc.set_title("Background (see-through: lower the opacity)")
            bc.connect("color-set", lambda b: self._set("Background", bg_color=_hex(b.get_rgba())))
            self.controls["bg_color"] = bc
            self._row(box, "Background", bc)
            cur = [i for i, (_l, h, v) in enumerate(POSITIONS) if h == c.get("halign") and v == c.get("valign")]
            self._row(box, "Position", self._combo("position", [l for l, _h, _v in POSITIONS], cur[0] if cur else 4,
                                                   lambda i: self._set("Text Position", halign=POSITIONS[i][1],
                                                                       valign=POSITIONS[i][2])))
        # ---- speed (R3-03)
        if m is not None and not m.get("is_image"):
            self._section(box, "Speed")
            sp = c.get("speed", 1.0)
            idx = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - sp))
            self._row(box, "Speed", self._combo("speed", ["%g×" % s for s in SPEEDS], idx,
                                                lambda i: self.win.edit(lambda p: p.set_speed(self.cid, SPEEDS[i]))))
        # ---- sound (R3-05)
        has_sound = m is not None and m.get("has_audio") and not c.get("sound_elsewhere")
        if c.get("sound_elsewhere"):
            # its sound is a clip of its own on a sound track (R5-05): the controls are over there
            self._section(box, "Sound")
            snd = p.sound_partner(self.cid)
            lab = Gtk.Label(xalign=0, label="This clip's sound is its own clip on the %s track, at the "
                            "same time and grouped with the picture.%s" % (
                                model.TRACK_NAMES[p.find(snd["id"])[0]] if snd else "Audio",
                                "" if snd else " It isn't there any more."))
            lab.set_line_wrap(True)
            lab.set_max_width_chars(34)
            lab.get_style_context().add_class("dim-label" if snd else "reel-warning")
            box.pack_start(lab, False, False, 0)
        if has_sound:
            self._section(box, "Sound")
            self._row(box, "Volume", self._scale("volume", 0, 200, 5, c.get("volume", 1.0) * 100,
                                                 lambda v: "%d%%" % v,
                                                 lambda v: self._set("Volume", volume=round(v) / 100.0)))
            mute = Gtk.CheckButton(label="Mute")
            mute.set_active(c.get("muted", False))
            mute.connect("toggled", lambda b: self._quiet or self._set("Mute", muted=b.get_active()))
            self.controls["muted"] = mute
            box.pack_start(mute, False, False, 0)
            if track == "music":
                bed = Gtk.CheckButton(label="Music bed: dips under speech and voice-over")
                bed.set_active(c.get("music_bed", False))
                bed.connect("toggled", lambda b: self._quiet or self._set("Music Bed", music_bed=b.get_active()))
                self.controls["music_bed"] = bed
                box.pack_start(bed, False, False, 0)
            kf = c.get("keyframes") or []
            if kf:
                self._section(box, "Volume points")
                for i, (t, v) in enumerate(kf):
                    self._row(box, model.fmt_time(t, p.fps), self._scale(
                        "kf%d" % i, 0, 200, 5, v * 100, lambda v: "%d%%" % v,
                        lambda v, i=i: self._set_kf(i, v / 100.0)))
        # ---- fades
        self._section(box, "Fades")
        self._row(box, "Fade in (s)", self._spin("fade_in", 0, 30, 0.25, c.get("fade_in", 0),
                                                 lambda v: self._set("Fade In", fade_in=v), 2))
        self._row(box, "Fade out (s)", self._spin("fade_out", 0, 30, 0.25, c.get("fade_out", 0),
                                                  lambda v: self._set("Fade Out", fade_out=v), 2))
        # ---- picture (R3-03)
        if track in ("video", "titles") and c["kind"] == "media" and m is not None:
            col = c.get("color") or {}
            self._section(box, "Colour")
            self._row(box, "Brightness", self._scale("brightness", -1, 1, 0.05, col.get("brightness", 0.0),
                                                     lambda v: "%+.0f" % (v * 100),
                                                     lambda v: self._set("Brightness", color={"brightness": v})))
            self._row(box, "Contrast", self._scale("contrast", 0, 2, 0.05, col.get("contrast", 1.0),
                                                   lambda v: "%.0f%%" % (v * 100),
                                                   lambda v: self._set("Contrast", color={"contrast": v})))
            self._row(box, "Saturation", self._scale("saturation", 0, 2, 0.05, col.get("saturation", 1.0),
                                                     lambda v: "%.0f%%" % (v * 100),
                                                     lambda v: self._set("Saturation", color={"saturation": v})))
            self._section(box, "Picture")
            self._row(box, "Zoom", self._scale("zoom", 100, 300, 5, c.get("zoom", 1.0) * 100, lambda v: "%d%%" % v,
                                               lambda v: self._set("Zoom", zoom=v / 100.0)))
            pz = [i for i, (_l, k) in enumerate(PANZOOM) if k == c.get("panzoom")]
            self._row(box, "Pan and zoom", self._combo("panzoom", [l for l, _k in PANZOOM], pz[0] if pz else 0,
                                                       lambda i: self._set("Pan and Zoom", panzoom=PANZOOM[i][1])))
            # ---- chroma key (R4-02)
            from . import engine
            self._section(box, "Chroma key")
            on = Gtk.CheckButton(label="Key out a background colour")
            on.set_active(c.get("chroma", False))
            on.connect("toggled", lambda b: self._quiet or self._set("Chroma Key", chroma=b.get_active()))
            self.controls["chroma"] = on
            box.pack_start(on, False, False, 0)
            names = [n for n, _k in engine.CHROMA_COLORS]
            keys = [k for _n, k in engine.CHROMA_COLORS]
            cur = keys.index(c.get("chroma_color", "green")) if c.get("chroma_color", "green") in keys else 0
            self._row(box, "Colour", self._combo("chroma_color", names, cur,
                                                 lambda i: self._set("Chroma Colour", chroma_color=keys[i])))
            self._row(box, "Tolerance", self._scale("chroma_tolerance", 1, 90, 1, c.get("chroma_tolerance", 20.0),
                                                    lambda v: "%.0f°" % v,
                                                    lambda v: self._set("Chroma Tolerance", chroma_tolerance=v)))
            self._row(box, "Softness", self._scale("chroma_softness", 0, 64, 1, c.get("chroma_softness", 2.0),
                                                   lambda v: "%.0f" % v,
                                                   lambda v: self._set("Chroma Softness", chroma_softness=v)))
            self._row(box, "Keep edges", self._scale("chroma_edges", 0, 128, 1, c.get("chroma_edges", 100),
                                                     lambda v: "%.0f" % v,
                                                     lambda v: self._set("Chroma Edges", chroma_edges=int(v))))
            cr = c.get("crop") or {}
            for k, lab in (("l", "Crop left %"), ("r", "Crop right %"), ("t", "Crop top %"), ("b", "Crop bottom %")):
                self._row(box, lab, self._spin("crop_" + k, 0, 45, 1, cr.get(k, 0) * 100,
                                               lambda v, k=k: self._set("Crop", crop={k: v / 100.0}), 0))
            # ---- steadying and straightening (R4-07)
            if not m.get("is_image"):
                self._section(box, "Steady and straighten")
                st = Gtk.CheckButton(label="Take the shake out")
                st.set_active(c.get("steady", False))
                st.connect("toggled", lambda b: self._quiet or self._set("Steady", steady=b.get_active()))
                self.controls["steady"] = st
                box.pack_start(st, False, False, 0)
                self._row(box, "How much", self._scale("steady_amount", 1, 10, 1, c.get("steady_amount", 5),
                                                       lambda v: "%.0f" % v,
                                                       lambda v: self._set("Steady Amount", steady_amount=int(v))))
                self._row(box, "Straighten", self._scale("lens", -100, 100, 5, c.get("lens", 0.0) * 100,
                                                         lambda v: "%+.0f" % v,
                                                         lambda v: self._set("Straighten", lens=round(v) / 100.0)))
                ap = Gtk.Button(label="Render the corrected copy")
                ap.connect("clicked", lambda _b: self.win.run("steady-apply"))
                self.controls["steady_apply"] = ap
                box.pack_start(ap, False, False, 0)
                hint = Gtk.Label(xalign=0)
                hint.get_style_context().add_class("reel-hint")
                hint.set_line_wrap(True)
                hint.set_max_width_chars(30)
                hint.set_text("Steadying has to watch the whole clip and straightening bends every "
                              "pixel, so Reel renders a corrected copy of the file once. The preview "
                              "and any export then use that copy. Change a setting and render again.")
                self.controls["steady_hint"] = hint
                box.pack_start(hint, False, False, 0)
                ready = Gtk.Label(xalign=0)
                ready.get_style_context().add_class("reel-hint")
                self.controls["steady_ready"] = ready
                box.pack_start(ready, False, False, 0)
        # ---- transition into the clip
        if track in ("video", "titles") and p.neighbours(c["id"])[0] is not None:
            self._section(box, "Transition from the clip before")
            keys = [None] + [k for k, _n in TRANSITIONS]
            names = ["None"] + [n for _k, n in TRANSITIONS]
            tr = c.get("transition")
            cur = keys.index(tr["type"]) if tr and tr["type"] in keys else 0
            self._row(box, "Transition", self._combo("transition", names, cur,
                                                     lambda i: self.win.run("transition:%s" % (keys[i] or "none"))))
            self._row(box, "Duration (s)", self._spin("transition_duration", 0.1, 5, 0.25,
                                                      tr["duration"] if tr else 1.0,
                                                      lambda v: self.win.run("transition-duration:%g" % v), 2))
        self._update_values(c)

    def _set_kf(self, i, v):
        c = self.win.project.clip(self.cid)
        kf = [list(x) for x in c.get("keyframes", [])]
        if i < len(kf):
            kf[i][1] = v
            self._set("Volume Points", keyframes=kf)

    def _update_values(self, c):
        """The clip changed elsewhere (ribbon, timeline): show its values without rebuilding."""
        self._quiet = True
        try:
            t = self.controls.get("times")
            if t is not None:
                fps = self.win.project.fps
                t.set_text("Starts %s · %s long" % (model.fmt_time(c["start"], fps), model.fmt_time(c["duration"], fps)))
            for key in ("fade_in", "fade_out"):
                w = self.controls.get(key)
                if w is not None and abs(w.get_value() - c.get(key, 0)) > 1e-6:
                    w.set_value(c.get(key, 0))
            w = self.controls.get("volume")
            if w is not None and abs(w.get_value() - c.get("volume", 1.0) * 100) > 0.5:
                w.set_value(c.get("volume", 1.0) * 100)
            w = self.controls.get("muted")
            if w is not None:
                w.set_active(c.get("muted", False))
            w = self.controls.get("music_bed")
            if w is not None:
                w.set_active(c.get("music_bed", False))
            w = self.controls.get("zoom")
            if w is not None:
                w.set_value(c.get("zoom", 1.0) * 100)
            col = c.get("color") or {}
            for k, d in (("brightness", 0.0), ("contrast", 1.0), ("saturation", 1.0)):
                w = self.controls.get(k)
                if w is not None and abs(w.get_value() - col.get(k, d)) > 1e-6:
                    w.set_value(col.get(k, d))
            w = self.controls.get("chroma")
            if w is not None:
                w.set_active(c.get("chroma", False))
            for k, d in (("chroma_tolerance", 20.0), ("chroma_softness", 2.0), ("chroma_edges", 100)):
                w = self.controls.get(k)
                if w is not None and abs(w.get_value() - float(c.get(k, d))) > 1e-6:
                    w.set_value(float(c.get(k, d)))
            w = self.controls.get("steady")
            if w is not None:
                w.set_active(c.get("steady", False))
            w = self.controls.get("steady_amount")
            if w is not None and abs(w.get_value() - float(c.get("steady_amount", 5))) > 1e-6:
                w.set_value(float(c.get("steady_amount", 5)))
            w = self.controls.get("lens")
            if w is not None and abs(w.get_value() - c.get("lens", 0.0) * 100) > 0.5:
                w.set_value(c.get("lens", 0.0) * 100)
            w = self.controls.get("steady_ready")
            if w is not None:
                from . import engine
                want = engine.fix_settings(c)
                if want is None:
                    w.set_text("")
                elif engine.fixed_copy(c["media"], c) is not None:
                    w.set_text("The corrected copy is ready.")
                elif not engine.have_ffmpeg():
                    w.set_text("ffmpeg isn\u2019t installed, so this clip can\u2019t be corrected.")
                else:
                    w.set_text("Not rendered yet: this clip still plays as it was filmed.")
        finally:
            self._quiet = False
