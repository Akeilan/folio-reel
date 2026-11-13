"""X4-05: write down everything a Folio app puts in front of a person, as plain lines.

Run inside any Folio app through that app's own test harness (they all exec FOLIO_TEST_SCRIPT with
the window up). It walks the real widget tree rather than any one app's own structures, so it reads
a ribbon, a menu bar, a toolbar or a side pane alike, and an app that lost its whole menu bar shows
up as hundreds of lines gone.

  SURFACE_OUT=/tmp/x.json  <app>/tests/run_ui.sh surface.py

Each line is a path: "menu:File > Open", "ribbon:Home > Clipboard > Paste", "page:Export".
"""
import json
import os
import sys

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

OUT = os.environ.get("SURFACE_OUT") or "/tmp/folio-surface.json"
MAX_DEPTH = 24


def _label_of(w):
    """What a person reads on this widget, or None."""
    for get in ("get_label", "get_text", "get_title"):
        if hasattr(w, get):
            try:
                t = getattr(w, get)()
            except TypeError:
                continue
            if t and isinstance(t, str) and t.strip():
                return " ".join(t.split())[:80]
    # a button holding a box with a label in it
    if isinstance(w, Gtk.Container):
        for kid in w.get_children():
            if isinstance(kid, Gtk.Label):
                t = kid.get_text()
                if t and t.strip():
                    return " ".join(t.split())[:80]
            if isinstance(kid, Gtk.Container):
                for g in kid.get_children():
                    if isinstance(g, Gtk.Label) and g.get_text() and g.get_text().strip():
                        return " ".join(g.get_text().split())[:80]
    return None


def _kind(w):
    if isinstance(w, Gtk.MenuItem):
        return "menu"
    if isinstance(w, (Gtk.Button, Gtk.ToolButton)):
        return "button"
    if isinstance(w, Gtk.ComboBox):
        return "choice"
    if isinstance(w, (Gtk.Entry, Gtk.SpinButton)):
        return "field"
    return None


def _walk(w, trail, out, depth=0):
    if depth > MAX_DEPTH or w is None:
        return
    try:
        visible = w.get_visible()
    except Exception:      # noqa: BLE001
        visible = True
    name = _label_of(w)
    here = trail
    kind = _kind(w)
    if name and kind and visible:
        here = trail + [name]
        out.add("%s:%s" % (kind, " > ".join(here)))
    elif name and visible and isinstance(w, Gtk.Notebook):
        here = trail + [name]
    if isinstance(w, Gtk.MenuItem):
        sub = w.get_submenu()
        if sub is not None:
            _walk(sub, here, out, depth + 1)
        return
    if isinstance(w, Gtk.Notebook):
        for i in range(w.get_n_pages()):
            page = w.get_nth_page(i)
            title = w.get_tab_label_text(page) or "page %d" % i
            out.add("tab:%s" % " > ".join(trail + [title]))
            _walk(page, trail + [title], out, depth + 1)
        return
    if isinstance(w, Gtk.Container):
        for kid in w.get_children():
            _walk(kid, here, out, depth + 1)


def collect():
    """Every line this app shows right now."""
    out = set()
    for win in Gtk.Window.list_toplevels():
        try:
            if not win.get_visible():
                continue
        except Exception:      # noqa: BLE001
            continue
        title = (win.get_title() or "window").split(" - ")[-1]
        _walk(win, [], out, 0)
        out.add("window:%s" % title)
    return out


def _ribbon_lines(win):
    """The ribbon's own account of itself, where an app has one: tabs, groups and controls are
    built before they are ever shown, so walking the tree alone would miss the tabs behind the
    one on top."""
    out = set()
    r = getattr(win, "ribbon", None)
    if r is None:
        return out
    for tab in getattr(r, "tabs", []) or []:
        tname = getattr(tab, "name", None) or _label_of(tab) or "tab"
        out.add("ribbon:%s" % tname)
        body = getattr(tab, "body", None)
        if body is not None:
            for grp in body.get_children():
                cap = getattr(grp, "caption", None) or _group_caption(grp)
                if cap:
                    out.add("ribbon:%s > %s" % (tname, cap))
        for c in getattr(tab, "controls", []) or []:
            act = getattr(c, "action", None)
            lab = _label_of(c) or act
            if lab:
                out.add("ribbon:%s > %s%s" % (tname, lab, " [%s]" % act if act else ""))
    for c in getattr(r, "controls", []) or []:
        act = getattr(c, "action", None)
        lab = _label_of(c) or act
        if lab:
            out.add("control:%s%s" % (lab, " [%s]" % act if act else ""))
    return out


def _group_caption(grp):
    """A ribbon group's caption: the label at the foot of it."""
    if not isinstance(grp, Gtk.Container):
        return None
    for kid in grp.get_children():
        if isinstance(kid, Gtk.Label):
            t = kid.get_text()
            if t and t.strip():
                return " ".join(t.split())[:60]
    return None


def _commands(win):
    """Every command the window answers to."""
    return {"command:" + n[4:].replace("_", "-") for n in dir(win)
            if n.startswith("cmd_") and callable(getattr(win, n, None))}


def main():
    lines = set()
    wins = [w for w in Gtk.Window.list_toplevels() if w.get_visible()]
    main_win = wins[0] if wins else None
    for w in wins:
        if hasattr(w, "ribbon") or hasattr(w, "run"):
            main_win = w
            break
    lines |= collect()
    if main_win is not None:
        lines |= _ribbon_lines(main_win)
        lines |= _commands(main_win)
    data = {"app": os.environ.get("SURFACE_APP") or (main_win.get_title() if main_win else "?"),
            "lines": sorted(lines)}
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1)
    print("surface: %d lines -> %s" % (len(data["lines"]), OUT))
    sys.stdout.flush()
    GLib.idle_add(lambda: os._exit(0))


main()
