"""Recovery copies: while a project has unsaved changes Reel keeps a copy of it, so a crash or a
power cut costs a minute or two of work, not the afternoon's. The copy goes when the project is
saved or its window is closed properly; one left behind is offered the next time Reel starts."""
import json
import os
import time


def folder():
    root = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(root, "folio-reel", "recovery")


def every():
    """Seconds between copies (FOLIO_REEL_RECOVERY_SECS, for tests)."""
    try:
        return max(1, int(os.environ.get("FOLIO_REEL_RECOVERY_SECS", "45")))
    except ValueError:
        return 45


def _file(rid):
    return os.path.join(folder(), "%s.json" % rid)


def write(rid, name, path, project_json):
    os.makedirs(folder(), exist_ok=True)
    tmp = _file(rid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write('{"pid": %d, "name": %s, "path": %s, "saved": %f, "project": %s}'
                % (os.getpid(), json.dumps(name), json.dumps(path), time.time(), project_json))
    os.replace(tmp, _file(rid))


def clear(rid):
    try:
        os.remove(_file(rid))
    except OSError:
        pass


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


def pending():
    """Copies whose Reel is no longer running, newest first:
    [{"id", "name", "path", "when", "project"}]."""
    out = []
    try:
        names = os.listdir(folder())
    except OSError:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        p = os.path.join(folder(), n)
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            try:
                os.remove(p)
            except OSError:
                pass
            continue
        if not isinstance(d, dict) or not isinstance(d.get("project"), dict):
            continue
        if d.get("pid") == os.getpid() or _alive(d.get("pid")):
            continue
        saved = float(d.get("saved") or 0)
        out.append({"id": n[:-5], "name": d.get("name") or "a project", "path": d.get("path"),
                    "when": time.strftime("%H:%M on %d %B", time.localtime(saved)), "saved": saved,
                    "project": d["project"]})
    out.sort(key=lambda e: -e["saved"])
    return out
