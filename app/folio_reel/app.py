"""Folio Reel application: windows, recent projects, settings."""
import json
import os
import sys

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION  # noqa: E402

GLib.set_prgname(APP_ID)
GLib.set_application_name(APP_NAME)
Gdk.set_program_class(APP_ID)

_CONFIG_ROOT = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONFIG = os.path.join(_CONFIG_ROOT, "folio-reel")
HERE = os.path.dirname(os.path.abspath(__file__))


class ReelApp(Gtk.Application):
    def __init__(self):
        Gtk.Application.__init__(self, application_id=APP_ID,
                                 flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE)
        self.windows = []
        self.settings = self._load_settings()
        self._untitled = 0

    # ------------------------------------------------------------ settings
    def _load_settings(self):
        try:
            with open(os.path.join(CONFIG, "settings.json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"recent": []}

    def save_settings(self):
        os.makedirs(CONFIG, exist_ok=True)
        tmp = os.path.join(CONFIG, "settings.json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.settings, f, indent=1)
        os.replace(tmp, os.path.join(CONFIG, "settings.json"))

    def add_recent(self, path):
        path = os.path.abspath(path)
        rec = [p for p in self.settings.get("recent", []) if p != path]
        rec.insert(0, path)
        self.settings["recent"] = rec[:30]
        try:
            self.save_settings()
        except OSError:
            pass

    def recent(self):
        return [p for p in self.settings.get("recent", []) if os.path.exists(p)]

    def next_untitled(self):
        self._untitled += 1
        return "Project%d" % self._untitled

    # ------------------------------------------------------------ life cycle
    def do_startup(self):
        Gtk.Application.do_startup(self)
        screen = Gdk.Screen.get_default()
        for i, name in enumerate(("theme.css", "reel.css")):
            css = Gtk.CssProvider()
            css.load_from_path(os.path.join(HERE, name))
            Gtk.StyleContext.add_provider_for_screen(screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + i)
        from . import appearance, fontfix
        self._dark_css = Gtk.CssProvider()
        self._dark_css.load_from_path(os.path.join(HERE, "theme-dark.css"))
        appearance.apply_initial()
        self._apply_dark(appearance.is_dark())
        appearance.on_change(self._apply_dark)
        fontfix.install()
        from gi.repository import GObject

        def _own(w, *a):
            try:
                if w.get_window_type() == Gtk.WindowType.TOPLEVEL and not hasattr(w, "ribbon") \
                        and not isinstance(w, Gtk.FileChooserDialog):
                    w.get_style_context().add_class("folio-dialog")
            except Exception:       # noqa: BLE001
                pass
            return True
        GObject.add_emission_hook(Gtk.Window, "realize", _own)

    def _apply_dark(self, dark):
        screen = Gdk.Screen.get_default()
        if screen is None:
            return
        if dark:
            Gtk.StyleContext.add_provider_for_screen(screen, self._dark_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)
        else:
            Gtk.StyleContext.remove_provider_for_screen(screen, self._dark_css)
        from . import icons
        icons.restyle()
        for w in Gtk.Window.list_toplevels():
            if hasattr(w, "restyle"):
                w.restyle()
            w.queue_draw()

    def do_activate(self):
        if self.windows:
            self.windows[-1].present()
            return
        self._maybe_script(self.new_window())
        GLib.idle_add(self.offer_recovery)

    def offer_recovery(self):
        """Projects with unsaved changes left behind by a Reel that didn't close properly: ask
        about each, and open the ones wanted with their changes in place."""
        from . import model, recovery
        if getattr(self, "_recovery_asked", False):
            return False
        self._recovery_asked = True
        for entry in recovery.pending()[:5]:
            parent = self.windows[-1] if self.windows else None
            d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION,
                                  buttons=Gtk.ButtonsType.NONE,
                                  text="Folio Reel didn't close properly last time.")
            d.format_secondary_text("Bring back “%s” with the changes that weren't saved (kept at %s)?"
                                    % (entry["name"], entry["when"]))
            d.set_title(APP_NAME)
            d.add_button("Discard", Gtk.ResponseType.NO)
            d.add_button("Recover", Gtk.ResponseType.YES)
            d.set_default_response(Gtk.ResponseType.YES)
            self.recovery_dialog = d
            r = d.run()
            d.destroy()
            self.recovery_dialog = None
            if r == Gtk.ResponseType.YES:
                try:
                    p = model.Project(model.check_project(entry["project"]), entry.get("path"))
                except model.EditError:
                    recovery.clear(entry["id"])
                    continue
                blank = [w for w in self.windows if w.is_blank()]
                win = blank[0] if blank else self.new_window()
                p.recovered = True          # unsaved work: closing asks, even with nothing to undo
                win.adopt(p, entry.get("path"), changed=True)
                win.notice("Recovered “%s”. Save it to keep it." % entry["name"], 20)
            if r in (Gtk.ResponseType.YES, Gtk.ResponseType.NO):
                recovery.clear(entry["id"])
        return False

    def _maybe_script(self, win):
        script = os.environ.get("FOLIO_TEST_SCRIPT")
        if script:
            def run_script():
                ns = {"app": self, "win": win, "GLib": GLib, "Gtk": Gtk, "Gdk": Gdk}
                try:
                    with open(script) as f:
                        exec(compile(f.read(), script, "exec"), ns)
                except Exception:       # noqa: BLE001
                    import traceback
                    traceback.print_exc()
                    sys.stdout.flush()
                    os._exit(3)
                return False
            GLib.timeout_add(int(os.environ.get("FOLIO_TEST_DELAY", "2500")), run_script)

    def do_open(self, files, n_files, hint):
        win = None
        for f in files:
            path = f.get_path()
            if path:
                win = self.open_path(path)
        if win is not None:
            self._maybe_script(win)
        elif not self.windows:
            # the file couldn't be opened (the reason has been shown): a window to work in all the same
            self._maybe_script(self.new_window())
        GLib.idle_add(self.offer_recovery)

    def new_window(self, path=None):
        from .window import ReelWindow
        win = ReelWindow(self, path)
        self.windows.append(win)
        win.present()
        return win

    def open_path(self, path, from_window=None):
        path = os.path.abspath(path)
        for w in self.windows:
            if w.path == path:
                w.present()
                return w
        if from_window is not None and from_window.is_blank():
            from_window.open_file(path)
            return from_window
        blank = [w for w in self.windows if w.is_blank()]
        win = blank[0] if blank else self.new_window()
        if win.open_file(path) is False and not blank and len(self.windows) > 1:
            # nothing to show in the window made for it
            win.project.dirty = False
            self.windows.remove(win)
            if win.preview is not None:
                win.preview.close()
                win.preview = None
            win.destroy()
            return None
        return win

    def window_closed(self, win):
        if win in self.windows:
            self.windows.remove(win)
        try:
            self.save_settings()
        except OSError:
            pass
        if not self.windows:
            GLib.idle_add(self.quit)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    if "--version" in argv:
        print("%s %s" % (APP_NAME, VERSION))
        return 0
    if "--help" in argv or "-h" in argv:
        from . import cli
        print(cli.USAGE)
        return 0
    if "--render" in argv:
        # R3-08: render a project (or a Folio Show slide list) to a video without a window
        from . import cli
        return cli.render(argv[argv.index("--render") + 1:])
    app = ReelApp()
    code = app.run(argv)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code or 0)
