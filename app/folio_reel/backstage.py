"""File: New, Open, Save, Save As, Export and Close, laid out as the suite's other apps do it."""
import os

from gi.repository import Gtk, Pango

from . import APP_NAME, VERSION, icons
from .engine import FORMATS
from .model import EXPORT_PRESETS, PRESETS

PAGES = [("home", "Home", "B"), ("new", "New", "N"), ("open", "Open", "O"), ("save", "Save", "S"),
         ("save-as", "Save As", "A"), ("export", "Export", "E"), ("close", "Close", "C"), ("about", "About", "D")]
PRESET_NAMES = {"720p": "HD 720p (1280 × 720)", "1080p": "Full HD 1080p (1920 × 1080)", "4k": "4K (3840 × 2160)"}


class Backstage(Gtk.Box):
    def __init__(self, win):
        Gtk.Box.__init__(self)
        self.win = win
        self.get_style_context().add_class("folio-backstage")
        self.set_hexpand(True)
        self.set_vexpand(True)
        nav = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        nav.get_style_context().add_class("folio-bs-nav")
        nav.set_size_request(180, -1)
        back = Gtk.Button(label="←")
        back.get_style_context().add_class("folio-bs-navbtn")
        back.get_style_context().add_class("back")
        back.set_tooltip_text("Back (Esc)")
        back.connect("clicked", lambda *_: self.close())
        nav.pack_start(back, False, False, 0)
        self.buttons = {}
        for key, label, tip in PAGES:
            b = Gtk.Button(label=label)
            b.get_child().set_xalign(0)
            b.get_style_context().add_class("folio-bs-navbtn")
            b.keytip = tip
            b.connect("clicked", lambda _b, k=key: self.pick(k))
            nav.pack_start(b, False, False, 0)
            self.buttons[key] = b
        self.pack_start(nav, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.body.get_style_context().add_class("folio-bs-body")
        self.body.set_margin_start(40)
        self.body.set_margin_top(24)
        self.body.set_margin_end(40)
        self.pack_start(self.body, True, True, 0)
        self.page = None

    # ------------------------------------------------------------ pages
    def open(self, page="home"):
        self.show_all()
        self.pick(page)

    def close(self):
        self.hide()
        self.win.focus_document()

    def pick(self, key):
        if key in ("save", "save-as", "close"):
            self.close()
            self.win.run(key)
            return
        for k, b in self.buttons.items():
            ctx = b.get_style_context()
            (ctx.add_class if k == key else ctx.remove_class)("active")
        for ch in self.body.get_children():
            self.body.remove(ch)
        self.page = key
        getattr(self, "_page_" + key.replace("-", "_"))()
        self.body.show_all()

    def _title(self, text):
        lab = Gtk.Label(label=text, xalign=0)
        lab.get_style_context().add_class("folio-bs-title")
        self.body.pack_start(lab, False, False, 0)

    def _tile(self, label, sub, icon, cb):
        b = Gtk.Button()
        b.get_style_context().add_class("folio-bs-tile")
        box = Gtk.Box(spacing=10)
        box.pack_start(icons.image(icon, 32), False, False, 0)
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        t = Gtk.Label(label=label, xalign=0)
        t.get_style_context().add_class("folio-bs-cardtitle")
        v.pack_start(t, False, False, 0)
        if sub:
            s = Gtk.Label(label=sub, xalign=0)
            s.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            s.set_max_width_chars(70)
            s.get_style_context().add_class("dim-label")
            v.pack_start(s, False, False, 0)
        box.pack_start(v, True, True, 0)
        b.add(box)
        b.connect("clicked", lambda *_: cb())
        return b

    def _new_tiles(self):
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(3)
        for label, sub, aspect in (("Widescreen video", "16:9, for screens and video sites", "16:9"),
                                   ("Portrait video", "9:16, for phones", "9:16"),
                                   ("Square video", "1:1", "1:1")):
            flow.add(self._tile(label, sub, "reel-aspect", lambda a=aspect: (self.close(), self.win.run("new:" + a))))
        return flow

    def _recent_list(self, limit=12):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        rec = self.win.app.recent()[:limit]
        if not rec:
            lab = Gtk.Label(label="Projects you open will show here.", xalign=0)
            lab.get_style_context().add_class("dim-label")
            box.pack_start(lab, False, False, 0)
        for path in rec:
            box.pack_start(self._tile(os.path.basename(path), os.path.dirname(path), "reel-fps",
                                      lambda p=path: (self.close(), self.win.open_file(p, ask=True))), False, False, 0)
        return box

    def _page_home(self):
        self._title("Good to see you")
        self.body.pack_start(self._new_tiles(), False, False, 0)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>Recent</b>")
        lab.set_margin_top(16)
        self.body.pack_start(lab, False, False, 0)
        self.body.pack_start(self._recent_list(), False, False, 0)

    def _page_new(self):
        self._title("New")
        self.body.pack_start(self._new_tiles(), False, False, 0)

    def _page_open(self):
        self._title("Open")
        self.body.pack_start(self._tile("Browse", "Open a Folio Reel project (.reel)", "open",
                                        lambda: (self.close(), self.win.run("open"))), False, False, 0)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>Recent</b>")
        lab.set_margin_top(12)
        self.body.pack_start(lab, False, False, 0)
        self.body.pack_start(self._recent_list(30), False, False, 0)

    def _page_export(self):
        self._title("Export")
        grid = Gtk.Grid(column_spacing=12, row_spacing=8)
        self.fmt = Gtk.ComboBoxText()
        for k, name in FORMATS.items():
            self.fmt.append(k, name)
        self.fmt.set_active_id(self.win.app.settings.get("export_format", "mp4"))
        self.preset = Gtk.ComboBoxText()
        for k in PRESETS:
            self.preset.append(k, PRESET_NAMES[k])
        self.preset.set_active_id(self.win.app.settings.get("export_preset", "1080p"))
        grid.attach(Gtk.Label(label="Format", xalign=0), 0, 0, 1, 1)
        grid.attach(self.fmt, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="Quality", xalign=0), 0, 1, 1, 1)
        grid.attach(self.preset, 1, 1, 1, 1)
        self.body.pack_start(grid, False, False, 0)
        note = Gtk.Label(label="You can keep editing while it renders; the export uses the project as it is now.",
                         xalign=0)
        note.get_style_context().add_class("dim-label")
        note.set_margin_top(8)
        self.body.pack_start(note, False, False, 0)
        go = Gtk.Button(label="Export…")
        go.get_style_context().add_class("suggested-action")
        go.set_halign(Gtk.Align.START)
        go.set_margin_top(12)
        go.connect("clicked", lambda *_: (self.close(), self.win.export_as(self.fmt.get_active_id(),
                                                                            self.preset.get_active_id())))
        self.export_button = go
        self.body.pack_start(go, False, False, 0)
        # named presets, and a queue that runs them one after another (R4-08)
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>Presets</b>")
        lab.set_margin_top(18)
        self.body.pack_start(lab, False, False, 0)
        hint = Gtk.Label(label="One click picks the format and the size. Several exports wait their turn and run "
                               "one after another, so the machine isn't trying to make them all at once.", xalign=0)
        hint.get_style_context().add_class("dim-label")
        hint.set_line_wrap(True)
        self.body.pack_start(hint, False, False, 0)
        self.preset_buttons = []
        for name, fmt, size in EXPORT_PRESETS:
            b = Gtk.Button(label=name)
            b.set_halign(Gtk.Align.START)
            b.connect("clicked", lambda _b, f=fmt, p=size: (self.close(), self.win.export_as(f, p)))
            self.preset_buttons.append((name, b))
            self.body.pack_start(b, False, False, 0)

    def _page_about(self):
        self._title("About")
        lab = Gtk.Label(xalign=0)
        lab.set_markup("<b>%s %s</b>\nPart of Folio Studio. Video editing on this computer: no account, no cloud.\n\n"
                       "Icons: Colibre (MPL 2.0 / CC BY-SA 4.0) and Folio's own." % (APP_NAME, VERSION))
        lab.set_line_wrap(True)
        self.body.pack_start(lab, False, False, 0)
