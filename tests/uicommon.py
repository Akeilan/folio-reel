# Shared by the UI tests (exec'd into the test script's namespace, which has app, win, Gtk, Gdk, GLib).
import os
import sys
import time

from gi.repository import Gdk, GLib, Gtk

FAILS = []
N = [0]
OUT = os.environ.get("UI_OUT", "/tmp/ui_out_reel")
os.makedirs(OUT, exist_ok=True)
TESTS = os.environ.get("REEL_TESTS") or os.path.dirname(os.environ["FOLIO_TEST_SCRIPT"])
sys.path.insert(0, TESTS)
import mkmedia  # noqa: E402
MEDIA = mkmedia.make(os.path.join(os.environ.get("REEL_MEDIA_DIR", "/tmp"), "reel_ui_media"))
from folio_reel import model as _model  # noqa: E402
URI = {k: _model.path_to_uri(v) for k, v in MEDIA.items()}


def pump(t=0.15):
    end = time.time() + t
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.003)


def wait(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        pump(0.05)
    return cond()


def check(cond, what, info=None):
    N[0] += 1
    print(("ok   " if cond else "FAIL ") + what + ("" if cond or info is None else "  -- %r" % (info,)))
    sys.stdout.flush()
    if not cond:
        FAILS.append(what)
    return cond


def shot(name, w=None):
    import cairo
    pump(0.3)
    gw = (w or win).get_window()
    img = cairo.ImageSurface(cairo.FORMAT_ARGB32, gw.get_width(), gw.get_height())
    cr = cairo.Context(img)
    Gdk.cairo_set_source_window(cr, gw, 0, 0)
    cr.paint()
    path = os.path.join(OUT, name + ".png")
    img.write_to_png(path)
    return img


def pixel(img, x, y):
    data = img.get_data()
    i = y * img.get_stride() + x * 4
    return data[i + 2], data[i + 1], data[i]


class Ev:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def get_scroll_deltas(self):
        return True, getattr(self, "dx", 0.0), getattr(self, "dy", 0.0)


def key(name, ctrl=False, shift=False, alt=False, w=None):
    st = 0
    if ctrl:
        st |= Gdk.ModifierType.CONTROL_MASK
    if shift:
        st |= Gdk.ModifierType.SHIFT_MASK
    if alt:
        st |= Gdk.ModifierType.MOD1_MASK
    ev = Ev(keyval=Gdk.keyval_from_name(name), state=Gdk.ModifierType(st), type=Gdk.EventType.KEY_PRESS)
    target = w or win
    r = target.on_key(target, ev)
    pump(0.05)
    return r


def key_release(name):
    ev = Ev(keyval=Gdk.keyval_from_name(name), state=Gdk.ModifierType(0), type=Gdk.EventType.KEY_RELEASE)
    return win.on_key_release(win, ev)


def tl_click(x, y, button=1, double=False, shift=False, ctrl=False, dx=0, dy=0, release=True):
    """Press (drag, release) on the timeline at pixel x, y."""
    t = win.timeline
    st = Gdk.ModifierType((Gdk.ModifierType.SHIFT_MASK if shift else 0) | (Gdk.ModifierType.CONTROL_MASK if ctrl else 0))
    ev = Ev(type=Gdk.EventType._2BUTTON_PRESS if double else Gdk.EventType.BUTTON_PRESS, x=float(x), y=float(y),
            button=button, state=st)
    t._press(t.area, ev)
    if dx or dy:
        for k in range(1, 7):
            m = Ev(type=Gdk.EventType.MOTION_NOTIFY, x=float(x + dx * k / 6), y=float(y + dy * k / 6),
                   state=Gdk.ModifierType(st | Gdk.ModifierType.BUTTON1_MASK))
            t._motion(t.area, m)
    if release:
        t._release(t.area, Ev(type=Gdk.EventType.BUTTON_RELEASE, x=float(x + dx), y=float(y + dy), button=button, state=st))
    pump(0.08)


def clip_xy(c, frac=0.5):
    """Pixel position on the timeline of a point frac along clip c."""
    t = win.timeline
    tr = win.project.find(c["id"])[0]
    y, h = t.track_rect(tr)
    return t.x_of(c["start"] + c["duration"] * frac), y + h / 2


def clips(track):
    return win.project.track(track)


def settle():
    win.flush()
    pump(0.3)


def snap_rgb(t):
    """The preview's picture at time t (average of the middle)."""
    win.pause()
    win.seek(t)
    win._do_seek()
    pump(0.2)
    pb = win.preview.snapshot()
    if pb is None:
        return None
    small = pb.scale_simple(8, 8, 2)
    px = small.get_pixels()
    rs, n = small.get_rowstride(), small.get_n_channels()
    tot = [0, 0, 0]
    for y in range(2, 6):
        for x in range(2, 6):
            for k in range(3):
                tot[k] += px[y * rs + x * n + k]
    return tuple(v // 16 for v in tot)


def respond(dialog_attr, response, delay=400, setup=None):
    """Answer the modal dialog the window keeps in win.<dialog_attr> once it shows."""
    def go():
        d = getattr(win, dialog_attr, None)
        if d is None:
            return True
        if isinstance(d, tuple):
            if setup:
                setup(d)
            d = d[0]
        elif setup:
            setup(d)
        d.response(response)
        return False
    GLib.timeout_add(delay, go)


def finish():
    print("%d checks, %d failed" % (N[0], len(FAILS)))
    print("all passed" if not FAILS else "FAILED")
    sys.stdout.flush()
    sys.stdout.flush()
    os._exit(1 if FAILS else 0)
