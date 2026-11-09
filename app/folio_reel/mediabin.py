"""The media bin (R3-01): the project's video, sound and pictures, with thumbnails. Drag one to
the timeline, double-click it to add it at the playhead."""
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from . import icons, model

COL_PIX, COL_NAME, COL_URI, COL_TIP = range(4)


class MediaBin(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self, orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.get_style_context().add_class("reel-bin")
        self.set_size_request(230, -1)
        head = Gtk.Box(spacing=4)
        title = Gtk.Label(label="Media", xalign=0)
        title.get_style_context().add_class("reel-pane-title")
        head.pack_start(title, True, True, 0)
        imp = Gtk.Button()
        imp.set_relief(Gtk.ReliefStyle.NONE)
        imp.add(icons.image("reel-import", 16))
        imp.set_tooltip_text("Import Media (Ctrl+I)")
        imp.connect("clicked", lambda *_: win.run("import-media"))
        head.pack_end(imp, False, False, 2)
        self.pack_start(head, False, False, 0)
        self.store = Gtk.ListStore(GdkPixbuf.Pixbuf, str, str, str)
        self.view = Gtk.IconView(model=self.store)
        self.view.set_pixbuf_column(COL_PIX)
        self.view.set_text_column(COL_NAME)
        self.view.set_tooltip_column(COL_TIP)
        self.view.set_item_width(96)
        self.view.set_columns(-1)
        self.view.set_margin(4)
        self.view.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.view.connect("item-activated", self._activated)
        self.view.connect("button-press-event", self._press)
        self.view.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY)
        self.view.drag_source_add_uri_targets()
        self.view.connect("drag-data-get", self._drag_get)
        # files dropped from the file manager are imported
        self.view.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.view.drag_dest_add_uri_targets()
        self.view.connect("drag-data-received", lambda w, c, x, y, d, i, t: win.import_uris(d.get_uris() or []))
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.add(self.view)
        self.empty = Gtk.Label(label="Import video, sound and pictures, or drop them here.")
        self.empty.set_line_wrap(True)
        self.empty.set_max_width_chars(22)
        self.empty.get_style_context().add_class("reel-hint")
        ov = Gtk.Overlay()
        ov.add(sw)
        ov.add_overlay(self.empty)
        ov.set_overlay_pass_through(self.empty, True)
        self.pack_start(ov, True, True, 0)
        self._thumbs = {}

    def _icon_for(self, m):
        if m["uri"] in self._thumbs:
            return self._thumbs[m["uri"]]
        pb = None
        if m.get("has_video") or m.get("is_image"):
            from . import engine
            try:
                pb = engine.thumbnail(m, None, 88)
            except Exception:       # noqa: BLE001
                pb = None
        if pb is None:
            pb = icons.pixbuf("reel-music" if m.get("has_audio") else "insertgraphic", 32)
        self._thumbs[m["uri"]] = pb
        return pb

    def refresh(self):
        sel = set(self.selected_uris())
        self.store.clear()
        for m in self.win.project.media:
            kind = "picture" if m.get("is_image") else ("video" if m.get("has_video") else "sound")
            tip = "%s\n%s%s" % (m["name"], kind,
                                "" if m.get("is_image") else ", " + model.fmt_time(m.get("duration", 0)))
            if m.get("width"):
                tip += ", %d × %d" % (m["width"], m["height"])
            it = self.store.append([None, m["name"], m["uri"], GLib.markup_escape_text(tip)])
            if m["uri"] in sel:
                self.view.select_path(self.store.get_path(it))
        self.empty.set_visible(len(self.store) == 0)
        GLib.idle_add(self._fill_icons)

    def _fill_icons(self):
        for row in self.store:
            if row[COL_PIX] is None:
                m = self.win.project.media_by_uri(row[COL_URI])
                if m is not None:
                    row[COL_PIX] = self._icon_for(m)
        return False

    def selected_uris(self):
        return [self.store[p][COL_URI] for p in self.view.get_selected_items()]

    def select_uri(self, uri):
        self.view.unselect_all()
        for row in self.store:
            if row[COL_URI] == uri:
                self.view.select_path(row.path)

    def _activated(self, view, path):
        self.win.add_media_to_timeline([self.store[path][COL_URI]])

    def _drag_get(self, view, ctx, data, info, time):
        data.set_uris(self.selected_uris())
        return True

    def _press(self, view, ev):
        if ev.button == 1:
            # pressing a thumbnail picks it, so dragging it to the timeline carries that one: the
            # drag hands over whatever is selected, and before this an unselected thumbnail
            # dragged nothing at all (R5-06)
            path = view.get_path_at_pos(int(ev.x), int(ev.y))
            if path is not None and not view.path_is_selected(path) \
                    and not (ev.state & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK)):
                view.unselect_all()
                view.select_path(path)
            return False
        if ev.button != 3:
            return False
        path = view.get_path_at_pos(int(ev.x), int(ev.y))
        if path is not None and not view.path_is_selected(path):
            view.unselect_all()
            view.select_path(path)
        menu = Gtk.Menu()
        for label, cmd in (("Add to Timeline", "add-to-timeline"), ("Import Media…", "import-media"),
                           (None, None), ("Remove from Project", "remove-media")):
            if label is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=label)
            mi.set_sensitive(cmd == "import-media" or bool(self.selected_uris()))
            mi.connect("activate", lambda _m, c=cmd: self.win.run(c))
            menu.append(mi)
        menu.show_all()
        menu.attach_to_widget(view, None)
        menu.popup_at_pointer(ev)
        self.context_menu = menu
        return True
