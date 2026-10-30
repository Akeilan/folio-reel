"""Recording straight into the project (R3-07): the screen, one window, the camera, or a
voice-over from the microphone.

X11: the screen and windows through ximagesrc. Wayland: the desktop's screen-cast portal asks
which screen or window to share, and PipeWire delivers it. Sound: the default microphone
(FOLIO_REEL_AUDIOSRC overrides the source element, for tests)."""
import ctypes
import datetime
import os

from gi.repository import Gio, GLib, Gst

from . import engine

SECOND = Gst.SECOND


def out_dir():
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS) or os.path.expanduser("~/Videos")
    d = os.path.join(d, "Folio Reel")
    os.makedirs(d, exist_ok=True)
    return d


def new_path(kind, ext):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H.%M.%S")
    return os.path.join(out_dir(), "%s %s.%s" % (kind, stamp, ext))


def is_wayland():
    return bool(os.environ.get("WAYLAND_DISPLAY")) and not os.environ.get("FOLIO_REEL_FORCE_X11")


def audio_source():
    return os.environ.get("FOLIO_REEL_AUDIOSRC") or ("pulsesrc" if Gst.ElementFactory.find("pulsesrc") else "autoaudiosrc")


def cameras():
    """[(name, device path)] of the video capture devices."""
    out = []
    mon = Gst.DeviceMonitor()
    mon.add_filter("Video/Source", None)
    mon.start()
    for dev in mon.get_devices():
        props = dev.get_properties()
        path = props.get_string("device.path") if props else None
        if path or not out:
            out.append((dev.get_display_name(), path))
    mon.stop()
    fake = os.environ.get("FOLIO_REEL_FAKE_CAMERA")
    if fake:
        out.append(("Test Camera", "test"))
    return out


# ------------------------------------------------------------------ X11 windows
def x11_windows():
    """[(xid, title)] of the top-level windows on an X11 display."""
    try:
        x = ctypes.cdll.LoadLibrary("libX11.so.6")
    except OSError:
        return []
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    dpy = x.XOpenDisplay(None)
    if not dpy:
        return []
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
                                     ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                     ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                     ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
    x.XFree.argtypes = [ctypes.c_void_p]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    root = x.XDefaultRootWindow(dpy)

    def prop(win, name, kind):
        atom = x.XInternAtom(dpy, name.encode(), 1)
        if not atom:
            return None
        t, fmt, n, left, data = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        if x.XGetWindowProperty(dpy, win, atom, 0, 65536, 0, 0, ctypes.byref(t), ctypes.byref(fmt), ctypes.byref(n),
                                ctypes.byref(left), ctypes.byref(data)) != 0 or not data.value:
            return None
        try:
            if kind == "windows" and fmt.value == 32:
                return list((ctypes.c_ulong * n.value).from_address(data.value))
            if kind == "text":
                return ctypes.string_at(data.value, n.value * (fmt.value // 8)).decode("utf-8", "replace")
        finally:
            x.XFree(data)
        return None

    wins = prop(root, "_NET_CLIENT_LIST", "windows")
    if wins is None:
        # no window manager (or an old one): the root window's mapped children
        x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                 ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p),
                                 ctypes.POINTER(ctypes.c_uint)]
        r, p, kids, n = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p(), ctypes.c_uint()
        wins = []
        if x.XQueryTree(dpy, root, ctypes.byref(r), ctypes.byref(p), ctypes.byref(kids), ctypes.byref(n)) and kids.value:
            wins = list((ctypes.c_ulong * n.value).from_address(kids.value))
            x.XFree(kids)
    out = []
    for w in wins:
        title = prop(w, "_NET_WM_NAME", "text") or prop(w, "WM_NAME", "text")
        size = window_size(w) if title else None
        if title and size and size[0] >= 80 and size[1] >= 60:     # not hidden helper windows
            out.append((int(w), title))
    x.XCloseDisplay(dpy)
    return out


def window_size(xid):
    try:
        import gi
        gi.require_version("GdkX11", "3.0")
        from gi.repository import Gdk, GdkX11
        w = GdkX11.X11Window.foreign_new_for_display(Gdk.Display.get_default(), int(xid))
        if w is None:
            return None
        if not w.is_viewable() and w.get_state() & Gdk.WindowState.WITHDRAWN:
            return None
        g = w.get_geometry()
        return (g[2], g[3]) if g[2] > 1 and g[3] > 1 else None
    except Exception:       # noqa: BLE001
        return None


# ------------------------------------------------------------------ Wayland: the screen-cast portal
class Portal:
    """org.freedesktop.portal.ScreenCast: ask the desktop for a screen or window, get a PipeWire
    stream. done(fd, node) or failed(message)."""
    def __init__(self, window_only, done, failed):
        self.done, self.failed = done, failed
        self.window_only = window_only
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.proxy = Gio.DBusProxy.new_sync(self.bus, Gio.DBusProxyFlags.NONE, None, "org.freedesktop.portal.Desktop",
                                            "/org/freedesktop/portal/desktop", "org.freedesktop.portal.ScreenCast", None)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.n = 0
        self.session = None

    def _request(self, method, args, then):
        self.n += 1
        token = "folio_reel_%d" % self.n
        path = "/org/freedesktop/portal/desktop/request/%s/%s" % (self.sender, token)
        sub = [None]

        def response(conn, sender, obj, iface, signal, params):
            self.bus.signal_unsubscribe(sub[0])
            code, results = params.unpack()
            if code != 0:
                self.failed("Recording was cancelled." if code == 1 else "The desktop wouldn't share the screen.")
                return
            then(results)
        sub[0] = self.bus.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
                                           "Response", path, None, Gio.DBusSignalFlags.NO_MATCH_RULE, response)
        args = list(args)
        args[-1]["handle_token"] = GLib.Variant("s", token)
        self.proxy.call_sync(method, GLib.Variant(self._sig(method), tuple(args)), Gio.DBusCallFlags.NONE, -1, None)

    @staticmethod
    def _sig(method):
        return {"CreateSession": "(a{sv})", "SelectSources": "(oa{sv})", "Start": "(osa{sv})"}[method]

    def start(self):
        try:
            self._request("CreateSession", [{"session_handle_token": GLib.Variant("s", "folio_reel")}], self._created)
        except GLib.Error as e:
            self.failed("Screen recording isn't available on this desktop (%s)." % e.message)

    def _created(self, results):
        self.session = results["session_handle"]
        self._request("SelectSources", [self.session, {"types": GLib.Variant("u", 2 if self.window_only else 1),
                                                      "cursor_mode": GLib.Variant("u", 2),
                                                      "multiple": GLib.Variant("b", False)}], self._selected)

    def _selected(self, results):
        self._request("Start", [self.session, "", {}], self._started)

    def _started(self, results):
        streams = results.get("streams") or []
        if not streams:
            self.failed("Nothing was chosen to record.")
            return
        node = streams[0][0]
        ret, out_fds = self.proxy.call_with_unix_fd_list_sync(
            "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (self.session, {})), Gio.DBusCallFlags.NONE, -1, None, None)
        fd = out_fds.get(ret.unpack()[0])
        self.done(fd, node)


# ------------------------------------------------------------------ the recorder
class Recorder:
    """kind: 'screen', 'window', 'camera' or 'voice'. on_state(state, info): 'recording',
    ('done', path) or ('error', message)."""
    def __init__(self, kind, on_state, xid=None, device=None, sound=True):
        engine.init()
        self.kind = kind
        self.on_state = on_state
        self.xid = xid
        self.device = device
        self.sound = sound
        self.path = new_path({"screen": "Screen Recording", "window": "Window Recording", "camera": "Camera Recording",
                              "voice": "Voice-over"}[kind], "wav" if kind == "voice" else "mp4")
        self.pipeline = None
        self.started = None
        self._stopping = False

    def start(self):
        if self.kind in ("screen", "window") and is_wayland():
            Portal(self.kind == "window", self._from_portal, lambda msg: self.on_state("error", msg)).start()
            return
        if self.kind == "screen":
            src = "ximagesrc use-damage=false show-pointer=true"
        elif self.kind == "window":
            src = "ximagesrc use-damage=false show-pointer=true xid=%d" % int(self.xid)
            size = window_size(self.xid)
            if size:
                # H.264 wants even sizes; a window can be any size
                src += " ! videoconvert ! videoscale ! video/x-raw,width=%d,height=%d" % (size[0] // 2 * 2, size[1] // 2 * 2)
        elif self.kind == "camera":
            src = "videotestsrc is-live=true pattern=ball" if self.device == "test" else \
                ("v4l2src device=\"%s\"" % self.device if self.device else "v4l2src")
        else:
            src = None
        self._launch(src)

    def _from_portal(self, fd, node):
        self._launch("pipewiresrc fd=%d path=%d do-timestamp=true keepalive-time=1000 always-copy=true" % (fd, node))

    def _launch(self, vsrc):
        loc = self.path.replace("\\", "\\\\").replace('"', '\\"')
        if self.kind == "voice":
            desc = ("%s ! queue ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 "
                    "! wavenc ! filesink location=\"%s\"" % (audio_source(), loc))
        else:
            aac = "avenc_aac" if Gst.ElementFactory.find("avenc_aac") else "voaacenc"
            desc = ("%s ! queue ! videoconvert ! videorate ! video/x-raw,framerate=30/1 "
                    "! x264enc speed-preset=ultrafast tune=zerolatency key-int-max=60 ! h264parse ! queue "
                    "! mp4mux name=mux ! filesink location=\"%s\"" % (vsrc, loc))
            if self.sound:
                desc += (" %s ! queue ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=2 ! %s ! queue ! mux."
                         % (audio_source(), aac))
        try:
            self.pipeline = Gst.parse_launch(desc)
        except GLib.Error as e:
            self.on_state("error", "Can't record: %s" % e.message)
            return
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._message)
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self._fail("Recording couldn't start.")
            return
        self.started = GLib.get_monotonic_time()
        self.on_state("recording", None)

    def elapsed(self):
        return 0.0 if self.started is None else (GLib.get_monotonic_time() - self.started) / 1e6

    def stop(self):
        """Finish the file properly (the muxer writes its index on end-of-stream)."""
        if self.pipeline is None or self._stopping:
            return
        self._stopping = True
        self.pipeline.send_event(Gst.Event.new_eos())
        GLib.timeout_add_seconds(8, self._force_end)

    def cancel(self):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        try:
            os.remove(self.path)
        except OSError:
            pass

    def _force_end(self):
        if self.pipeline is not None:
            self._finish()
        return False

    def _fail(self, msg):
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.on_state("error", msg)

    def _finish(self):
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.on_state("done", self.path)

    def _message(self, bus, msg):
        if self.pipeline is None:
            return
        if msg.type == Gst.MessageType.EOS:
            self._finish()
        elif msg.type == Gst.MessageType.ERROR:
            err, _dbg = msg.parse_error()
            self._fail("Recording stopped: %s" % err.message)
