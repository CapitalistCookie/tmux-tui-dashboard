"""The bottom pane: one line for each event of the source, `HH:MMZ  <source>  <event>`, followed live.

  python3 -m tmux_tui_dashboard.follow [--once] [--backlog 40] [--poll 1]
"""
import argparse
import os
import re
import signal
import subprocess
import sys
import time
import unicodedata

REPO = os.path.dirname(os.path.abspath(__file__))
from tmux_tui_dashboard import palette
from tmux_tui_dashboard import model
from tmux_tui_dashboard.source import load_source

COLOR = dict(palette.C, orch=palette.C["cyan"], builder=palette.C["yellow"], driver=palette.C["magenta"],
             healer=palette.C["green"], err=palette.C["red"])


def hhmmss(ts):
    return ((ts or "")[11:16] or model.clock().strftime("%H:%M")) + "Z"


ANSI = re.compile(r"\033\[[0-9;]*m")


def cw(ch):
    if unicodedata.combining(ch) or ord(ch) < 32 or ord(ch) == 127:
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def visible_len(s):
    return sum(cw(c) for c in ANSI.sub("", s))


def cut(s, width):
    width = max(1, width)
    if visible_len(s) <= width:
        return s + COLOR["reset"]
    out, n = [], 0
    for piece in re.split(r"(\033\[[0-9;]*m)", s):
        if piece.startswith("\033["):
            out.append(piece)
            continue
        kept = []
        for ch in piece:
            if n + cw(ch) > width - 1:
                break
            kept.append(ch)
            n += cw(ch)
        out.append("".join(kept))
        if len(kept) < len(piece):
            break
    return "".join(out) + "…" + COLOR["reset"]


def tokens(s):
    out, active = [], ""
    for piece in re.split(r"(\033\[[0-9;]*m)", s):
        if not piece:
            continue
        if piece.startswith("\033["):
            active = "" if piece in (COLOR["reset"], "\033[m") else active + piece
            continue
        for w in re.split(r"(\s+)", piece):
            if w:
                out.append((w, active))
    return out


def wrap(s, width, indent=2, max_lines=0):
    width = max(8, width)
    lead = " " * min(max(0, indent), max(0, width - 8))
    lines, cur, n, gap = [], "", 0, ""
    words = tokens(s)
    if words and words[0][0].isspace():
        cur, n, words = words[0][0], len(words[0][0]), words[1:]
    for word, col in words:
        if word.isspace():
            if n:
                gap = word
            continue
        w = visible_len(word)
        if n and n + len(gap) + w > width:
            lines.append(cur + COLOR["reset"])
            cur, n, gap = lead, len(lead), ""
        if gap:
            cur, n, gap = cur + gap, n + len(gap), ""
        while w > width - n:
            kept, k = [], n
            for ch in word:
                if k + cw(ch) > width:
                    break
                kept.append(ch)
                k += cw(ch)
            if kept:
                cur += col + "".join(kept)
                word = word[len(kept):]
                w = visible_len(word)
            lines.append(cur + COLOR["reset"])
            cur, n = lead, len(lead)
        if word:
            cur, n = cur + col + word, n + w
    if n or not lines:
        lines.append(cur + COLOR["reset"])
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = cut(lines[-1] + "…", width)
    return [cut(line, width) for line in lines]


CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def flat(text):
    return CONTROL.sub(" ", " ".join(str(text or "").split()))


def _sources():
    out, root = [], REPO + os.sep
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", None)
        if path and os.path.abspath(path).startswith(root):
            try:
                out.append((os.path.abspath(path), os.stat(path).st_mtime))
            except OSError:
                pass
    return sorted(set(out))


def _moved(stamp):
    try:
        return any(not os.path.exists(path) or os.stat(path).st_mtime != mtime for path, mtime in stamp)
    except OSError:
        return False


def _reload_if_changed(stamp):
    try:
        for path, mtime in stamp:
            if not os.path.exists(path) or os.stat(path).st_mtime != mtime:
                os.execv(sys.executable, [sys.executable] + sys.argv)
    except OSError:
        pass


SRC_W = 18


def cut_words(s, width):
    if visible_len(s) <= width:
        return s + COLOR["reset"]
    plain = ANSI.sub("", s)
    keep, n = 0, 0
    for ch in plain:
        if n + cw(ch) > width - 1:
            break
        n += cw(ch)
        keep += 1
    at = plain.rfind(" ", 0, keep)
    if 0 < keep < len(plain) and not plain[keep].isspace() and at >= keep // 2:
        keep = at
    while keep and plain[keep - 1] in " ,;:":
        keep -= 1
    out, k = [], 0
    for piece in re.split(r"(\033\[[0-9;]*m)", s):
        if piece.startswith("\033["):
            out.append(piece)
            continue
        take = piece[:max(0, keep - k)]
        out.append(take)
        k += len(take)
        if len(take) < len(piece):
            break
    return "".join(out) + "…" + COLOR["reset"]


RELOAD_SECS = 5


def render(ev, width):
    source, text, kind = ev.source or "driver", flat(ev.text), ev.kind
    if kind in ("divider", "reset"):
        head = fit_words(COLOR["bold"] + "═══ " + hhmmss(ev.time) + "  " + text + " ", width - 3)
        return [head + COLOR["bold"] + "═" * max(3, width - visible_len(head)) + COLOR["reset"]]
    if ev.outcome:
        mark = {"ok": COLOR["green"] + "✔", "failed": COLOR["err"] + "✖"}.get(ev.outcome, COLOR["amber"] + ev.outcome)
        call = ("$ " + text) if kind == "Bash" else (COLOR["bold"] + kind + COLOR["reset"] + " " + text)
        body = mark + COLOR["reset"] + " " + call + (COLOR["dim"] + "   " + flat(ev.result) + COLOR["reset"]
                                                     if ev.result else "")
    elif kind == "error" or ev.level == "error":
        body = COLOR["err"] + "ERROR " + text + COLOR["reset"]
    elif kind == "result":
        body = COLOR["dim"] + "-> " + text + COLOR["reset"]
    elif kind == "says":
        body = "says: " + text
    elif kind == "prompt":
        body = COLOR["dim"] + "prompt: " + text + COLOR["reset"]
    elif kind in ("log", "heartbeat"):
        body = (COLOR["dim"] if kind == "heartbeat" else "") + text + (COLOR["reset"] if kind == "heartbeat" else "")
    else:
        body = COLOR["bold"] + kind + COLOR["reset"] + ": " + text
    tone = {"driver": COLOR["dim"], "healer": COLOR["cyan"], "walker": COLOR["magenta"],
            "merge": COLOR["green"], "orchestrator": COLOR["lane:cpu"]}.get(source.split()[0],
                                                                            COLOR["yellow"])
    body = re.sub(r"\b(PASS|FAIL|ERROR)\b",
                  lambda m: ((COLOR["green"] if m.group(1) == "PASS" else COLOR["red"]) + m.group(1)
                             + COLOR["reset"]),
                  body)
    stamped = (COLOR["dim"] + hhmmss(ev.time) + COLOR["reset"] + "  " + tone + COLOR["bold"]
               + source.ljust(SRC_W)
               + COLOR["reset"] + " ")
    return [fit_words(stamped + body, width)]


def fit_words(s, width):
    if visible_len(s) <= width:
        return s + COLOR["reset"]
    toks = tokens(s)
    total = sum(1 for w, _c in toks if not w.isspace())
    n = k = best = end = 0
    for i, (w, _c) in enumerate(toks):
        n += visible_len(w)
        if w.isspace():
            continue
        k += 1
        if n + len(" +%d words" % (total - k)) > width:
            break
        best, end = k, i + 1
    left = total - best
    return ("".join(c + w + COLOR["reset"] for w, c in toks[:end]) + COLOR["dim"]
            + " +%d word%s" % (left, "" if left == 1 else "s") + COLOR["reset"])


CALL_LONG = 10


def footer(calls, now_t, width):
    items = []
    for ev in calls:
        t = model.parse_time(ev.time)
        secs = max(0.0, (now_t - t).total_seconds()) if t else 0.0
        age = ("%d s" % secs) if secs < 60 else span_text(secs / 60)
        what = ("$ " + flat(ev.text)) if ev.kind == "Bash" else (ev.kind + " " + flat(ev.text))
        items.append(COLOR["bold"] + ev.source + COLOR["reset"] + " " + fit_words(what, 48) + " for "
                     + (COLOR["amber"] if secs >= CALL_LONG * 60 else "") + age + COLOR["reset"])
    row = COLOR["dim"] + ("── in flight: " if items else "── nothing in flight ") + COLOR["reset"]
    for k, it in enumerate(items):
        more = " +%d more" % (len(items) - k - 1) if k + 1 < len(items) else ""
        if visible_len(row) + visible_len(it) + len(more) + 4 > width:
            row += COLOR["dim"] + "+%d more " % (len(items) - k) + COLOR["reset"]
            break
        row += it + "   "
    return row + COLOR["dim"] + "─" * max(0, width - visible_len(row)) + COLOR["reset"]


QUIET_MIN = 10


def span_text(minutes):
    minutes = int(round(minutes))
    if minutes < 60:
        return "%d min" % minutes
    return "%dh%02dm" % (minutes // 60, minutes % 60) if minutes < 2880 else "%.1fd" % (minutes / 1440)


def quiet_rule(a, z, width):
    text = " %s with no event, %s to %s " % (span_text((z - a).total_seconds() / 60), a.strftime("%H:%MZ"),
                                             z.strftime("%H:%MZ"))
    side = max(2, (width - len(text)) // 2)
    return cut(COLOR["dim"] + "─" * side + text + "─" * max(0, width - side - len(text)) + COLOR["reset"], width)


def stream_lines(evs, width, last=None):
    out = []
    for ev in evs:
        t = model.parse_time(ev.time) if ev.time and ev.kind != "heartbeat" else None
        if t and last and (t - last).total_seconds() >= QUIET_MIN * 60:
            out.append(quiet_rule(last, t, width))
        if t:
            last = max(last, t) if last else t
        out.extend(render(ev, width))
    return out, last


class Shaper:

    def __init__(self):
        self.shown = {}

    def feed(self, evs):
        out, i, now_t = [], 0, time.time()
        if len(self.shown) > 5000:
            self.shown = {k: v for k, v in self.shown.items() if now_t - v < 1800}
        while i < len(evs):
            key = (evs[i].source, (evs[i].time or "")[:19])
            j = i
            while j < len(evs) and (evs[j].source, (evs[j].time or "")[:19]) == key:
                j += 1
            run = evs[i:j]
            if len(run) > 5:
                run = run[:2] + [model.Event(run[2].time, run[2].source, "+%d more lines" % (len(run) - 2))]
            for ev in run:
                sig = "%s|%s|%s" % (ev.source, ev.kind, flat(ev.text))
                if ev.kind != "heartbeat" and now_t - self.shown.get(sig, -1e9) < 1800:
                    continue
                self.shown[sig] = now_t
                out.append(ev)
            i = j
        return out


def height():
    for handle in (sys.__stdout__, sys.__stderr__):
        try:
            rows = os.get_terminal_size(handle.fileno()).lines
            if rows > 0:
                return rows
        except (OSError, ValueError, AttributeError):
            pass
    return 24


class Pin:

    def __init__(self, source):
        self.source, self.rows, self.drawn = source, 0, None
        self.live = sys.stdout.isatty()

    def draw(self):
        if not self.live:
            return
        rows, cols = height(), width()
        if rows < 3:
            return
        calls = getattr(self.source, "open_calls", lambda: [])()
        text = footer(calls, model.clock(), cols)
        out = ""
        if rows != self.rows:
            out += "\0337\033[1;%dr\0338\033[%d;1H" % (rows - 1, rows - 1)
            self.rows, self.drawn = rows, None
        if text != self.drawn:
            out += "\0337\033[%d;1H\033[2K%s\0338" % (rows, text)
            self.drawn = text
        if out:
            sys.stdout.write(out)
            sys.stdout.flush()

    def stop(self):
        if self.live and self.rows:
            sys.stdout.write("\033[%d;1H\033[2K\033[r\033[%d;1H" % (self.rows, self.rows))
            sys.stdout.flush()


def width():
    for handle in (sys.__stdout__, sys.__stderr__):
        try:
            cols = os.get_terminal_size(handle.fileno()).columns
            if cols > 0:
                return max(24, cols)
        except (OSError, ValueError, AttributeError):
            pass
    cols = os.environ.get("COLUMNS", "")
    if cols.isdigit():
        return max(24, int(cols))
    pane = os.environ.get("TMUX_PANE")
    if pane:
        try:
            return max(24, int(subprocess.run(["tmux", "display", "-p", "-t", pane, "#{pane_width}"],
                                              capture_output=True, text=True, timeout=5).stdout.strip()))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return 120


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", nargs="?", default="")
    ap.add_argument("--sub", action="append", default=[])
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--once", action="store_true", help="print the backlog of the source and stop")
    ap.add_argument("--backlog", type=int, default=40)
    ap.add_argument("--poll", type=float, default=1.0)
    args = ap.parse_args()
    source = load_source(transcript=args.transcript, subs=args.sub, auto=args.auto or not args.transcript)
    shaper = Shaper()
    pin = Pin(source) if not args.once else None
    if pin:
        def leave(_signum, _frame):
            pin.stop()
            os._exit(0)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, leave)
        pin.draw()

    begun, newest = [], [None]

    def show(evs):
        lines, newest[0] = stream_lines(evs, width(), newest[0])
        for line in lines:
            sys.stdout.write(("\n" if begun else "") + line)
            begun[:] = [1]
    evs = source.events(None)
    show(shaper.feed(evs[-args.backlog:]))
    sys.stdout.flush()
    if args.once:
        sys.stdout.write("\n")
        return
    last = max([e.time for e in evs if e.time] or [""])
    stamp, checked = _sources(), time.time()
    try:
        while True:
            batch = source.events(last)
            if batch:
                last = max([last] + [e.time for e in batch if e.time])
                resets = [k for k, e in enumerate(batch) if e.kind == "reset"]
                if resets:
                    k = resets[-1]
                    show(shaper.feed(batch[:k]))
                    if batch[k].text:
                        show([batch[k]])
                    shaper = Shaper()
                    show(shaper.feed(batch[k + 1:][-args.backlog:]))
                else:
                    show(shaper.feed(batch))
                sys.stdout.flush()
            pin.draw()
            if time.time() - checked >= RELOAD_SECS:
                checked = time.time()
                if _moved(stamp):
                    pin.stop()
                _reload_if_changed(stamp)
            time.sleep(args.poll)
    except KeyboardInterrupt:
        pin.stop()
        return


if __name__ == "__main__":
    main()
