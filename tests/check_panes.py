"""The checks of the three panes, drawn from the sample feed at a pinned clock.   python3 tests/check_panes.py

  width     no row wider than its pane: the task graph, the top pane and the chart at every width from 24 to 219
  wrap      a wrapped block breaks between words and keeps every word
  frame     the painter never erases the screen, writes nothing when no row changed, and one row when one changed
  colour    the text is the same at 256 colours, at 8 and at none, with the same widths
  identity  the sample, written back as a feed and read again, draws the same three panes
  layout    at 134 by 28 every task is drawn once, every edge is routed, no two boxes overlap, no line runs through
            a box, and the rows are the budget
  run       python3 -m tmux_tui_dashboard.progress, .phases and .follow --once draw at 134 columns without an error
"""
import json
import os
import random
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "tmux_tui_dashboard", "feed.sample.json")
NOW = "2026-09-20T12:00:00Z"
os.environ["TMUX_TUI_DASHBOARD_NOW"] = NOW
sys.path.insert(0, ROOT)
from tmux_tui_dashboard import follow as F, model, phases as PH, progress as P  # noqa: E402
from tmux_tui_dashboard.source import load_source  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;]*m")
FAILED = []


def fail(group, text):
    FAILED.append((group, text))
    print("  FAIL %-8s %s" % (group, text))


def panes(src, width=134):
    b = P.Build(src)
    shaper = F.Shaper()
    stream = [line for ev in shaper.feed(src.events(None)[-40:]) for line in F.render(ev, width)]
    return b, P.render(width, 41, b) + ["\x00"] + PH.render(width, 26, b) + ["\x00"] + stream


def check_width(b):
    n = 0
    for w in range(24, 220):
        for rows in (P.task_graph(b, w, 30), P.render(w, 41, b), PH.render(w, 26, b)):
            for row in rows:
                n += 1
                if P.visible_len(row) > w:
                    return fail("width", "%d columns: a row of %d" % (w, P.visible_len(row))) or n
    return n


def check_wrap(_b):
    words = "merged rebased worktree M2 t21 the a of and into before after commit subject 12h04m".split()
    random.seed(7)
    n = 0
    for _ in range(80):
        text = " ".join(random.choice(words) for _ in range(random.randint(1, 50)))
        for w in (24, 60, 134):
            block = P.wrap(P.color("dim", text), w, indent=2)
            n += 1
            if any(P.visible_len(x) > w for x in block) or \
                    " ".join(ANSI.sub("", x).strip() for x in block).split() != text.split():
                return fail("wrap", "a block at %d columns lost a word or grew past the width" % w) or n
    return n


def check_frame(_b):
    rows = ["row %d" % i + " x" * 30 for i in range(41)]
    frame = P.Frame()
    first, same = frame.paint(rows, (134, 41)), frame.paint(rows, (134, 41))
    one = list(rows)
    one[10] = "the one row that moved"
    moved = frame.paint(one, (134, 41))
    if re.search(r"\x1b\[2J|\x07", first + same + moved):
        fail("frame", "a frame erases the screen or rings the bell")
    if re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", same):
        fail("frame", "an unchanged frame wrote content")
    if len(re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", moved)) > 80:
        fail("frame", "one changed row cost more than one row")
    return 3


def check_colour(_b):
    script = os.path.join(tempfile.mkdtemp(prefix="tmux_tui_dashboard-colour-"), "draw.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write("import sys\nsys.path.insert(0, %r)\nfrom tmux_tui_dashboard import progress as P, phases as PH\n"
                 "from tmux_tui_dashboard.source import load_source\nb = P.Build(load_source(%r))\n"
                 "print('\\x01'.join(P.render(134, 41, b) + PH.render(134, 26, b)))\n" % (ROOT, "json:" + SAMPLE))
    seen = {}
    for depth in ("256", "8", "none"):
        out = subprocess.run([sys.executable, script], capture_output=True, text=True,
                             env=dict(os.environ, TMUX_TUI_DASHBOARD_COLOR=depth, TERM="xterm-256color"))
        if out.returncode:
            return fail("colour", "the draw at %s failed: %s" % (depth, out.stderr.strip()[-200:])) or 1
        seen[depth] = out.stdout
    plain = {d: ANSI.sub("", t) for d, t in seen.items()}
    if len(set(plain.values())) != 1:
        fail("colour", "the text differs between colour depths: colour carries meaning alone")
    if ANSI.search(seen["none"]) or not ANSI.search(seen["256"]):
        fail("colour", "the depth does not reach the draw")
    return 3


def check_identity(_b):
    src = load_source("json:" + SAMPLE)
    b, first = panes(src)
    path = os.path.join(tempfile.mkdtemp(prefix="tmux_tui_dashboard-identity-"), "feed.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(model.feed_of(b, src.events(None)), fh)
    _b2, second = panes(load_source("json:" + path))
    if first != second:
        row = next(i for i, (x, y) in enumerate(zip(first, second)) if x != y)
        fail("identity", "the feed read again draws row %d differently" % row)
    return 1


def check_layout(b):
    P.task_graph(b, 134, 28)
    d = b.graph_drawn["drawing"]
    rects = list(d.boxes.values()) + [tuple(x) for x in d.extra]
    for k, a in enumerate(rects):
        for z in rects[k + 1:]:
            if a[0] < z[0] + z[2] and z[0] < a[0] + a[2] and a[1] < z[1] + z[3] and z[1] < a[1] + a[3]:
                fail("layout", "two boxes overlap: %s %s" % (a, z))
    if any(r[0] <= x < r[0] + r[2] and r[1] <= y < r[1] + r[3] for x, y in d.wires for r in rects):
        fail("layout", "a line runs through a box")
    nodes, edges, _g = P.graph_model(b)
    want = {(s, t) for s, t in edges if s in d.boxes and t in d.boxes}
    if set(d.edges) != want or d.hidden or len(d.cells) != 28:
        fail("layout", "%d of %d edges routed, %d boxes hidden, %d rows" % (len(d.edges), len(want),
                                                                        len(d.hidden), len(d.cells)))
    return len(d.boxes)


def check_run(_b):
    env = dict(os.environ, TMUX_TUI_DASHBOARD_SOURCE="json:" + SAMPLE, COLUMNS="134", TMUX_TUI_DASHBOARD_COLOR="none")
    env.pop("TMUX_PANE", None)
    n = 0
    for mod, rows in (("progress", 41), ("phases", 26), ("follow", 17)):
        argv = [sys.executable, "-m", "tmux_tui_dashboard." + mod] + (["--once"] if mod == "follow" else [])
        out = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT, env=dict(env, LINES=str(rows)),
                             stdin=subprocess.DEVNULL, timeout=120)
        lines = out.stdout.rstrip("\n").split("\n")
        n += len(lines)
        if out.returncode or "Traceback" in out.stderr or "error" in lines[0]:
            fail("run", "%s drew an error: %s" % (mod, (out.stderr or lines[0])[-200:]))
        if any(len(x) > 134 for x in lines):
            fail("run", "%s drew a row wider than 134 columns" % mod)
        if mod == "progress" and len(lines) != rows:
            fail("run", "the top pane drew %d rows for %d" % (len(lines), rows))
    return n


GROUPS = {"width": check_width, "wrap": check_wrap, "frame": check_frame, "colour": check_colour,
          "identity": check_identity, "layout": check_layout, "run": check_run}


def main():
    b = P.Build(load_source("json:" + SAMPLE))
    counts = []
    for name, fn in GROUPS.items():
        n = fn(b)
        counts.append("%s=%d" % (name, n or 0))
        print("  %-8s %d check(s)" % (name, n or 0))
    print("check_panes %s -> %s" % (" ".join(counts), "FAIL (%d)" % len(FAILED) if FAILED else "PASS"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
