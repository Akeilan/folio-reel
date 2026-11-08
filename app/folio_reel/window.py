"""The Folio Reel window: title bar with Quick Access and search, the ribbon, the media bin, the
preview, Clip Settings, the timeline and the status bar, and every command they run."""
import copy
import os

from gi.repository import Gdk, GLib, Gtk, Pango

from . import APP_NAME, engine, icons, model
from .backstage import Backstage
from .mediabin import MediaBin
from .props import ClipSettings
from .ribbon import Ribbon
from .timeline import Timeline

MEDIA_TYPES = ["video/*", "audio/*", "image/*"]
ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:3": (1440, 1080)}
SHUTTLE = [1, 2, 4, 8]
SCRUB_MS = 70        # the shortest gap between pictures while the playhead is being dragged (R5-01)
PROXY_HINT_WIDTH = 1280      # wider than this and small copies are worth mentioning (R5-03)


class ReelWindow(Gtk.ApplicationWindow):
    def __init__(self, app, path=None):
        Gtk.ApplicationWindow.__init__(self, application=app)
        self.app = app
        self.path = None
        self.untitled = app.next_untitled()
        self.project = model.Project()
        self.project.listen(self._changed)
        self.playhead = 0.0
        self.playing = False
        self.shuttle = 0
        self._shuttle_timer = None
        self._tick_id = None
        self._refresh_id = None
        self._seek_target = None
        self._seek_id = None
        self.picture_dialog = None
        self._said_proxies = False
        self._own_change = False
        self._alt_alone = False
        self.exports = []
        self.export_queue = []        # exports waiting their turn (R4-08)
        self.recorder = None
        self.full = None
        geo = app.settings.get("window", {})
        self.set_default_size(geo.get("w", 1360), geo.get("h", 860))
        if geo.get("max", True):
            self.maximize()
        self.set_icon_name("folio-reel")

        # ---- title bar (navy, R3-10)
        self.header = Gtk.HeaderBar()
        self.header.set_show_close_button(True)
        self.header.get_style_context().add_class("folio-titlebar")
        self.title_label = Gtk.Label(label=APP_NAME)
        self.title_label.get_style_context().add_class("title")
        self.header.set_custom_title(self.title_label)
        self.qat = Gtk.Box(spacing=0)
        self.build_qat()
        self.header.pack_start(self.qat)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search (Alt+Q)")
        self.search.get_style_context().add_class("folio-search")
        self.search.set_width_chars(28)
        self.search.connect("activate", self.on_search)
        self.header.pack_end(self.search)
        self.set_titlebar(self.header)

        # ---- layout
        self.overlay = Gtk.Overlay()
        self.add(self.overlay)
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.overlay.add(self.outer)
        self.ribbon = Ribbon(self.run, self.focus_document)
        self.ribbon.connect("file-clicked", lambda *_: self.show_backstage())
        self.outer.pack_start(self.ribbon, False, False, 0)
        self.timeline = Timeline(self)
        self.mediabin = MediaBin(self)
        self.clipset = ClipSettings(self)
        self.preview = None
        self.preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.preview_frame = Gtk.AspectFrame(ratio=16 / 9.0, obey_child=False)
        self.preview_frame.set_shadow_type(Gtk.ShadowType.NONE)
        self.preview_frame.get_style_context().add_class("reel-preview")
        pv_bg = Gtk.EventBox()
        pv_bg.get_style_context().add_class("reel-preview")
        pv_bg.add(self.preview_frame)
        pv_bg.connect("button-press-event", lambda w, e: (self.run("full-screen") if e.type == Gdk.EventType._2BUTTON_PRESS else None, False)[1])
        self.preview_bg = pv_bg
        self.preview_box.pack_start(pv_bg, True, True, 0)
        self.preview_box.pack_start(self._transport(), False, False, 0)
        top = Gtk.Paned()
        top.pack1(self.mediabin, False, False)
        mid = Gtk.Paned()
        mid.pack1(self.preview_box, True, False)
        mid.pack2(self.clipset, False, False)
        top.pack2(mid, True, False)
        self.vpaned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.vpaned.pack1(top, True, False)
        self.vpaned.pack2(self.timeline, False, False)
        self.outer.pack_start(self.vpaned, True, True, 0)
        self.outer.pack_start(self._status_bar(), False, False, 0)

        from .ribbon_defs import build_ribbon
        build_ribbon(self)
        self.backstage = Backstage(self)
        self.overlay.add_overlay(self.backstage)
        from .keytips import KeyTips
        self.keytips = KeyTips(self)
        self.connect("key-press-event", self.on_key)
        self.connect("key-release-event", self.on_key_release)
        self.connect("delete-event", self.on_delete)
        self.connect("configure-event", self._remember_geometry)
        self.show_all()
        self.backstage.hide()
        self.export_box.hide()
        self._new_preview()
        if path:
            self.open_file(path)
        self.update_title()
        self.mediabin.refresh()
        GLib.idle_add(lambda: (self.vpaned.set_position(max(250, self.vpaned.get_allocated_height() - 260)), False)[1])
        GLib.idle_add(self.focus_document)

    # ------------------------------------------------------------ pieces
    def _transport(self):
        bar = Gtk.Box(spacing=2)
        bar.get_style_context().add_class("reel-transport")
        self.transport = {}
        for key, icon, tip in (("go-start", "reel-start", "Go to Start (Home)"),
                               ("frame-back", "reel-prev-frame", "Previous Frame (Left)"),
                               ("play", "reel-play", "Play / Pause (Space)"),
                               ("frame-forward", "reel-next-frame", "Next Frame (Right)"),
                               ("go-end", "reel-end", "Go to End (End)")):
            b = Gtk.Button()
            b.add(icons.image(icon, 16))
            b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda _b, k=key: self.run(k))
            bar.pack_start(b, False, False, 0)
            self.transport[key] = b
        self.timecode = Gtk.Label(label="00:00:00:00")
        self.timecode.get_style_context().add_class("reel-timecode")
        # click the timecode to jump somewhere by typing the time (R5-01)
        tcbox = Gtk.EventBox()
        tcbox.add(self.timecode)
        tcbox.set_tooltip_text("Go to Time (Ctrl+J)")
        tcbox.connect("button-press-event", lambda w, e: (self.run("go-to-time"), False)[1])
        tcbox.connect("realize", lambda w: w.get_window().set_cursor(
            Gdk.Cursor.new_from_name(w.get_display(), "pointer")))
        self.timecode_box = tcbox
        bar.pack_start(tcbox, False, False, 6)
        # the output level while it plays (R4-01)
        self.levels = [0.0, 0.0]
        self.level_hold = [0.0, 0.0]
        self.meter = Gtk.DrawingArea()
        self.meter.set_size_request(74, 18)
        self.meter.set_valign(Gtk.Align.CENTER)
        self.meter.set_tooltip_text("Output level (left and right)")
        self.meter.connect("draw", self._draw_meter)
        bar.pack_end(self.meter, False, False, 6)
        fs = Gtk.Button()
        fs.add(icons.image("fullscreen", 16))
        fs.set_tooltip_text("Full-Screen Preview (F11)")
        fs.set_focus_on_click(False)
        fs.connect("clicked", lambda *_: self.run("full-screen"))
        bar.pack_end(fs, False, False, 0)
        return bar

    def _draw_meter(self, area, cr):
        """Two bars, left and right, green up to about -18 dB, amber, then red at the top."""
        from . import appearance
        dark = appearance.is_dark()
        w, h = area.get_allocated_width(), area.get_allocated_height()
        cr.set_source_rgb(*((0.16, 0.16, 0.16) if dark else (0.80, 0.80, 0.80)))
        cr.rectangle(0, 0, w, h)
        cr.fill()
        bh = (h - 3) / 2.0
        # green to about -13 dB, amber to -5, red at the top (each band drawn on its own)
        bands = ((0.78, (0.25, 0.70, 0.35)), (0.92, (0.90, 0.70, 0.20)), (1.0, (0.85, 0.25, 0.20)))
        for i in range(2):
            y = 1 + i * (bh + 1)
            v = self.levels[i] if i < len(self.levels) else 0.0
            at = 0.0
            for upto, rgb in bands:
                part = min(v, upto) - at
                if part > 0:
                    cr.set_source_rgb(*rgb)
                    cr.rectangle(w * at, y, w * part, bh)
                    cr.fill()
                at = upto
                if v <= upto:
                    break
            hold = self.level_hold[i] if i < len(self.level_hold) else 0.0
            if hold > 0:
                cr.set_source_rgb(0.95, 0.95, 0.95)
                cr.rectangle(min(w - 1, int(w * hold)), y, 1, bh)
                cr.fill()

    def show_level(self, pairs):
        """A level reading from the preview: the loudest sample since the last one, per channel."""
        from . import engine
        vals = [engine.db_to_bar(p) for p, _r in pairs[:2]] or [0.0]
        while len(vals) < 2:
            vals.append(vals[0])
        self.levels = vals
        self.level_hold = [max(h * 0.94, v) for h, v in zip(self.level_hold, vals)]
        self.meter.queue_draw()

    def clear_level(self):
        self.levels = [0.0, 0.0]
        self.level_hold = [0.0, 0.0]
        self.meter.queue_draw()

    def _status_bar(self):
        bar = Gtk.Box(spacing=10)
        bar.get_style_context().add_class("folio-status")
        self.notice_label = Gtk.Label(xalign=0)
        self.notice_label.set_ellipsize(Pango.EllipsizeMode.END)
        bar.pack_start(self.notice_label, True, True, 0)
        self.export_box = Gtk.Box(spacing=6)
        self.export_label = Gtk.Label(label="Exporting")
        self.export_bar = Gtk.ProgressBar()
        self.export_bar.set_size_request(160, -1)
        self.export_bar.set_valign(Gtk.Align.CENTER)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.cancel_exports())
        self.export_cancel = cancel
        for w in (self.export_label, self.export_bar, cancel):
            self.export_box.pack_start(w, False, False, 0)
        bar.pack_start(self.export_box, False, False, 0)
        self.info_label = Gtk.Label()
        bar.pack_end(self.info_label, False, False, 0)
        self.status = bar
        return bar

    def notice(self, text, seconds=8):
        self.notice_label.set_text(text)
        if getattr(self, "_notice_id", None):
            GLib.source_remove(self._notice_id)

        def clear():
            self._notice_id = None
            self.notice_label.set_text("")
            return False
        self._notice_id = GLib.timeout_add_seconds(seconds, clear)

    def message(self, text, secondary=None, kind=Gtk.MessageType.INFO):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=kind, buttons=Gtk.ButtonsType.OK, text=text)
        d.set_title(APP_NAME)
        if secondary:
            d.format_secondary_text(secondary)
        d.run()
        d.destroy()

    # ------------------------------------------------------------ QAT
    QAT_ALL = [("new", "newdoc", "New (Ctrl+N)", "New"), ("open", "open", "Open (Ctrl+O)", "Open"),
               ("save", "save", "Save (Ctrl+S)", "Save"), ("undo", "undo", "Undo (Ctrl+Z)", "Undo"),
               ("redo", "redo", "Redo (Ctrl+Y)", "Redo"), ("export", "reel-export", "Export Video (Ctrl+E)", "Export Video")]
    QAT_DEFAULT = ["save", "undo", "redo"]

    def build_qat(self):
        for c in self.qat.get_children():
            self.qat.remove(c)
        on = self.app.settings.get("qat", self.QAT_DEFAULT)
        for key, icon, tip, _n in self.QAT_ALL:
            if key not in on:
                continue
            b = Gtk.Button()
            b.add(icons.white_image(icon, 16))
            b.set_tooltip_text(tip)
            b.set_focus_on_click(False)
            b.connect("clicked", lambda _b, k=key: self.run(k))
            self.qat.pack_start(b, False, False, 0)
        mb = Gtk.MenuButton()
        mb.set_relief(Gtk.ReliefStyle.NONE)
        mb.set_focus_on_click(False)
        mb.set_tooltip_text("Customize Quick Access Toolbar")
        mb.add(Gtk.Label(label="▾"))
        menu = Gtk.Menu()
        head = Gtk.MenuItem(label="Customize Quick Access Toolbar")
        head.set_sensitive(False)
        menu.append(head)
        for k, _i, _t, name in self.QAT_ALL:
            mi = Gtk.CheckMenuItem(label=name)
            mi.set_active(k in on)
            mi.connect("toggled", lambda m, k=k: GLib.idle_add(lambda: (self.set_qat(k, m.get_active()), False)[1]))
            menu.append(mi)
        menu.show_all()
        mb.set_popup(menu)
        self.qat.pack_start(mb, False, False, 0)
        self.qat.show_all()

    def set_qat(self, key, on):
        cur = [k for k in self.app.settings.get("qat", self.QAT_DEFAULT) if k != key]
        if on:
            cur.append(key)
        self.app.settings["qat"] = [k for k, *_ in self.QAT_ALL if k in cur]
        try:
            self.app.save_settings()
        except OSError:
            pass
        for w in self.app.windows:
            w.build_qat()

    def restyle(self):
        self.build_qat()
        self.timeline.area.queue_draw()

    # ------------------------------------------------------------ backstage, focus, title
    def show_backstage(self, page="home"):
        self.pause()
        self.backstage.open(page)

    def backstage_open(self):
        return self.backstage.get_visible()

    def focus_document(self, *_):
        self.timeline.area.grab_focus()
        return False

    def doc_name(self):
        return os.path.basename(self.path) if self.path else self.untitled

    def update_title(self):
        name = self.doc_name()
        self.title_label.set_text("%s - %s" % (name, APP_NAME))
        self.set_title("%s - %s" % (name, APP_NAME))
        p = self.project
        self.info_label.set_text("%d × %d · %g fps · %s" % (p.width, p.height, p.fps, model.fmt_time(p.duration())))

    def is_blank(self):
        return self.path is None and not self.project.dirty and not self.project.media and not self.project.undo_stack

    # ------------------------------------------------------------ the preview (R3-02)
    def _new_preview(self):
        if self.preview is not None:
            self._detach_preview_widget()
            self.preview.close()
        self.preview = engine.Preview(self.project, on_event=self._preview_event)
        q = self.app.settings.get("preview_quality", 1)
        if q in (2, 4):
            self.preview.set_quality(q)
        if self.app.settings.get("use_proxies", False):
            self.preview.set_proxies(True)
        w = self.preview.widget
        if w is None:
            w = Gtk.Label(label="The preview needs GStreamer's GTK sink (gstreamer1.0-gtk3).")
        self.preview_widget = w
        self.preview_frame.add(w)
        w.show()
        self._fit_aspect()

    def _detach_preview_widget(self):
        w = getattr(self, "preview_widget", None)
        if w is not None and w.get_parent() is not None:
            w.get_parent().remove(w)

    def _fit_aspect(self):
        self.preview_frame.set(0.5, 0.5, self.project.width / float(self.project.height), False)

    def _preview_event(self, ev, val=None):
        if ev == "eos":
            self._stop_tick()
            self.playing = False
            self.shuttle = 0
            self.playhead = self.project.duration()
            self._show_play_state()
            self._after_seek()
        elif ev == "error":
            self.notice("Preview: %s" % val)
        elif ev == "level":
            if self.playing:
                self.show_level(val or [])
            else:
                self.clear_level()

    def seek(self, t, accurate=True):
        """Move the playhead. The bar, the timecode and the timeline keep up with every move; the
        picture is fetched a few times a second while the playhead is being dragged, which is what
        makes dragging it along a long film stay under the pointer instead of falling behind
        (R5-01). An accurate seek, the kind a click or a jump asks for, is served at once."""
        t = max(0.0, min(float(t), max(0.0, self.project.duration())))
        self.playhead = t
        self._after_seek()
        self._seek_target = (t, accurate)
        if accurate and self._seek_id is not None:
            GLib.source_remove(self._seek_id)
            self._seek_id = None
        if self._seek_id is None:
            self._seek_id = (GLib.idle_add(self._do_seek) if accurate
                             else GLib.timeout_add(SCRUB_MS, self._do_seek))

    def _do_seek(self):
        self._seek_id = None
        target, self._seek_target = self._seek_target, None
        if target is not None and self.preview is not None:
            self.preview.seek(*target)
        return False

    def _after_seek(self):
        fps = self.project.fps
        self.timecode.set_text("%s / %s" % (model.fmt_time(self.playhead, fps), model.fmt_time(self.project.duration(), fps)))
        self.timeline.show_time(self.playhead)
        self.timeline.area.queue_draw()

    def _show_play_state(self):
        b = self.transport["play"]
        b.remove(b.get_child())
        b.add(icons.image("reel-pause" if self.playing else "reel-play", 16))
        b.show_all()

    def play(self, rate=1.0):
        if self.project.duration() <= 0:
            self.notice("Add some media to the timeline first.")
            return
        self._stop_shuttle_timer()
        if self._seek_target is not None:
            if self._seek_id is not None:
                GLib.source_remove(self._seek_id)
                self._seek_id = None
            self._do_seek()
        if self.playhead >= self.project.duration() - 0.05:
            self.preview.seek(0.0)
            self.playhead = 0.0
        self.preview.play(rate)
        if self.preview.state != "playing":     # it reached the end while starting
            self._show_play_state()
            return
        self.playing = True
        self._show_play_state()
        if self._tick_id is None:
            self._tick_id = GLib.timeout_add(40, self._tick)

    def pause(self):
        self._stop_shuttle_timer()
        self.shuttle = 0
        if self.preview is not None and self.playing:
            self.preview.pause()
            self.playhead = self.preview.position()
        self.playing = False
        self._stop_tick()
        self._show_play_state()
        self.clear_level()
        self._after_seek()

    def _stop_tick(self):
        if self._tick_id is not None:
            GLib.source_remove(self._tick_id)
            self._tick_id = None

    def _tick(self):
        if not self.playing:
            self._tick_id = None
            return False
        self.playhead = self.preview.position()
        self._after_seek()
        return True

    def toggle_play(self):
        self.pause() if (self.playing or self.shuttle) else self.play()

    def shuttle_key(self, key):
        """J, K, L: back, stop, forward; pressing J or L again goes faster (R3-02)."""
        if key == "k":
            self.pause()
            return
        if key == "l":
            s = 1 if self.shuttle <= 0 else min(8, self.shuttle * 2)
            self.play(float(s))
            if self.playing:                # play() runs the main loop: it can stop at the end
                self.shuttle = s
            return
        # J: play backwards by stepping the playhead back (smooth reverse needs every frame decoded)
        s = -1 if self.shuttle >= 0 else max(-8, self.shuttle * 2)
        if self.playing:
            self.pause()
        self.shuttle = s
        self._stop_shuttle_timer()
        self._shuttle_timer = GLib.timeout_add(100, self._shuttle_back)
        self._show_play_state()

    def _shuttle_back(self):
        if self.shuttle >= 0:
            self._shuttle_timer = None
            return False
        t = self.playhead + self.shuttle * 0.1
        if t <= 0:
            self.seek(0.0, accurate=False)
            self.shuttle = 0
            self._shuttle_timer = None
            return False
        self.seek(t, accurate=False)
        return True

    def _stop_shuttle_timer(self):
        if self._shuttle_timer is not None:
            GLib.source_remove(self._shuttle_timer)
            self._shuttle_timer = None

    def step(self, frames):
        self.pause()
        self.seek(self.playhead + frames / float(self.project.fps))

    def full_screen(self):
        if self.full is not None:
            self.full.leave()
            return
        self.full = FullPreview(self)

    # ------------------------------------------------------------ changes
    def _changed(self, what):
        if what in ("media", "all"):
            self.mediabin.refresh()
        if what != "media":
            self.timeline.update_range()
            self.timeline.area.queue_draw()
            if self._refresh_id is None:
                self._refresh_id = GLib.timeout_add(120, self._refresh_preview)
            # clips that no longer exist leave the selection
            self.timeline.selected = [i for i in self.timeline.selected if self.project.clip(i) is not None]
            if not self._own_change:
                self.clipset.refresh()
            else:
                c = self.project.clip(self.clipset.cid) if self.clipset.cid else None
                if c is not None:
                    self.clipset._update_values(c)
        if what in ("timeline", "all") and (self.project.width, self.project.height) != getattr(self, "_aspect", None):
            self._aspect = (self.project.width, self.project.height)
            self._fit_aspect()
        self.update_title()
        self._update_states()

    def _refresh_preview(self):
        self._refresh_id = None
        if self.preview is not None and self.preview.building:
            self._refresh_id = GLib.timeout_add(60, self._refresh_preview)
            return False
        if self.preview is not None:
            was = self.playing
            if was:
                self.pause()
            self.preview.refresh()
            self.preview.seek(min(self.playhead, self.project.duration()))
        return False

    def flush(self):
        """Bring the preview up to date now (tests, export)."""
        if self._refresh_id is not None:
            GLib.source_remove(self._refresh_id)
            self._refresh_preview()

    def edit(self, fn, own=False):
        """Run an edit on the project; an edit that can't be made says why in the status bar."""
        self._own_change = own
        try:
            return fn(self.project)
        except model.EditError as e:
            self.notice(str(e))
            return None
        finally:
            self._own_change = False

    def selection_changed(self):
        self.clipset.refresh()
        self._update_states()

    def _update_states(self):
        sel = self.timeline.selected_clips()
        self.ribbon.update("muted", "true" if sel and all(c.get("muted") for c in sel) else "false")
        self.ribbon.update("snapping", "true" if self.project.snapping else "false")

    # ------------------------------------------------------------ files
    def open_file(self, path, ask=False):
        if ask and not self.is_blank():
            self.app.open_path(path)
            return
        try:
            p = model.Project.load(path)
        except (OSError, ValueError, KeyError) as e:
            self.message("“%s” couldn't be opened." % os.path.basename(path), str(e), Gtk.MessageType.ERROR)
            return
        self.pause()
        self.project = p
        p.listen(self._changed)
        self.path = os.path.abspath(path)
        self.app.add_recent(self.path)
        self.timeline.selected = []
        self.timeline.thumbs.clear()
        self.playhead = 0.0
        self._new_preview()
        self.mediabin.refresh()
        self.clipset.refresh()
        self.timeline.zoom_fit()
        self.update_title()
        self._after_seek()
        missing = p.missing_media()
        if missing:
            self.notice("%d media file%s couldn't be found: %s" % (len(missing), "" if len(missing) == 1 else "s",
                                                                   ", ".join(os.path.basename(m) for m in missing[:3])), 20)

    def new_project(self, aspect=None):
        if not self.is_blank():
            win = self.app.new_window()
            if aspect:
                win.run("aspect:" + aspect)
                win.project.undo_stack.clear()
                win.project.dirty = False
            return win
        if aspect:
            self.run("aspect:" + aspect)
            self.project.undo_stack.clear()
            self.project.dirty = False
        return self

    def save(self, path=None):
        path = path or self.path
        if path is None:
            return self.save_as()
        if not path.lower().endswith(".reel"):
            path += ".reel"
        try:
            self.project.save(path)
        except OSError as e:
            self.message("The project couldn't be saved.", str(e), Gtk.MessageType.ERROR)
            return False
        self.path = os.path.abspath(path)
        self.app.add_recent(self.path)
        self.update_title()
        self.notice("Saved.")
        return True

    def _chooser(self, title, action, name=None, filters=()):
        fc = Gtk.FileChooserNative(title=title, transient_for=self, action=action)
        if action == Gtk.FileChooserAction.SAVE:
            fc.set_do_overwrite_confirmation(True)
            if name:
                fc.set_current_name(name)
        for label, pats in filters:
            f = Gtk.FileFilter()
            f.set_name(label)
            for pat in pats:
                (f.add_mime_type if "/" in pat else f.add_pattern)(pat)
            fc.add_filter(f)
        return fc

    def save_as(self):
        fc = self._chooser("Save As", Gtk.FileChooserAction.SAVE, os.path.splitext(self.doc_name())[0] + ".reel",
                           [("Folio Reel projects", ["*.reel"])])
        ok = fc.run() == Gtk.ResponseType.ACCEPT
        path = fc.get_filename() if ok else None
        fc.destroy()
        return self.save(path) if path else False

    def open_dialog(self):
        fc = self._chooser("Open", Gtk.FileChooserAction.OPEN, filters=[("Folio Reel projects", ["*.reel"])])
        ok = fc.run() == Gtk.ResponseType.ACCEPT
        path = fc.get_filename() if ok else None
        fc.destroy()
        if path:
            self.app.open_path(path, from_window=self)

    def import_dialog(self):
        fc = self._chooser("Import Media", Gtk.FileChooserAction.OPEN,
                           filters=[("Video, sound and pictures", MEDIA_TYPES), ("All files", ["*"])])
        fc.set_select_multiple(True)
        ok = fc.run() == Gtk.ResponseType.ACCEPT
        uris = fc.get_uris() if ok else []
        fc.destroy()
        if uris:
            self.import_uris(uris)

    def import_uris(self, uris):
        """Put files in the media bin (R3-01). Returns their media entries."""
        out, bad = [], []
        for uri in uris:
            m = self.project.media_by_uri(uri)
            if m is None:
                path = model.uri_to_path(uri)
                try:
                    info = engine.probe(path)
                except Exception as e:      # noqa: BLE001
                    bad.append("%s (%s)" % (os.path.basename(path or uri), e))
                    continue
                m = self.edit(lambda p: p.add_media(info))
            if m is not None:
                out.append(m)
        if bad:
            self.notice("Couldn't import: " + "; ".join(bad), 15)
        elif out:
            self.notice("Imported %d file%s." % (len(out), "" if len(out) == 1 else "s"))
            self._mention_proxies(out)
        return out

    def _mention_proxies(self, media):
        """Big films play back heavily until there are small copies to preview from. Say so once a
        window, and only when there is nothing already made (R5-03)."""
        if self._said_proxies or self.app.settings.get("use_proxies", False):
            return
        big = [m for m in media if m.get("has_video") and not m.get("is_image")
               and (m.get("width") or 0) > PROXY_HINT_WIDTH
               and not os.path.exists(engine.proxy_path(m["uri"]))]
        if not big:
            return
        self._said_proxies = True
        self.notice("%s %dx%d. Make Small Copies, on the Insert tab, gives a smoother preview; an "
                    "export always uses the original." % (
                        "%s is" % big[0]["name"] if len(big) == 1 else "%d of those films are" % len(big),
                        big[0].get("width") or 0, big[0].get("height") or 0), 18)

    def add_media_to_timeline(self, uris, track=None, at=None):
        added = []
        for uri in uris:
            m = self.project.media_by_uri(uri)
            if m is None:
                continue
            tr = track if track in model.TRACKS else self.project.media_kind_track(m)
            if tr in ("audio", "music") and not m.get("has_audio"):
                tr = self.project.media_kind_track(m)
            if tr in ("video", "titles") and not (m.get("has_video") or m.get("is_image")):
                tr = "audio"
            c = self.edit(lambda p: p.add_clip(tr, m, at=self.playhead if at is None else at))
            if c is not None:
                added.append(c["id"])
                if tr in ("audio", "music") and (m.get("has_video") or m.get("is_image")):
                    # easy to aim a lane low: say so rather than quietly dropping the picture (R5-02)
                    self.notice("“%s” is on the %s track: its sound is in the film, its picture isn't."
                                % (m["name"], model.TRACK_NAMES[tr]), 12)
        if added:
            self.timeline.select(added)
        return added

    def add_uris(self, uris, track=None, at=None):
        """Files or bin media dropped on the timeline."""
        ms = self.import_uris(uris)
        return self.add_media_to_timeline([m["uri"] for m in ms], track=track, at=at)

    # ------------------------------------------------------------ export (R3-06)
    def export_as(self, fmt="mp4", preset="1080p"):
        missing = engine.missing_encoders(fmt)
        if missing:
            self.message("This computer can't make %s files yet." % engine.FORMATS.get(fmt, fmt),
                         "Missing: %s." % ", ".join(missing), Gtk.MessageType.ERROR)
            return None
        if self.project.duration() <= 0:
            self.message("There's nothing on the timeline to export.")
            return None
        if not self.confirm_picture():
            return None
        self.app.settings["export_format"], self.app.settings["export_preset"] = fmt, preset
        ext = ".webm" if fmt == "webm" else ".mp4"
        fc = self._chooser("Export Video", Gtk.FileChooserAction.SAVE, os.path.splitext(self.doc_name())[0] + ext,
                           [(engine.FORMATS[fmt], ["*" + ext])])
        ok = fc.run() == Gtk.ResponseType.ACCEPT
        path = fc.get_filename() if ok else None
        fc.destroy()
        if not path:
            return None
        if not path.lower().endswith(ext):
            path += ext
        return self.start_export(path, fmt, preset)

    def picture_warnings(self):
        """What a person should be told about this film's picture before it is rendered, in plain
        words. Empty when there is nothing to say (R5-02)."""
        total = self.project.duration()
        if total <= 0:
            return []
        dark = self.project.dark_spans()
        if not dark:
            return []
        said = []
        covered = sum(b - a for a, b in dark)
        if covered > total - 0.25:
            said.append("This film has no picture at all — it would come out black from end to end."
                        " Put a video clip or a picture on the Video track.")
        elif len(dark) == 1 and dark[0][1] > total - 0.25:
            said.append("The last %s of this film has no picture: it would come out black there."
                        % model.fmt_time(dark[0][1] - dark[0][0]))
        else:
            said.append("%s of this film has no picture and would come out black%s."
                        % (model.fmt_time(covered), ", starting at %s" % model.fmt_time(dark[0][0])
                           if dark[0][0] > 0.25 else ""))
        return said

    def confirm_picture(self):
        """Ask before rendering a film that would be black. True to carry on (R5-02)."""
        said = self.picture_warnings()
        if not said:
            return True
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                              text="Export this film anyway?")
        d.format_secondary_text(" ".join(said))
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Export Anyway", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        self.picture_dialog = d
        r = d.run()
        d.destroy()
        self.picture_dialog = None
        return r == Gtk.ResponseType.OK

    def start_export(self, path, fmt, preset):
        """Put an export in the queue. One runs at a time; the rest wait their turn (R4-08)."""
        self.export_queue.append((path, fmt, preset))
        if self.exports:
            self.notice("%s is waiting its turn: %d in the queue." % (os.path.basename(path), len(self.export_queue)))
            self._export_progress()
            return None
        return self._next_export()

    def _next_export(self):
        """Start the export at the head of the queue, if nothing is running."""
        if self.exports or not self.export_queue:
            return None
        path, fmt, preset = self.export_queue.pop(0)
        try:
            ex = engine.Exporter(self.project, path, fmt, preset, on_progress=lambda f: self._export_progress(),
                                 on_done=lambda p, err, e=None: None)
        except model.EditError as e:
            self.message(str(e))
            return self._next_export()
        ex.on_done = lambda p, err, ex=ex: self._export_done(ex, p, err)
        self.exports.append(ex)
        ex.start()
        self.export_box.show_all()
        self._export_progress()
        return ex

    def _export_progress(self):
        live = [e for e in self.exports if not e.done]
        if not live:
            return
        frac = sum(getattr(e, "fraction", 0.0) for e in live) / len(live)
        self.export_bar.set_fraction(frac)
        waiting = len(self.export_queue)
        said = "Exporting %s… %d%%" % (os.path.basename(live[0].path), int(frac * 100)) if len(live) == 1 else \
               "Exporting %d videos… %d%%" % (len(live), int(frac * 100))
        if waiting:
            said += "  (%d waiting)" % waiting
        self.export_label.set_text(said)

    def _export_done(self, ex, path, err):
        if ex in self.exports:
            self.exports.remove(ex)
        if err == "cancelled":
            self.notice("Export cancelled.")
        elif err:
            self.notice("Export failed: %s" % err, 20)
        else:
            left = len(self.export_queue)
            name = os.path.basename(path)
            read, dark = engine.look_at_film(path, getattr(ex, "duration", 0) / engine.SECOND)
            if read and dark == read:
                # the status bar, not a box in the way: a person who meant to render a black film
                # has already said so at the question before the render started
                self.notice("Exported %s — every frame of it is black." % name, 30)
            elif read and dark > read / 2:
                self.notice("Exported %s — most of it is black." % name, 30)
            else:
                self.notice("Exported %s.%s" % (name, " %d still to go." % left if left else ""), 20)
        if self.export_queue:
            self._next_export()
        elif not self.exports:
            self.export_box.hide()

    def cancel_exports(self):
        """Stop what is running and empty the queue (R4-08)."""
        waiting = len(self.export_queue)
        self.export_queue.clear()
        for e in list(self.exports):
            e.cancel()
        if waiting and not self.exports:
            self.export_box.hide()
        if waiting:
            self.notice("%d export(s) taken out of the queue." % waiting)

    # ------------------------------------------------------------ recording (R3-07)
    def record(self, kind):
        if self.recorder is not None:
            self.notice("A recording is already running.")
            return
        from . import record
        xid = device = None
        if kind == "window":
            if record.is_wayland():
                xid = None
            else:
                wins = [w for w in record.x11_windows() if w[1] and "Recording" not in w[1]]
                if not wins:
                    self.message("There are no windows to record.")
                    return
                xid = self._pick("Record Window", "Which window?", [(t, x) for x, t in wins])
                if xid is None:
                    return
        if kind == "camera":
            cams = record.cameras()
            if not cams:
                self.message("No camera was found.", "Plug in a webcam and try again.")
                return
            device = cams[0][1] if len(cams) == 1 else self._pick("Record Camera", "Which camera?", cams)
            if device is None and len(cams) > 1:
                return
        self.pause()
        self.recorder = record.Recorder(kind, self._record_state, xid=xid, device=device,
                                        sound=kind in ("camera", "voice") or self.app.settings.get("record_sound", False))
        self._record_at = self.playhead
        self.record_bar = RecordBar(self, self.recorder)
        self.recorder.start()
        return self.recorder

    def _pick(self, title, prompt, items):
        d = Gtk.Dialog(title=title, transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Record", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.pack_start(Gtk.Label(label=prompt, xalign=0), False, False, 0)
        combo = Gtk.ComboBoxText()
        for label, _v in items:
            combo.append_text(label)
        combo.set_active(0)
        box.pack_start(combo, False, False, 0)
        self.pick_dialog = d
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        i = combo.get_active()
        d.destroy()
        self.pick_dialog = None
        return items[i][1] if ok and i >= 0 else None

    def _record_state(self, state, info):
        if state == "recording":
            return
        bar = getattr(self, "record_bar", None)
        if bar is not None:
            bar.destroy()
            self.record_bar = None
        rec, self.recorder = self.recorder, None
        if state == "error":
            self.message("Recording", info, Gtk.MessageType.ERROR)
            return
        if state == "done" and info and os.path.exists(info):
            ms = self.import_uris([model.path_to_uri(info)])
            if ms:
                track = "audio" if rec.kind == "voice" else "video"
                self.add_media_to_timeline([ms[0]["uri"]], track=track, at=self._record_at)
                self.notice("Recorded %s." % os.path.basename(info), 12)

    # ------------------------------------------------------------ clipboard
    def copy_clips(self, cut=False):
        sel = self.timeline.selected_clips()
        if not sel:
            self.notice("Select clips to %s." % ("cut" if cut else "copy"))
            return
        base = min(c["start"] for c in sel)
        items = []
        for c in sel:
            track = self.project.find(c["id"])[0]
            m = self.project.media_by_uri(c["media"]) if c["kind"] == "media" else None
            items.append({"track": track, "clip": copy.deepcopy(c), "offset": c["start"] - base,
                          "media": copy.deepcopy(m) if m else None})
        self.app.clipboard = items
        if cut:
            self.edit(lambda p: p.delete([c["id"] for c in sel]))
            self.timeline.select([])

    def paste(self):
        items = getattr(self.app, "clipboard", None)
        if not items:
            self.notice("There's nothing to paste.")
            return
        new = self.edit(lambda p: p.paste(items, self.playhead))
        if new:
            self.timeline.select([c["id"] for c in new])

    # ------------------------------------------------------------ commands
    def sel_or_say(self, what="a clip", kinds=None):
        sel = self.timeline.selected_clips()
        if kinds:
            sel = [c for c in sel if c["kind"] in kinds]
        if not sel:
            self.notice("Select %s on the timeline first." % what)
        return sel

    def each(self, label, fn, what="a clip", kinds=None):
        sel = self.sel_or_say(what, kinds)
        if not sel:
            return
        for c in sel:
            self.edit(lambda p, c=c: fn(p, c))

    def run(self, cmd):
        if cmd is None:
            return None
        if self.keytips.active:
            self.keytips.leave()
        name, _, arg = cmd.partition(":")
        fn = getattr(self, "cmd_" + name.replace("-", "_"), None)
        if fn is None:
            self.notice("“%s” isn't available in Folio Reel." % name)
            return None
        return fn(arg) if arg else fn()

    # file
    def cmd_new(self, aspect=None):
        return self.new_project(aspect)

    def cmd_open(self):
        self.open_dialog()

    def cmd_save(self):
        return self.save()

    def cmd_save_as(self):
        return self.save_as()

    def cmd_close(self):
        if not self.on_delete(self, None):
            self.destroy()

    def cmd_export(self, arg=None):
        if arg:
            fmt, _, preset = arg.partition("/")
            return self.export_as(fmt or "mp4", preset or "1080p")
        self.show_backstage("export")

    def cmd_import_media(self):
        self.import_dialog()

    def cmd_add_to_timeline(self):
        uris = self.mediabin.selected_uris()
        if not uris:
            self.notice("Choose media in the bin first.")
            return
        self.add_media_to_timeline(uris)

    def cmd_remove_media(self):
        for uri in self.mediabin.selected_uris():
            self.edit(lambda p, u=uri: p.remove_media(u))

    # edit
    def cmd_undo(self):
        label = self.project.undo()
        self.notice("Undid %s." % label if label else "Nothing to undo.")

    def cmd_redo(self):
        label = self.project.redo()
        self.notice("Redid %s." % label if label else "Nothing to redo.")

    def cmd_cut(self):
        self.copy_clips(cut=True)

    def cmd_copy(self):
        self.copy_clips()

    def cmd_paste(self):
        self.paste()

    def cmd_delete(self, ripple=False):
        sel = self.sel_or_say("clips to delete")
        if sel:
            self.edit(lambda p: p.delete([c["id"] for c in sel], ripple=ripple))
            self.timeline.select([])

    def cmd_ripple_delete(self):
        self.cmd_delete(ripple=True)

    def cmd_select_all(self):
        self.timeline.select([c["id"] for c in self.project.all_clips()])

    def cmd_split(self):
        sel = self.timeline.selected_clips()
        ids = [c["id"] for c in sel] or None
        new = self.edit(lambda p: p.split_at(self.playhead, ids))
        if new:
            self.timeline.select([c["id"] for c in new])

    def cmd_trim_start(self):
        self.each("Trim", lambda p, c: p.trim_to_playhead(c["id"], self.playhead, "start"))

    def cmd_trim_end(self):
        self.each("Trim", lambda p, c: p.trim_to_playhead(c["id"], self.playhead, "end"))

    def cmd_clip_properties(self):
        if self.sel_or_say():
            self.clipset.refresh()
            self.clipset.sw.get_vadjustment().set_value(0)

    # playback
    def cmd_play(self):
        self.toggle_play()

    def cmd_frame_back(self):
        self.step(-1)

    def cmd_frame_forward(self):
        self.step(1)

    def cmd_go_start(self):
        self.pause()
        self.seek(0.0)

    def cmd_go_end(self):
        self.pause()
        self.seek(self.project.duration())

    def cmd_go_to_time(self, arg=None):
        """Jump the playhead to a time the person types: the way to reach the middle of a long film
        without dragging all the way there (R5-01). go-to-time:90 goes straight there."""
        if arg:
            t = model.parse_time(arg, self.project.fps)
            if t is not None:
                self.pause()
                self.seek(t)
                self.timeline.centre_on(t)
            return t
        d = Gtk.Dialog(title="Go to Time", transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("Go", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_spacing(8)
        for m in ("set_margin_start", "set_margin_end", "set_margin_top", "set_margin_bottom"):
            getattr(box, m)(12)
        box.pack_start(Gtk.Label(label="Time in the film (minutes:seconds, or hours:minutes:seconds):", xalign=0),
                       False, False, 0)
        entry = Gtk.Entry()
        entry.set_text(model.fmt_time(self.playhead, self.project.fps))
        entry.set_width_chars(16)
        entry.set_activates_default(True)
        box.pack_start(entry, False, False, 0)
        box.pack_start(Gtk.Label(label="This film runs to %s." % model.fmt_time(self.project.duration(), self.project.fps),
                                 xalign=0), False, False, 0)
        self.time_dialog = (d, entry)
        d.show_all()
        r = d.run()
        text = entry.get_text()
        d.destroy()
        self.time_dialog = None
        if r != Gtk.ResponseType.OK:
            return None
        t = model.parse_time(text, self.project.fps)
        if t is None:
            self.notice("“%s” isn't a time." % text.strip())
            return None
        self.pause()
        self.seek(t)
        self.timeline.centre_on(t)
        return t

    def cmd_full_screen(self):
        self.full_screen()

    # ---------------------------------------------------------------- groups of clips (R4-06)
    def cmd_group(self):
        ids = [c["id"] for c in self.timeline.selected_clips()]
        gid = self.edit(lambda p: p.group(ids))
        if gid:
            self.timeline.select(ids)
            self.notice("Grouped. The clips now move and trim as one; Ungroup breaks them up again.")

    def cmd_ungroup(self):
        ids = [c["id"] for c in self.timeline.selected_clips()]
        n = self.edit(lambda p: p.ungroup(ids))
        if n:
            self.timeline.select(ids)
            self.notice("%d clips are on their own again." % n)

    # ---------------------------------------------------------------- markers (R4-05)
    def marker_here(self):
        """The marker at the playhead, or the nearest one within half a second."""
        return self.project.marker_at(self.playhead, max(0.5, 6.0 / max(self.timeline.pps, 1.0)))

    def cmd_marker_add(self):
        mid = self.edit(lambda p: p.add_marker(self.playhead))
        if mid is not None:
            self.timeline.refresh()
            self.notice("Marker at %s. M adds one, Rename names it." % model.fmt_time(self.playhead))
        return mid

    def cmd_marker_next(self):
        m = self.project.next_marker(self.playhead)
        if m is None:
            self.notice("No marker after here.")
            return
        self.pause()
        self.seek(m["t"])
        if m["name"]:
            self.notice(m["name"])

    def cmd_marker_prev(self):
        m = self.project.prev_marker(self.playhead)
        if m is None:
            self.notice("No marker before here.")
            return
        self.pause()
        self.seek(m["t"])
        if m["name"]:
            self.notice(m["name"])

    def cmd_marker_delete(self):
        m = self.marker_here()
        if m is None:
            self.notice("No marker at the playhead.")
            return
        self.edit(lambda p: p.remove_markers([m["id"]]))
        self.timeline.refresh()

    def cmd_marker_clear(self):
        n = len(self.project.markers())
        if not n:
            self.notice("There are no markers.")
            return
        self.edit(lambda p: p.clear_markers())
        self.timeline.refresh()
        self.notice("%d markers deleted." % n)

    def cmd_marker_rename(self, arg=None):
        """Name a marker and pick its colour. Without a marker at the playhead, one is put there."""
        m = self.marker_here()
        if m is None:
            mid = self.cmd_marker_add()
            m = self.project.marker(mid) if mid is not None else None
        if m is None:
            return
        d = Gtk.Dialog(title="Marker", transient_for=self, modal=True)
        d.add_button("Delete", Gtk.ResponseType.REJECT)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.pack_start(Gtk.Label(label="Marker at %s" % model.fmt_time(m["t"], self.project.fps), xalign=0), False, False, 0)
        entry = Gtk.Entry()
        entry.set_text(m.get("name", ""))
        entry.set_width_chars(28)
        entry.set_activates_default(True)
        box.pack_start(entry, False, False, 0)
        colors = Gtk.ComboBoxText()
        keys = [k for k, _ in model.MARKER_COLORS]
        for _k, label in model.MARKER_COLORS:
            colors.append_text(label)
        colors.set_active(keys.index(m.get("color", "yellow")) if m.get("color", "yellow") in keys else 0)
        row = Gtk.Box(spacing=8)
        row.pack_start(Gtk.Label(label="Colour:", xalign=0), False, False, 0)
        row.pack_start(colors, False, False, 0)
        box.pack_start(row, False, False, 0)
        self.marker_dialog = (d, {"name": entry, "color": colors})
        d.show_all()
        r = d.run()
        name, color = entry.get_text().strip(), keys[max(0, colors.get_active())]
        d.destroy()
        self.marker_dialog = None
        if r == Gtk.ResponseType.REJECT:
            self.edit(lambda p: p.remove_markers([m["id"]]))
        elif r == Gtk.ResponseType.OK:
            self.edit(lambda p: p.set_marker(m["id"], name=name, color=color))
        self.timeline.refresh()

    # insert
    def cmd_record_screen(self):
        return self.record("screen")

    def cmd_record_window(self):
        return self.record("window")

    def cmd_record_camera(self):
        return self.record("camera")

    def cmd_record_voice(self):
        return self.record("voice")

    def _insert_text(self, kind):
        c = self.edit(lambda p: p.add_clip("titles", kind, at=self.playhead))
        if c is not None:
            self.timeline.select([c["id"]])
            GLib.idle_add(self._focus_title_text)
        return c

    def _focus_title_text(self):
        tv = self.clipset.controls.get("text")
        if tv is not None:
            tv.grab_focus()
            b = tv.get_buffer()
            b.select_range(b.get_start_iter(), b.get_end_iter())
        return False

    def cmd_insert_title(self):
        return self._insert_text("title")

    def cmd_insert_lower_third(self):
        return self._insert_text("lower-third")

    def cmd_insert_caption(self):
        return self._insert_text("caption")

    # preview quality (R4-04)
    def cmd_preview_quality(self, arg="1"):
        """Play the preview at full size, half or quarter. Exports are not affected."""
        try:
            d = int(str(arg).strip())
        except ValueError:
            d = 1
        d = d if d in (1, 2, 4) else 1
        self.app.settings["preview_quality"] = d
        self.app.save_settings()
        if self.preview is not None:
            self.preview.set_quality(d)
            self._after_seek()
        self.notice({1: "Preview at full size.", 2: "Preview at half size.",
                     4: "Preview at quarter size."}[d])
        return d

    # proxies (R4-04)
    def cmd_make_proxies(self, which=None):
        """Small copies of the big videos, for a smoother preview. The originals are what any
        export uses."""
        from . import engine
        want = [m for m in self.project.media if m.get("has_video") and not m.get("is_image")]
        chosen = self.mediabin.selected_uris()
        if chosen:
            want = [m for m in want if m["uri"] in chosen]
        if not want:
            self.notice("There are no videos in the bin to copy.")
            return 0
        todo = [m for m in want if not os.path.exists(engine.proxy_path(m["uri"]))]
        if not todo:
            self.notice("Every one of those already has a small copy.")
            self.cmd_use_proxies("on")
            return 0
        self.notice("Making %d small cop%s…" % (len(todo), "y" if len(todo) == 1 else "ies"))
        made = []
        for i, m in enumerate(todo):
            self.notice("Making small copies: %d of %d (%s)…" % (i + 1, len(todo), m["name"]))
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if engine.make_proxy(m):
                made.append(m["name"])
        if made:
            self.cmd_use_proxies("on")
            self.notice("%d small cop%s ready; the preview uses them." % (len(made), "y" if len(made) == 1 else "ies"))
        else:
            self.notice("The small copies couldn't be made.")
        return len(made)

    def cmd_use_proxies(self, arg="toggle"):
        """Whether the preview plays the small copies."""
        cur = bool(self.app.settings.get("use_proxies", False))
        on = not cur if arg == "toggle" else arg in ("on", "1", "true", "yes")
        self.app.settings["use_proxies"] = on
        self.app.save_settings()
        if self.preview is not None:
            self.preview.set_proxies(on)
            self._after_seek()
        self.notice("The preview plays the small copies." if on else "The preview plays the original files.")
        return on

    def cmd_remove_proxies(self):
        from . import engine
        n = engine.forget_proxies()
        self.app.settings["use_proxies"] = False
        self.app.save_settings()
        if self.preview is not None:
            self.preview.set_proxies(False)
        self.notice("%d small cop%s removed." % (n, "y" if n == 1 else "ies"))
        return n

    def _reshow(self):
        """The media behind a clip changed under us (a corrected copy appeared or went): build the
        preview again and redraw."""
        self._refresh_preview()
        self._after_seek()

    # steadying and straightening (R4-07)
    def _fixed(self, c):
        """Whether the clip, as it now stands, already has its corrected copy."""
        from . import engine
        cur = self.project.clip(c["id"]) or c
        return engine.fix_settings(cur) is None or engine.fixed_copy(cur["media"], cur) is not None

    def cmd_steady(self, arg="toggle"):
        """Take the shake out of the selected video clips."""
        sel = self.sel_or_say("a video clip", kinds=("media",))
        if not sel:
            return 0
        on = arg in ("on", "1", "true", "yes") if arg != "toggle" else not all(c.get("steady") for c in sel)
        for c in sel:
            self.edit(lambda p, c=c: p.set(c["id"], label="Steady", steady=on))
        if not on:
            self.notice("Steadying off; the clips play as they were filmed.")
            self._reshow()
            return 0
        if all(self._fixed(c) for c in sel):
            self.notice("Steadying on; the corrected copies are already made.")
            self._reshow()
        else:
            self.notice("Steadying on. Choose Render Correction to make the corrected copy.")
        return 1

    def cmd_lens(self, arg="0"):
        """Straighten the lens on the selected video clips: -100 to 100."""
        sel = self.sel_or_say("a video clip", kinds=("media",))
        if not sel:
            return 0
        try:
            v = max(-100.0, min(100.0, float(arg))) / 100.0
        except ValueError:
            self.notice("Straighten takes a number from -100 to 100.")
            return 0
        for c in sel:
            self.edit(lambda p, c=c: p.set(c["id"], label="Straighten", lens=v))
        if abs(v) < 1e-6:
            self.notice("Straightening off; the clips play as they were filmed.")
            self._reshow()
            return 0
        if all(self._fixed(c) for c in sel):
            self.notice("Straightening set; the corrected copies are already made.")
            self._reshow()
        else:
            self.notice("Straightening set. Choose Render Correction to make the corrected copy.")
        return 1

    def cmd_steady_apply(self, arg=None):
        """Render the corrected copies the selected clips ask for. Reel edits those copies from
        here on, in the preview and in any export."""
        from . import engine
        sel = self.sel_or_say("a video clip", kinds=("media",))
        if not sel:
            return 0
        want = []
        for c in sel:
            m = self.project.media_by_uri(c["media"])
            st = engine.fix_settings(c)
            if st is None or m is None or not m.get("has_video") or m.get("is_image"):
                continue
            if engine.fixed_copy(c["media"], c) is None:
                want.append((c, m, st))
        if not want:
            if any(engine.fix_settings(c) for c in sel):
                self.notice("Those are ready; the preview plays the corrected copies.")
                self._reshow()
            else:
                self.notice("Turn on Steady or move Straighten first.")
            return 0
        if not engine.have_ffmpeg():
            self.notice(engine.FFMPEG_MISSING, seconds=20)
            return 0
        done = 0
        for i, (c, m, st) in enumerate(want):
            self.notice("Correcting %d of %d (%s)\u2026" % (i + 1, len(want), c["name"]))
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)

            def progress(f, i=i, c=c):
                self.notice("Correcting %d of %d (%s): %d%%" % (i + 1, len(want), c["name"], int(f * 100)))
                while Gtk.events_pending():
                    Gtk.main_iteration_do(False)
            if engine.make_fix(m, st, on_progress=progress):
                done += 1
        if done:
            self.notice("%d clip%s corrected; the preview plays the corrected copies."
                        % (done, "" if done == 1 else "s"))
            self._reshow()
        else:
            self.notice("The corrected copies couldn\u2019t be made.")
        return done

    def cmd_remove_fixes(self):
        """Throw the corrected copies away; the clips play as they were filmed again."""
        from . import engine
        n = engine.forget_fixes()
        self._reshow()
        self.notice("%d corrected cop%s removed." % (n, "y" if n == 1 else "ies"))
        return n

    # subtitles (R4-03)
    def cmd_import_subtitles(self, path=None):
        """Read an .srt into caption clips on the Titles track."""
        from . import subtitles
        if path is None:
            fc = self._chooser("Import Subtitles", Gtk.FileChooserAction.OPEN,
                               filters=[("Subtitles (.srt)", ["*.srt"]), ("All files", ["*"])])
            ok = fc.run() == Gtk.ResponseType.ACCEPT
            path = fc.get_filename() if ok else None
            fc.destroy()
        if not path:
            return None
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                entries = subtitles.parse(f.read())
        except OSError as e:
            self.notice("Couldn't read %s: %s" % (os.path.basename(path), e))
            return None
        if not entries:
            self.notice("There are no subtitles in that file.")
            return None
        made = self.edit(lambda p: p.add_subtitles(entries))
        self.notice("%d subtitles added to the Titles track." % len(entries))
        return made

    def cmd_export_subtitles(self, path=None):
        """Write the caption clips out as an .srt."""
        from . import subtitles
        entries = subtitles.from_clips(self.project.track("titles"))
        if not entries:
            self.notice("There are no captions to write out. Insert > Caption makes one.")
            return None
        if path is None:
            fc = self._chooser("Export Subtitles", Gtk.FileChooserAction.SAVE,
                               os.path.splitext(self.doc_name())[0] + ".srt",
                               [("Subtitles (.srt)", ["*.srt"])])
            ok = fc.run() == Gtk.ResponseType.ACCEPT
            path = fc.get_filename() if ok else None
            fc.destroy()
        if not path:
            return None
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(subtitles.write(entries))
        except OSError as e:
            self.notice("Couldn't write %s: %s" % (os.path.basename(path), e))
            return None
        self.notice("%d subtitles written to %s." % (len(entries), os.path.basename(path)))
        return path

    # transitions (R3-03)
    def cmd_transition(self, kind):
        sel = self.sel_or_say("the clip to transition into")
        for c in sel:
            dur = (c.get("transition") or {}).get("duration") or self.app.settings.get("transition_duration", 1.0)
            self.edit(lambda p, c=c: p.set_transition(c["id"], None if kind == "none" else kind, dur))

    def cmd_transition_duration(self, secs):
        self.app.settings["transition_duration"] = float(secs)
        for c in self.timeline.selected_clips():
            tr = c.get("transition")
            if tr:
                self.edit(lambda p, c=c, tr=tr: p.set_transition(c["id"], tr["type"], float(secs)))

    # effects
    def cmd_color(self, what):
        def apply(p, c):
            col = dict(c.get("color") or {})
            if what == "bw":
                col["saturation"] = 0.0
            elif what == "brighter":
                col["brightness"] = min(1.0, col.get("brightness", 0.0) + 0.1)
            elif what == "darker":
                col["brightness"] = max(-1.0, col.get("brightness", 0.0) - 0.1)
            elif what == "contrast+":
                col["contrast"] = min(2.0, col.get("contrast", 1.0) + 0.15)
            elif what == "contrast-":
                col["contrast"] = max(0.0, col.get("contrast", 1.0) - 0.15)
            else:
                col = model.clip_defaults()["color"]
            return p.set(c["id"], label="Colour", color=col)
        self.each("Colour", apply, "a video clip or picture", kinds=("media",))

    def cmd_speed(self, x):
        self.each("Speed", lambda p, c: p.set_speed(c["id"], float(x)), "a video or sound clip", kinds=("media",))

    def cmd_panzoom(self, how):
        self.each("Pan and Zoom", lambda p, c: p.set(c["id"], label="Pan and Zoom", panzoom=None if how == "none" else how),
                  "a picture or video clip", kinds=("media",))

    def cmd_zoom(self, z):
        self.each("Zoom", lambda p, c: p.set(c["id"], label="Zoom", zoom=float(z)), "a picture or video clip", kinds=("media",))

    def cmd_picture_reset(self):
        d = model.clip_defaults()
        self.each("Reset Picture", lambda p, c: p.set(c["id"], label="Reset Picture", zoom=1.0, panzoom=None, crop=d["crop"]),
                  "a picture or video clip", kinds=("media",))

    def cmd_picture(self, what):
        if what == "reset":
            self.cmd_picture_reset()

    def cmd_crop(self):
        sel = self.sel_or_say("a picture or video clip", kinds=("media",))
        if not sel:
            return
        c = sel[0]
        cr = dict(c.get("crop") or {})
        d = Gtk.Dialog(title="Crop", transient_for=self, modal=True)
        d.add_button("Cancel", Gtk.ResponseType.CANCEL)
        d.add_button("OK", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        g = Gtk.Grid(column_spacing=10, row_spacing=6, margin=12)
        spins = {}
        for i, (k, lab) in enumerate((("l", "Left"), ("r", "Right"), ("t", "Top"), ("b", "Bottom"))):
            g.attach(Gtk.Label(label=lab + " (%):", xalign=0), 0, i, 1, 1)
            sp = Gtk.SpinButton.new_with_range(0, 45, 1)
            sp.set_value(round(cr.get(k, 0) * 100))
            sp.set_activates_default(True)
            spins[k] = sp
            g.attach(sp, 1, i, 1, 1)
        d.get_content_area().add(g)
        self.crop_dialog = (d, spins)
        d.show_all()
        ok = d.run() == Gtk.ResponseType.OK
        vals = {k: sp.get_value() / 100.0 for k, sp in spins.items()}
        d.destroy()
        self.crop_dialog = None
        if ok:
            for c in sel:
                self.edit(lambda p, c=c: p.set(c["id"], label="Crop", crop=vals))

    def cmd_fade_in(self, secs):
        self.each("Fade In", lambda p, c: p.set(c["id"], label="Fade In", fade_in=float(secs)))

    def cmd_fade_out(self, secs):
        self.each("Fade Out", lambda p, c: p.set(c["id"], label="Fade Out", fade_out=float(secs)))

    # audio (R3-05)
    def cmd_volume(self, v):
        self.each("Volume", lambda p, c: p.set(c["id"], label="Volume", volume=float(v)), "a clip with sound", kinds=("media",))

    def cmd_mute(self):
        sel = self.sel_or_say("a clip with sound", kinds=("media",))
        on = not all(c.get("muted") for c in sel)
        for c in sel:
            self.edit(lambda p, c=c: p.set(c["id"], label="Mute", muted=on))

    def cmd_music_bed(self):
        sel = [c for c in self.timeline.selected_clips() if self.project.find(c["id"])[0] == "music"]
        if not sel:
            sel = list(self.project.track("music"))
        if not sel:
            self.notice("Put music on the Music track first; it then dips under speech on the Audio track.")
            return
        on = not all(c.get("music_bed") for c in sel)
        for c in sel:
            self.edit(lambda p, c=c: p.set(c["id"], label="Music Bed", music_bed=on))
        self.notice("Music bed on: the music dips under the Audio track." if on else "Music bed off.")

    def _kf_target(self):
        sel = self.sel_or_say("a clip with sound", kinds=("media",))
        out = []
        for c in sel:
            if c["start"] <= self.playhead <= model.end_of(c):
                out.append(c)
        if sel and not out:
            self.notice("Move the playhead over the clip first.")
        return out

    def cmd_keyframe_add(self):
        for c in self._kf_target():
            t = self.playhead - c["start"]
            kf = [list(x) for x in c.get("keyframes", [])]
            v = engine._piecewise([tuple(x) for x in kf], t) if kf else 1.0
            kf = [x for x in kf if abs(x[0] - t) > 0.02] + [[t, v]]
            self.edit(lambda p, c=c, kf=kf: p.set_keyframes(c["id"], kf))

    def cmd_keyframe_dip(self):
        for c in self._kf_target():
            t = self.playhead - c["start"]
            kf = [list(x) for x in c.get("keyframes", [])]
            v = engine._piecewise([tuple(x) for x in kf], t) if kf else 1.0
            pts = [[max(0.0, t - 0.4), v], [t, v * 0.3], [min(c["duration"], t + 2.0), v * 0.3],
                   [min(c["duration"], t + 2.4), v]]
            kf = [x for x in kf if not (t - 0.4 <= x[0] <= t + 2.4)] + pts
            self.edit(lambda p, c=c, kf=kf: p.set_keyframes(c["id"], kf))

    def cmd_keyframe_clear(self):
        self.each("Volume Points", lambda p, c: p.set_keyframes(c["id"], []), "a clip with sound", kinds=("media",))

    # view
    def cmd_zoom_in(self):
        self.timeline.set_zoom(self.timeline.pps * 1.5)

    def cmd_zoom_out(self):
        self.timeline.set_zoom(self.timeline.pps / 1.5)

    def cmd_zoom_fit(self):
        self.timeline.zoom_fit()

    def cmd_snapping(self, on=None):
        self.project.snapping = self.snap_check.get_active() if on is None else on == "on"
        self.notice("Snapping %s." % ("on" if self.project.snapping else "off"))

    def cmd_aspect(self, a):
        w, h = ASPECTS.get(a, (1920, 1080))
        self.edit(lambda p: p.set_size(w, h))

    def cmd_fps(self, f):
        self.edit(lambda p: p.set_size(p.width, p.height, int(f)))

    # ------------------------------------------------------------ menus, search, keys
    def context_menu(self, ev):
        menu = Gtk.Menu()
        sel = self.timeline.selected_clips()
        items = [("Split at Playhead", "split"), None, ("Cut", "cut"), ("Copy", "copy"), ("Paste", "paste"),
                 ("Delete", "delete"), ("Ripple Delete", "ripple-delete"), None, ("Clip Settings", "clip-properties")]
        if any(self.project.find(c["id"])[0] == "music" for c in sel):
            items.append(("Music Bed", "music-bed"))
        if any(c["kind"] == "media" for c in sel):
            items.append(("Mute / Unmute", "mute"))
        for it in items:
            if it is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=it[0])
            mi.set_sensitive(it[1] == "paste" or bool(sel) or it[1] == "split")
            mi.connect("activate", lambda _m, c=it[1]: self.run(c))
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(self.timeline.area, None)
        menu.popup_at_pointer(ev)
        self._context_menu = menu
        return menu

    def on_search(self, entry):
        q = entry.get_text().strip().lower()
        if not q:
            return
        for c in self.ribbon.all_controls():
            if q in (c.label_text or "").lower():
                entry.set_text("")
                c.press()
                return
        self.notice("Nothing found for “%s”." % entry.get_text())

    def on_key_release(self, w, ev):
        name = (Gdk.keyval_name(ev.keyval) or "").lower()
        if name in ("alt_l", "alt_r") and self._alt_alone and not self.keytips.active and not self.backstage_open():
            self._alt_alone = False
            self.keytips.start()
            return True
        return False

    def on_key(self, w, ev):
        kv = ev.keyval
        state = ev.state & Gtk.accelerator_get_default_mod_mask()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(state & Gdk.ModifierType.MOD1_MASK)
        low = (Gdk.keyval_name(kv) or "").lower()
        self._alt_alone = low in ("alt_l", "alt_r")
        if self.keytips.active:
            return self.keytips.key(ev)
        if self.backstage_open():
            if kv == Gdk.KEY_Escape:
                self.backstage.close()
                return True
            return False
        focus = self.get_focus()
        typing = isinstance(focus, (Gtk.Entry, Gtk.TextView, Gtk.SpinButton))
        if kv == Gdk.KEY_F10 and not shift:
            self.keytips.start()
            return True
        if alt and low == "q":
            self.search.grab_focus()
            return True
        if alt and not ctrl and kv < 0x10000 and chr(kv).isalnum() and not typing:
            if self.keytips.start_with(chr(Gdk.keyval_to_upper(kv)).upper()):
                return True
        if kv == Gdk.KEY_F11 or (alt and kv in (Gdk.KEY_Return, Gdk.KEY_KP_Enter)):
            self.full_screen()
            return True
        if kv == Gdk.KEY_F12:
            self.run("save-as")
            return True
        if ctrl and not alt:
            cmds = {"n": "new", "o": "open", "s": "save", "w": "close", "z": "undo", "y": "redo", "e": "export",
                    "i": "import-media", "x": "cut", "c": "copy", "v": "paste", "a": "select-all", "equal": "zoom-in",
                    "plus": "zoom-in", "kp_add": "zoom-in", "minus": "zoom-out", "kp_subtract": "zoom-out", "0": "zoom-fit",
                    "t": "insert-title", "b": "split", "g": "group", "j": "go-to-time"}
            if shift:
                cmds = {"s": "save-as", "z": "redo", "g": "ungroup"}
            if low in cmds:
                if typing and low in ("z", "y", "x", "c", "v", "a"):
                    return False
                self.run(cmds[low])
                return True
            return False
        if typing:
            return False
        if low == "space":
            self.toggle_play()
            return True
        if low in ("j", "k", "l") and not alt:
            self.shuttle_key(low)
            return True
        if low == "left":
            self.step(-self.project.fps if shift else -1)
            return True
        if low == "right":
            self.step(self.project.fps if shift else 1)
            return True
        if low == "home":
            self.run("go-start")
            return True
        if low == "end":
            self.run("go-end")
            return True
        if low == "s" and not alt:
            self.run("split")
            return True
        if low == "m" and not alt:                       # markers (R4-05)
            self.run("marker-rename" if shift else "marker-add")
            return True
        if low in ("comma", "period") and not alt:
            self.run("marker-prev" if low == "comma" else "marker-next")
            return True
        if low in ("delete", "backspace"):
            self.run("ripple-delete" if shift else "delete")
            return True
        if low == "escape":
            if self.full is not None:
                self.full.leave()
            else:
                self.timeline.select([])
            return True
        return False

    # ------------------------------------------------------------ closing
    def _remember_geometry(self, *_):
        st = self.get_window().get_state() if self.get_window() else 0
        maxed = bool(st & Gdk.WindowState.MAXIMIZED)
        geo = self.app.settings.setdefault("window", {})
        geo["max"] = maxed
        if not maxed:
            w, h = self.get_size()
            geo["w"], geo["h"] = w, h
        return False

    def on_delete(self, w, ev):
        """True keeps the window open."""
        if self.recorder is not None:
            self.recorder.stop()
        if self.exports:
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.NONE, text="A video is still being exported.")
            d.format_secondary_text("Closing stops the export.")
            d.add_button("Keep Exporting", Gtk.ResponseType.CANCEL)
            d.add_button("Stop and Close", Gtk.ResponseType.OK)
            self.close_dialog = d
            r = d.run()
            d.destroy()
            self.close_dialog = None
            if r != Gtk.ResponseType.OK:
                return True
            self.cancel_exports()
        if self.project.dirty and (self.project.undo_stack or self.path):
            d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.NONE, text="Save changes to “%s”?" % self.doc_name())
            d.set_title(APP_NAME)
            d.add_button("Don't Save", Gtk.ResponseType.NO)
            d.add_button("Cancel", Gtk.ResponseType.CANCEL)
            d.add_button("Save", Gtk.ResponseType.YES)
            d.set_default_response(Gtk.ResponseType.YES)
            self.close_dialog = d
            r = d.run()
            d.destroy()
            self.close_dialog = None
            if r == Gtk.ResponseType.YES:
                if not self.save():
                    return True
            elif r != Gtk.ResponseType.NO:
                return True
        self.pause()
        if self.full is not None:
            self.full.leave()
        if self.preview is not None:
            self.preview.close()
        self.app.window_closed(self)
        return False


class FullPreview(Gtk.Window):
    """Full-screen preview (R3-02): the picture alone; Esc, F11 or a double-click goes back."""
    def __init__(self, win):
        Gtk.Window.__init__(self)
        self.win = win
        self.set_title("%s - Full Screen" % APP_NAME)
        self.get_style_context().add_class("reel-preview")
        self.set_transient_for(win)
        frame = Gtk.AspectFrame(ratio=win.project.width / float(win.project.height), obey_child=False)
        frame.set_shadow_type(Gtk.ShadowType.NONE)
        frame.get_style_context().add_class("reel-preview")
        self.frame = frame
        ev = Gtk.EventBox()
        ev.get_style_context().add_class("reel-preview")
        ev.add(frame)
        ev.connect("button-press-event", lambda w, e: (self.leave() if e.type == Gdk.EventType._2BUTTON_PRESS else None, False)[1])
        self.add(ev)
        win._detach_preview_widget()
        frame.add(win.preview_widget)
        self.connect("key-press-event", self._key)
        self.connect("delete-event", lambda *_: (self.leave(), True)[1])
        self.show_all()
        self.fullscreen()

    def on_key(self, w, ev):
        return self._key(w, ev)

    def _key(self, w, ev):
        if ev.keyval in (Gdk.KEY_Escape, Gdk.KEY_F11):
            self.leave()
            return True
        return self.win.on_key(w, ev)

    def leave(self):
        win = self.win
        if win.full is not self:
            return
        win.full = None
        win._detach_preview_widget()
        win.preview_frame.add(win.preview_widget)
        win.preview_widget.show()
        self.destroy()
        win.present()


class RecordBar(Gtk.Window):
    """While recording: the time so far and Stop."""
    def __init__(self, win, rec):
        Gtk.Window.__init__(self, title="Recording - %s" % APP_NAME)
        self.win = win
        self.rec = rec
        self.set_transient_for(win)
        self.set_keep_above(True)
        self.set_resizable(False)
        box = Gtk.Box(spacing=10, margin=10)
        box.pack_start(icons.image("reel-record", 16), False, False, 0)
        self.label = Gtk.Label(label="Starting…")
        self.label.set_width_chars(16)
        box.pack_start(self.label, False, False, 0)
        stop = Gtk.Button(label="Stop")
        stop.get_style_context().add_class("suggested-action")
        stop.connect("clicked", lambda *_: self.stop())
        self.stop_button = stop
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.cancel())
        box.pack_start(stop, False, False, 0)
        box.pack_start(cancel, False, False, 0)
        self.add(box)
        self.connect("delete-event", lambda *_: (self.stop(), True)[1])
        self._timer = GLib.timeout_add(250, self._tick)
        self.show_all()

    def _tick(self):
        if self.rec.started is not None:
            self.label.set_text("Recording %s" % model.fmt_time(self.rec.elapsed()))
        return True

    def stop(self):
        self.label.set_text("Finishing…")
        self.stop_button.set_sensitive(False)
        self.rec.stop()

    def cancel(self):
        self.rec.cancel()
        self.win.recorder = None
        self.win.record_bar = None
        self.destroy()

    def destroy(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = None
        Gtk.Window.destroy(self)
