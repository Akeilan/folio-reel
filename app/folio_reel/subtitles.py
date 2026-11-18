"""Subtitles (R4-03): SRT files in and out, and the caption clips they become.

A subtitle is a caption clip on the Titles track — the same thing Insert > Caption makes — so it
is trimmed, moved and styled like everything else on the timeline, and it is burned into the
picture on export. Export writes the captions back out as an .srt, which is what a video site or
a player wants beside the file."""
import re


def fmt_time(t):
    """SRT writes 00:00:01,250."""
    t = max(0.0, float(t))
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def parse_time(text):
    """00:00:01,250 or 00:00:01.250 (some writers use a stop) in seconds, or None. The
    milliseconds can be left off: 00:00:06 is six seconds (R9-25)."""
    m = re.match(r"\s*(\d+):([0-5]?\d):([0-5]?\d)(?:[,.](\d{1,3}))?\s*$", text or "")
    if not m:
        m = re.match(r"\s*(\d+):([0-5]?\d)[,.](\d{1,3})\s*$", text or "")
        if not m:
            return None
        mm, ss, ms = m.groups()
        return int(mm) * 60 + int(ss) + int(ms.ljust(3, "0")) / 1000.0
    h, mm, ss, ms = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + int((ms or "0").ljust(3, "0")) / 1000.0


def decode(raw):
    """The text of a subtitle file. UTF-8 when it is that; otherwise the Windows encoding most
    older .srt files were saved in, which used to come in as “Caf� na�ve” (R9-25)."""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8-sig", "utf-16"):
        try:
            if enc == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    try:
        return raw.decode("cp1252")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


TAG = re.compile(r"</?(?:i|b|u|s|font|c|v)(?:\s[^<>]*)?>|\{\\[^{}]*\}", re.I)


def plain(words):
    """Subtitle text without its styling tags (<i>, <font color=…>, {\\an8}): captions are styled
    in Clip Settings, and the tags used to show as text."""
    return TAG.sub("", words)


def parse(text, skipped=None):
    """An .srt as [(start, end, words)], in time order. Numbering and blank lines are forgiven;
    a block without a readable time line is skipped, and listed in `skipped` when one is given."""
    out = []
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    for block in re.split(r"\n\s*\n", text):
        lines = [l for l in block.split("\n") if l.strip() != ""]
        if not lines:
            continue
        if lines[0].strip().isdigit() and len(lines) > 1:
            lines = lines[1:]
        times = lines[0].split("-->")
        if len(times) != 2:
            if skipped is not None and len(lines) > 1:
                skipped.append(lines[0])
            continue
        a, b = parse_time(times[0]), parse_time(times[1].split()[0] if times[1].split() else "")
        if a is None or b is None:
            if skipped is not None:
                skipped.append(lines[0])
            continue
        words = plain("\n".join(lines[1:])).strip()
        if not words:
            continue
        out.append((a, max(a + 0.1, b), words))
    out.sort(key=lambda x: x[0])
    return out


def write(entries):
    """Those entries as the text of an .srt file."""
    parts = []
    for i, (a, b, words) in enumerate(entries, 1):
        parts.append("%d\n%s --> %s\n%s\n" % (i, fmt_time(a), fmt_time(b), words.strip()))
    return "\n".join(parts)


def from_clips(clips):
    """The caption clips of a project as subtitle entries."""
    caps = sorted([c for c in clips if c.get("kind") == "caption"], key=lambda c: c["start"])
    return [(c["start"], c["start"] + c["duration"], c.get("text", "")) for c in caps if (c.get("text") or "").strip()]
