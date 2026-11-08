"""A Reel project: the media bin and four tracks of clips (R3-01), saved as JSON (.reel).

Times are seconds (floats). Every edit goes through Project's methods, which keep the tracks in
order and record undo steps.

  Tracks (top to bottom in the picture):  titles (overlay), video, audio, music
  A clip:  {"id", "kind": media|title|lower-third|caption, "media": uri, "name", "start",
            "inpoint", "duration" (on the timeline), "speed", "volume", "fade_in", "fade_out",
            "color": {brightness, contrast, saturation, hue}, "crop": {l, r, t, b} (fractions),
            "zoom", "panzoom": None|"in"|"out"|"left"|"right", "transition": None|{type, duration},
            "music_bed", "keyframes": [[t, level], ...], text, font, text_color, bg_color, ...}
"""
import copy
import json
import os
import time

TRACKS = ["titles", "video", "audio", "music"]
TRACK_NAMES = {"titles": "Titles", "video": "Video", "audio": "Audio", "music": "Music"}
IMAGE_SECONDS = 5.0
TITLE_SECONDS = 4.0
TRANSITIONS = [("crossfade", "Crossfade"), ("dip-black", "Fade to Black"), ("wipe-right", "Wipe Right"),
               ("wipe-left", "Wipe Left"), ("wipe-down", "Wipe Down"), ("wipe-up", "Wipe Up"),
               ("box", "Box"), ("clock", "Clock"), ("iris", "Iris")]
PRESETS = {"720p": (1280, 720), "1080p": (1920, 1080), "4k": (3840, 2160)}
# Named export presets (R4-08): what it is called, the format, and the size.
EXPORT_PRESETS = [
    ("Full HD video (MP4, 1080p)", "mp4", "1080p"),
    ("4K video (MP4)", "mp4", "4k"),
    ("Smaller file (MP4, 720p)", "mp4", "720p"),
    ("For the web (WebM, 1080p)", "webm", "1080p"),
    ("For the web, smaller (WebM, 720p)", "webm", "720p"),
]
EPS = 1e-6


def new_project(width=1920, height=1080, fps=30):
    return {"version": 1, "width": width, "height": height, "fps": fps, "media": [],
            "tracks": {t: [] for t in TRACKS}, "markers": [], "next_id": 1}


MARKER_COLORS = [("yellow", "Yellow"), ("red", "Red"), ("green", "Green"), ("blue", "Blue"),
                 ("purple", "Purple"), ("white", "White")]
MARKER_RGB = {"yellow": (0.98, 0.78, 0.10), "red": (0.85, 0.20, 0.18), "green": (0.22, 0.70, 0.30),
              "blue": (0.20, 0.52, 0.90), "purple": (0.60, 0.35, 0.85), "white": (0.95, 0.95, 0.95)}


def clip_defaults():
    return {"speed": 1.0, "volume": 1.0, "fade_in": 0.0, "fade_out": 0.0,
            "color": {"brightness": 0.0, "contrast": 1.0, "saturation": 1.0, "hue": 0.0},
            "crop": {"l": 0.0, "r": 0.0, "t": 0.0, "b": 0.0}, "zoom": 1.0, "panzoom": None,
            "transition": None, "music_bed": False, "keyframes": [], "muted": False,
            "chroma": False, "chroma_color": "green", "chroma_tolerance": 20.0,
            "chroma_softness": 2.0, "chroma_edges": 100,
            "steady": False, "steady_amount": 5, "lens": 0.0}


def end_of(c):
    return c["start"] + c["duration"]


class EditError(Exception):
    """An edit that can't be made (the message says why)."""


class Project:
    def __init__(self, data=None, path=None):
        self.data = data or new_project()
        for t in TRACKS:
            self.data["tracks"].setdefault(t, [])
        self.data.setdefault("markers", [])      # R4-05: older projects have none
        self.path = path
        self.undo_stack = []
        self.redo_stack = []
        self.listeners = []
        self.dirty = False
        self.snapping = True

    # ------------------------------------------------------------ change notification and undo
    def listen(self, fn):
        self.listeners.append(fn)

    def _changed(self, what="timeline"):
        self.dirty = True
        for fn in list(self.listeners):
            fn(what)

    def checkpoint(self, label="", merge=None):
        """Before an edit: remember how things were, for Undo. merge: a key; another change with the
        same key straight after (a slider being dragged) joins this undo step."""
        now = time.monotonic()
        last = getattr(self, "_merge", None)
        self._merge = (merge, now) if merge is not None else None
        if merge is not None and last and last[0] == merge and now - last[1] < 1.5 and self.undo_stack:
            self.redo_stack.clear()
            return
        self.undo_stack.append((label, copy.deepcopy(self.data)))
        if len(self.undo_stack) > 200:
            self.undo_stack.pop(0)
        self.redo_stack.clear()

    def can_undo(self):
        return bool(self.undo_stack)

    def can_redo(self):
        return bool(self.redo_stack)

    def undo_label(self):
        return self.undo_stack[-1][0] if self.undo_stack else None

    def redo_label(self):
        return self.redo_stack[-1][0] if self.redo_stack else None

    def undo(self):
        self._merge = None
        if not self.undo_stack:
            return None
        label, data = self.undo_stack.pop()
        self.redo_stack.append((label, copy.deepcopy(self.data)))
        self.data = data
        self._changed("all")
        return label

    def redo(self):
        self._merge = None
        if not self.redo_stack:
            return None
        label, data = self.redo_stack.pop()
        self.undo_stack.append((label, copy.deepcopy(self.data)))
        self.data = data
        self._changed("all")
        return label

    # ------------------------------------------------------------ settings
    @property
    def width(self):
        return self.data["width"]

    @property
    def height(self):
        return self.data["height"]

    @property
    def fps(self):
        return self.data["fps"]

    def set_size(self, width, height, fps=None):
        self.checkpoint("Project Size")
        self.data["width"], self.data["height"] = int(width), int(height)
        if fps:
            self.data["fps"] = fps
        self._changed()

    # ------------------------------------------------------------ media bin
    @property
    def media(self):
        return self.data["media"]

    def media_by_uri(self, uri):
        for m in self.data["media"]:
            if m["uri"] == uri:
                return m
        return None

    def add_media(self, info):
        """info: {"uri", "name", "duration", "has_video", "has_audio", "is_image", "width", "height"}"""
        old = self.media_by_uri(info["uri"])
        if old:
            return old
        self.checkpoint("Import Media")
        self.data["media"].append(dict(info))
        self._changed("media")
        return info

    def remove_media(self, uri):
        used = [c for c in self.all_clips() if c.get("media") == uri]
        if used:
            raise EditError("“%s” is used in the timeline: remove those clips first." % self.media_by_uri(uri)["name"])
        self.checkpoint("Remove Media")
        self.data["media"] = [m for m in self.data["media"] if m["uri"] != uri]
        self._changed("media")

    # ------------------------------------------------------------ looking things up
    def track(self, name):
        return self.data["tracks"][name]

    def all_clips(self):
        for t in TRACKS:
            for c in self.data["tracks"][t]:
                yield c

    def find(self, cid):
        for t in TRACKS:
            for c in self.data["tracks"][t]:
                if c["id"] == cid:
                    return t, c
        return None, None

    def clip(self, cid):
        return self.find(cid)[1]

    def duration(self):
        return max([end_of(c) for c in self.all_clips()] + [0.0])

    def clips_at(self, t):
        return [c for c in self.all_clips() if c["start"] - EPS <= t < end_of(c) - EPS]

    def _sort(self, track):
        self.data["tracks"][track].sort(key=lambda c: (c["start"], c["id"]))

    def neighbours(self, cid):
        """(previous clip, next clip) on the same track."""
        track, c = self.find(cid)
        if c is None:
            return None, None
        lst = self.data["tracks"][track]
        i = lst.index(c)
        return (lst[i - 1] if i > 0 else None), (lst[i + 1] if i + 1 < len(lst) else None)

    def snap_points(self, exclude=()):
        pts = {0.0}
        for c in self.all_clips():
            if c["id"] in exclude:
                continue
            pts.add(c["start"])
            pts.add(end_of(c))
        for m in self.data.get("markers", []):      # clips snap to markers as well (R4-05)
            pts.add(m["t"])
        return sorted(pts)

    def snap(self, t, tolerance, exclude=(), extra=()):
        """t moved to the nearest clip edge (or extra point, e.g. the playhead) within tolerance."""
        if not self.snapping:
            return t
        best, dist = t, tolerance
        for p in list(self.snap_points(exclude)) + list(extra):
            if abs(p - t) <= dist:
                best, dist = p, abs(p - t)
        return best

    # ------------------------------------------------------------ groups of clips (R4-06)
    def group_of(self, cid):
        """The group a clip belongs to, or None."""
        _t, c = self.find(cid)
        return (c or {}).get("group") or None

    def group_members(self, gid):
        """Every clip in a group, earliest first."""
        if not gid:
            return []
        return sorted([c for c in self.all_clips() if c.get("group") == gid], key=lambda c: c["start"])

    def expand_groups(self, ids):
        """The given clips, plus everything grouped with them (R4-06)."""
        out = list(ids)
        gids = {self.group_of(i) for i in ids} - {None}
        for g in gids:
            for c in self.group_members(g):
                if c["id"] not in out:
                    out.append(c["id"])
        return out

    def group(self, ids):
        """Make the clips one group, which moves and trims as a single clip. Returns the group id."""
        clips = [c for c in self.all_clips() if c["id"] in ids]
        if len(clips) < 2:
            raise EditError("Pick two or more clips to group.")
        self.checkpoint("Group")
        gid = self._new_id()
        for c in clips:
            c["group"] = gid
        self._changed()
        return gid

    def ungroup(self, ids):
        """Break up every group the given clips are in. Returns how many clips were freed."""
        gids = {self.group_of(i) for i in ids} - {None}
        if not gids:
            raise EditError("Those clips aren't grouped.")
        self.checkpoint("Ungroup")
        n = 0
        for c in self.all_clips():
            if c.get("group") in gids:
                c.pop("group", None)
                n += 1
        self._changed()
        return n

    def move_group(self, gid, delta, tolerance=0.0, playhead=None):
        """Slide a whole group along the timeline. Nothing moves unless every clip in it can."""
        members = self.group_members(gid)
        if not members:
            raise EditError("no such group")
        first = members[0]
        start = max(0.0, first["start"] + delta)
        if tolerance:
            ids = [c["id"] for c in members]
            last_end = max(end_of(c) for c in members)
            extra = [playhead] if playhead is not None else []
            s1 = self.snap(start, tolerance, exclude=ids, extra=extra)
            s2 = self.snap(start + (last_end - first["start"]), tolerance, exclude=ids, extra=extra) - (last_end - first["start"])
            moved = [s for s in (s1, s2) if abs(s - start) > 1e-9]
            if moved:
                start = min(moved, key=lambda s: abs(s - start))
        delta = start - first["start"]
        if abs(delta) < EPS:
            return 0.0
        ids = {c["id"] for c in members}
        for c in members:
            at = c["start"] + delta
            if at < -EPS:
                raise EditError("The group would run off the start of the timeline.")
            track = self.find(c["id"])[0]
            for x in self.data["tracks"][track]:
                if x["id"] in ids:
                    continue
                if not (end_of(x) <= at + EPS or x["start"] >= at + c["duration"] - EPS):
                    raise EditError("Something is in the way of the group there.")
        self.checkpoint("Move group")
        for c in members:
            c["start"] = max(0.0, c["start"] + delta)
        for t in TRACKS:
            self._sort(t)
        self._changed()
        return delta

    # ------------------------------------------------------------ markers (R4-05)
    def markers(self):
        """The markers, earliest first."""
        return sorted(self.data.get("markers", []), key=lambda m: m["t"])

    def marker(self, mid):
        for m in self.data.get("markers", []):
            if m["id"] == mid:
                return m
        return None

    def marker_at(self, t, tolerance=0.0):
        """The marker nearest t within tolerance, or None."""
        best, dist = None, tolerance
        for m in self.markers():
            d = abs(m["t"] - t)
            if d <= dist:
                best, dist = m, d
        return best

    def add_marker(self, t, name="", color="yellow"):
        """Put a marker at t. A marker already there is renamed rather than doubled up."""
        t = max(0.0, float(t))
        here = self.marker_at(t, EPS)
        if here is not None:
            if name:
                self.set_marker(here["id"], name=name, color=color)
            return here["id"]
        self.checkpoint("Add marker")
        m = {"id": self._new_id(), "t": t, "name": name, "color": color if color in MARKER_RGB else "yellow"}
        self.data.setdefault("markers", []).append(m)
        self._changed()
        return m["id"]

    def set_marker(self, mid, label="Change marker", **props):
        m = self.marker(mid)
        if m is None:
            return False
        if all(m.get(k) == v for k, v in props.items()):
            return True
        self.checkpoint(label)
        for k, v in props.items():
            if k == "t":
                v = max(0.0, float(v))
            m[k] = v
        self._changed()
        return True

    def remove_markers(self, ids):
        ids = [i for i in ids if self.marker(i) is not None]
        if not ids:
            return 0
        self.checkpoint("Delete marker" if len(ids) == 1 else "Delete markers")
        self.data["markers"] = [m for m in self.data.get("markers", []) if m["id"] not in ids]
        self._changed()
        return len(ids)

    def clear_markers(self):
        return self.remove_markers([m["id"] for m in self.markers()])

    def next_marker(self, t):
        """The first marker after t, or None."""
        for m in self.markers():
            if m["t"] > t + EPS:
                return m
        return None

    def prev_marker(self, t):
        for m in reversed(self.markers()):
            if m["t"] < t - EPS:
                return m
        return None

    # ------------------------------------------------------------ making clips
    def _new_id(self):
        n = self.data["next_id"]
        self.data["next_id"] = n + 1
        return n

    def _media_clip(self, m):
        c = {"id": self._new_id(), "kind": "media", "media": m["uri"], "name": m["name"], "start": 0.0,
             "inpoint": 0.0, "duration": IMAGE_SECONDS if m.get("is_image") else max(0.04, float(m["duration"]))}
        c.update(clip_defaults())
        return c

    def _text_clip(self, kind, text):
        c = {"id": self._new_id(), "kind": kind, "name": text.split("\n")[0][:40] or kind.title(), "start": 0.0,
             "inpoint": 0.0, "duration": TITLE_SECONDS, "text": text}
        c.update(clip_defaults())
        if kind == "title":
            c.update({"font": "Sans Bold 64", "text_color": "#ffffffff", "bg_color": "#ff000000",
                      "halign": "center", "valign": "center"})
        elif kind == "lower-third":
            c.update({"font": "Sans Bold 36", "text_color": "#ffffffff", "bg_color": "#c0101828",
                      "halign": "left", "valign": "bottom"})
        else:   # caption
            c.update({"font": "Sans 30", "text_color": "#ffffffff", "bg_color": "#a0000000",
                      "halign": "center", "valign": "bottom"})
        return c

    def media_kind_track(self, m):
        """Where a piece of media goes by default."""
        if m.get("has_video") or m.get("is_image"):
            return "video"
        return "audio"

    def max_duration(self, c):
        """How long a clip can be on the timeline (media length after its in point, at its speed)."""
        if c["kind"] != "media":
            return float("inf")
        m = self.media_by_uri(c["media"])
        if m is None or m.get("is_image"):
            return float("inf")
        return max(0.04, (float(m["duration"]) - c["inpoint"]) / c.get("speed", 1.0))

    def _make_room(self, track, at, length, exclude=None):
        """Insert edit: every clip on the track starting at or after `at` moves later by `length`;
        a clip running across `at` is split there first (its second half moves too)."""
        lst = self.data["tracks"][track]
        for c in list(lst):
            if c is exclude:
                continue
            if c["start"] < at - EPS < end_of(c) - 2 * EPS and at - c["start"] > EPS:
                self._split(track, c, at)
        for c in lst:
            if c is not exclude and c["start"] >= at - EPS:
                c["start"] += length
        self._sort(track)

    def _first_free(self, track, at, length):
        """The first start at or after `at` where `length` fits on the track."""
        t = at
        for c in sorted(self.data["tracks"][track], key=lambda x: x["start"]):
            if end_of(c) <= t + EPS:
                continue
            if c["start"] >= t + length - EPS:
                break
            t = end_of(c)
        return t

    def add_clip(self, track, source, at=None, insert=False, text=None):
        """source: a media entry (dict with uri) or a text kind ('title', 'lower-third', 'caption').
        at=None: after the last clip on the track. insert=True: clips from `at` on move later."""
        if track not in TRACKS:
            raise EditError("there's no %s track" % track)
        if isinstance(source, dict):
            if track == "titles" and not (source.get("has_video") or source.get("is_image")):
                raise EditError("The Titles track is for pictures, video and titles.")
            if track in ("audio", "music") and not source.get("has_audio"):
                raise EditError("“%s” has no sound to put on the %s track." % (source["name"], TRACK_NAMES[track]))
        self.checkpoint("Add Clip")
        if isinstance(source, dict):
            c = self._media_clip(source)
        else:
            c = self._text_clip(source, text or {"title": "Title", "lower-third": "Name\nRole",
                                                  "caption": "Caption"}.get(source, ""))
        lst = self.data["tracks"][track]
        if at is None:
            at = max([end_of(x) for x in lst] + [0.0])
        at = max(0.0, at)
        if insert:
            self._make_room(track, at, c["duration"])
        else:
            at = self._first_free(track, at, c["duration"])
        c["start"] = at
        lst.append(c)
        self._sort(track)
        self._changed()
        return c

    def add_subtitles(self, entries):
        """Subtitles (R4-03) as caption clips on the Titles track, each at its own time. Captions
        already there are left alone; overlapping ones are moved along as any clip would be."""
        if not entries:
            return []
        self.checkpoint("Import Subtitles")
        made = []
        for start, end, words in entries:
            c = self._text_clip("caption", words)
            c["start"] = max(0.0, float(start))
            c["duration"] = max(0.1, float(end) - float(start))
            c["start"] = self._first_free("titles", c["start"], c["duration"])
            self.data["tracks"]["titles"].append(c)
            self._sort("titles")
            made.append(c)
        self._changed()
        return made

    # ------------------------------------------------------------ editing
    def _split(self, track, c, t):
        b = copy.deepcopy(c)
        b["id"] = self._new_id()
        off = t - c["start"]
        c["duration"] = off
        b["start"] = t
        b["duration"] -= off
        b["inpoint"] = c["inpoint"] + off * c.get("speed", 1.0) if c["kind"] == "media" else 0.0
        b["transition"] = None
        b["fade_in"] = 0.0
        c["fade_out"] = 0.0
        b["keyframes"] = [[k - off, v] for k, v in c.get("keyframes", []) if k >= off]
        c["keyframes"] = [[k, v] for k, v in c.get("keyframes", []) if k < off]
        self.data["tracks"][track].append(b)
        self._sort(track)
        return b

    def split(self, cid, t):
        """Split at time t (R3-01). Returns the new (second) clip."""
        track, c = self.find(cid)
        if c is None:
            raise EditError("no such clip")
        if not (c["start"] + 0.04 <= t <= end_of(c) - 0.04):
            raise EditError("The playhead isn't over that clip.")
        self.checkpoint("Split")
        b = self._split(track, c, t)
        self._changed()
        return b

    def split_at(self, t, ids=None):
        """Split every clip under time t (or just the given ones)."""
        hit = [c for c in self.clips_at(t) if (ids is None or c["id"] in ids)
               and c["start"] + 0.04 <= t <= end_of(c) - 0.04]
        if not hit:
            raise EditError("There's no clip under the playhead to split.")
        self.checkpoint("Split")
        out = []
        for c in hit:
            out.append(self._split(self.find(c["id"])[0], c, t))
        self._changed()
        return out

    def delete(self, ids, ripple=False):
        """Delete clips; ripple=True closes the gap they leave (R3-01 ripple delete)."""
        if not ids:
            return
        self.checkpoint("Ripple Delete" if ripple else "Delete")
        for cid in ids:
            track, c = self.find(cid)
            if c is None:
                continue
            lst = self.data["tracks"][track]
            nxt = self.neighbours(cid)[1]
            lst.remove(c)
            if nxt is not None and nxt.get("transition"):
                nxt["transition"] = None
            if ripple:
                gap = c["duration"]
                for x in lst:
                    if x["start"] >= c["start"] - EPS:
                        x["start"] = max(0.0, x["start"] - gap)
                self._sort(track)
        self._changed()

    def move(self, cid, start, track=None, tolerance=0.0, playhead=None):
        """Move a clip (optionally to another track). It snaps to clip edges and the playhead, and
        never lands on top of another clip: it goes to the nearest free place instead."""
        old_track, c = self.find(cid)
        if c is None:
            raise EditError("no such clip")
        track = track or old_track
        if track != old_track:
            if c["kind"] != "media" and track != "titles":
                raise EditError("Titles stay on the Titles track.")
            if c["kind"] == "media":
                m = self.media_by_uri(c["media"])
                if track in ("audio", "music") and not m.get("has_audio"):
                    raise EditError("That clip has no sound.")
                if track in ("video", "titles") and not (m.get("has_video") or m.get("is_image")):
                    raise EditError("That clip has no picture.")
        self.checkpoint("Move")
        start = max(0.0, start)
        if tolerance:
            extra = [playhead] if playhead is not None else []
            s1 = self.snap(start, tolerance, exclude=(cid,), extra=extra)
            s2 = self.snap(start + c["duration"], tolerance, exclude=(cid,), extra=extra) - c["duration"]
            moved = [s for s in (s1, s2) if abs(s - start) > 1e-9]   # only an edge that snapped counts
            if moved:
                start = min(moved, key=lambda s: abs(s - start))
        self.data["tracks"][old_track].remove(c)
        c["transition"] = None
        lst = self.data["tracks"][track]
        # the nearest free place: where it was dropped, else just after or before what's there
        def free(at):
            return all(end_of(x) <= at + EPS or x["start"] >= at + c["duration"] - EPS for x in lst)
        if not free(start):
            cands = [end_of(x) for x in lst] + [x["start"] - c["duration"] for x in lst]
            cands = [p for p in cands if p >= -EPS and free(max(0.0, p))]
            if not cands:
                cands = [max([end_of(x) for x in lst] + [0.0])]
            start = min(cands, key=lambda p: abs(p - start))
        c["start"] = max(0.0, start)
        lst.append(c)
        self._sort(track)
        self._changed()
        return c

    def paste(self, items, at):
        """Copied clips back on their tracks from time `at`, keeping their spacing; each goes to
        the first free place. items: [{"track", "clip", "offset", "media"}]. Returns the new clips."""
        if not items:
            return []
        self.checkpoint("Paste")
        out = []
        regroup = {}       # a pasted group is a group of its own, not the one copied from (R4-06)
        for it in sorted(items, key=lambda x: x["offset"]):
            c = copy.deepcopy(it["clip"])
            if c.get("group"):
                c["group"] = regroup.setdefault(c["group"], self._new_id())
            if c["kind"] == "media" and self.media_by_uri(c["media"]) is None:
                if not it.get("media"):
                    continue
                self.data["media"].append(copy.deepcopy(it["media"]))
            c["id"] = self._new_id()
            c["transition"] = None
            track = it["track"]
            c["start"] = self._first_free(track, max(0.0, at + it["offset"]), c["duration"])
            self.data["tracks"][track].append(c)
            self._sort(track)
            out.append(c)
        self._changed("all" if any(it.get("media") for it in items) else "timeline")
        return out

    def trim(self, cid, edge, t, tolerance=0.0, playhead=None):
        """Drag a clip's start or end edge to time t (R3-01 trim). The media's own length and the
        neighbouring clips are the limits."""
        track, c = self.find(cid)
        if c is None:
            raise EditError("no such clip")
        if tolerance:
            t = self.snap(t, tolerance, exclude=(cid,), extra=[playhead] if playhead is not None else [])
        prev, nxt = self.neighbours(cid)
        self.checkpoint("Trim")
        sp = c.get("speed", 1.0)
        if edge == "start":
            lo = end_of(prev) - (c["transition"]["duration"] if c.get("transition") else 0) if prev else 0.0
            if c["kind"] == "media" and not self.media_by_uri(c["media"]).get("is_image"):
                lo = max(lo, c["start"] - c["inpoint"] / sp)
            t = min(max(t, lo), end_of(c) - 0.1)
            delta = t - c["start"]
            if c["kind"] == "media":
                c["inpoint"] = max(0.0, c["inpoint"] + delta * sp)
            c["start"] = t
            c["duration"] -= delta
        else:
            hi = nxt["start"] + (nxt["transition"]["duration"] if nxt and nxt.get("transition") else 0) if nxt else float("inf")
            hi = min(hi, c["start"] + self.max_duration(c))
            t = max(min(t, hi), c["start"] + 0.1)
            c["duration"] = t - c["start"]
        c["fade_in"] = min(c["fade_in"], c["duration"])
        c["fade_out"] = min(c["fade_out"], c["duration"])
        self._sort(track)
        self._changed()
        return c

    def trim_to_playhead(self, cid, t, edge):
        """Ribbon Trim Start / Trim End: the clip's start (or end) moves to the playhead."""
        return self.trim(cid, edge, t)

    def set(self, cid, label="Change", merge=False, **props):
        """Change clip properties (volume, fade_in, color, text, ...). merge=True: repeated changes
        of the same properties (a slider) are one undo step."""
        track, c = self.find(cid)
        if c is None:
            raise EditError("no such clip")
        self.checkpoint(label, merge=(cid, tuple(sorted(props))) if merge else None)
        for k, v in props.items():
            if isinstance(v, dict) and isinstance(c.get(k), dict):
                c[k] = dict(c[k], **v)
            else:
                c[k] = v
        if "fade_in" in props or "fade_out" in props:
            c["fade_in"] = max(0.0, min(c["fade_in"], c["duration"]))
            c["fade_out"] = max(0.0, min(c["fade_out"], c["duration"]))
        if c["kind"] != "media" and "text" in props:
            c["name"] = props["text"].split("\n")[0][:40] or c["name"]
        self._changed("props")
        return c

    def set_speed(self, cid, speed):
        """Speed (R3-03): 0.25× to 4×. The clip gets shorter or longer on the timeline; clips after it
        on the track move to keep the cut where it was."""
        track, c = self.find(cid)
        if c is None or c["kind"] != "media":
            raise EditError("Speed is for video and sound clips.")
        speed = max(0.25, min(4.0, float(speed)))
        self.checkpoint("Speed")
        m = self.media_by_uri(c["media"])
        span = c["duration"] * c["speed"]                # how much of the media the clip shows
        if not m.get("is_image"):
            span = min(span, float(m["duration"]) - c["inpoint"])
        new = span / speed
        delta = new - c["duration"]
        old_end = end_of(c)
        c["speed"] = speed
        c["duration"] = new
        for x in self.data["tracks"][track]:
            if x is not c and x["start"] >= old_end - EPS:
                x["start"] += delta
        self._sort(track)
        self._changed()
        return c

    def set_transition(self, cid, kind, duration=1.0):
        """A transition into this clip from the one before it on the track (R3-03). Crossfades and
        wipes overlap the two clips (this clip and everything after it move earlier); Fade to Black
        fades the first out and the second in."""
        track, c = self.find(cid)
        prev = self.neighbours(cid)[0] if c else None
        if c is None or prev is None:
            raise EditError("A transition goes between two clips: pick the second one.")
        if track not in ("video", "titles"):
            raise EditError("Transitions are for the Video and Titles tracks; on sound, use fades.")
        self.checkpoint("Transition")
        old = c.get("transition")
        shift = old["duration"] if old and old["type"] != "dip-black" else 0.0
        if kind in (None, "none"):
            new_shift = 0.0
            c["transition"] = None
        else:
            gap = c["start"] - end_of(prev)
            if gap > 0.05 and kind != "dip-black":
                raise EditError("The two clips must touch for a transition: close the gap first.")
            duration = max(0.1, min(float(duration), c["duration"] / 2, prev["duration"] / 2 + shift))
            new_shift = duration if kind != "dip-black" else 0.0
            c["transition"] = {"type": kind, "duration": duration}
        delta = shift - new_shift
        if abs(delta) > EPS:
            for x in self.data["tracks"][track]:
                if x["start"] >= c["start"] - EPS:
                    x["start"] += delta
        self._sort(track)
        self._changed()
        return c

    def set_keyframes(self, cid, points):
        """Volume points [(time in the clip, level 0..2), ...] (R3-05)."""
        return self.set(cid, label="Volume Points", keyframes=sorted([[float(t), float(v)] for t, v in points]))

    # ------------------------------------------------------------ the music bed (R3-05)
    def duck_points(self, music, level=0.3, ramp=0.4):
        """Where the music dips: under every clip on the Audio track (speech, voice-over).
        Returns [(t in the clip, gain)]."""
        speech = []
        for x in self.data["tracks"]["audio"]:
            if not x.get("muted"):
                speech.append((x["start"], end_of(x)))
        speech.sort()
        merged = []
        for a, b in speech:
            if merged and a <= merged[-1][1] + ramp * 2:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        s, e = music["start"], end_of(music)
        pts = [(0.0, 1.0)]
        for a, b in merged:
            if b <= s or a >= e:
                continue
            for t, g in ((a - ramp, 1.0), (a, level), (b, level), (b + ramp, 1.0)):
                if s - EPS <= t <= e + EPS:
                    pts.append((t - s, g))
                elif t < s and g == level:
                    pts.append((0.0, level))
        pts.sort()
        return pts

    # ------------------------------------------------------------ files
    def to_json(self):
        d = copy.deepcopy(self.data)
        if self.path:
            base = os.path.dirname(os.path.abspath(self.path))
            for m in d["media"]:
                p = uri_to_path(m["uri"])
                if p:
                    try:
                        m["relative"] = os.path.relpath(p, base)
                    except ValueError:
                        pass
        return json.dumps(d, indent=1)

    def save(self, path=None):
        path = path or self.path
        if not path:
            raise EditError("no file name")
        self.path = path
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        os.replace(tmp, path)
        self.dirty = False

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "tracks" not in data:
            raise EditError("That isn't a Folio Reel project.")
        base = os.path.dirname(os.path.abspath(path))
        uri_map = {}
        for m in data.get("media", []):
            # media moved along with the project (e.g. a folder copied to another computer)
            p = uri_to_path(m["uri"])
            rel = m.pop("relative", None)
            if p and not os.path.exists(p) and rel and os.path.exists(os.path.join(base, rel)):
                new = path_to_uri(os.path.normpath(os.path.join(base, rel)))
                uri_map[m["uri"]] = new
                m["uri"] = new
        for t in data["tracks"].values():
            for c in t:
                if c.get("media") in uri_map:
                    c["media"] = uri_map[c["media"]]
                for k, v in clip_defaults().items():
                    c.setdefault(k, copy.deepcopy(v))
        p = cls(data, path)
        return p

    def missing_media(self):
        return [m for m in self.data["media"] if uri_to_path(m["uri"]) and not os.path.exists(uri_to_path(m["uri"]))]


def uri_to_path(uri):
    if uri.startswith("file://"):
        from urllib.parse import unquote, urlparse
        return unquote(urlparse(uri).path)
    return None


def path_to_uri(path):
    from urllib.parse import quote
    return "file://" + quote(os.path.abspath(path))


def fmt_time(secs, frames_fps=None):
    secs = max(0.0, secs)
    if frames_fps:
        total = int(round(secs * frames_fps))
        f = total % frames_fps
        s = total // frames_fps
        return "%d:%02d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60, f)
    s = int(secs)
    if s >= 3600:
        return "%d:%02d:%02d" % (s // 3600, (s // 60) % 60, s % 60)
    return "%d:%02d.%d" % (s // 60, s % 60, int((secs - s) * 10))
