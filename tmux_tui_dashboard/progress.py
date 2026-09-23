"""The top pane: what runs now, what is blocked, what comes next, the task graph, the status strip and
the legend.

  python3 -m tmux_tui_dashboard.progress           draw once
  python3 -m tmux_tui_dashboard.progress --loop    redraw every 2 s (TMUX_TUI_DASHBOARD_PROGRESS_SECONDS), in place
"""
import datetime
import math
import os
import re
import signal
import statistics
import subprocess
import sys
import time
import unicodedata

REPO = os.path.dirname(os.path.abspath(__file__))
from tmux_tui_dashboard import palette
from tmux_tui_dashboard import model
from tmux_tui_dashboard.source import load_source
from tmux_tui_dashboard import layout as dash_layout


C = dict(palette.C)
C["blue"] = C.get("lane:cpu", "")
for _key in [k for k in C if k.startswith("lane:")]:
    C[_key] = ""
C.update({"hot": C["amber"], "warn": C["amber"], "parked": C["red"]})
ANSI = re.compile(r"\033\[[0-9;]*m")
GLYPH = {"done": "✔", "building": "▶", "merging": "≡", "review": "◆", "ready": "·", "waiting": "◌", "blocked": "✖",
         "healing": "✚", "pulled": "*"}
CRIT = "»"
KIND = {"done": "green", "building": "yellow", "merging": "yellow", "review": "yellow", "ready": "blue", "waiting": "dim",
        "blocked": "red", "healing": "cyan", "pulled": "dim"}
MS_KIND = {"done": "green", "building": "yellow", "blocked": "red", "healing": "cyan", "waiting": "dim"}


def ms_colour(b, m):
    return MS_KIND.get(b.ms_state(m), "dim")


def ramp(value, mean):
    return "amber" if value is not None and mean and value > mean else "level"


def health(ok, warn=False):
    return "amber" if warn else ("green" if ok else "red")


def hm(minutes):
    minutes = int(round(minutes))
    return "%dh%02dm" % (minutes // 60, minutes % 60) if minutes >= 60 else "%dm" % minutes


def dur(minutes):
    minutes = max(0.0, float(minutes))
    return hm(minutes) if minutes < 2880 else "%.1fd" % (minutes / 1440)


def plan_and_spent(b):
    plan = sum(m.minutes for m in b.milestones)
    first = b.project.seeded or b.now
    return plan, max(0.0, (b.now - first).total_seconds() / 60)


def cw(ch):
    if unicodedata.combining(ch) or ord(ch) < 32 or ord(ch) == 127:
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def visible_len(s):
    return sum(cw(c) for c in ANSI.sub("", s))


def cut(s, width):
    width = max(1, width)
    if visible_len(s) <= width:
        return s + C["reset"]
    plain = ANSI.sub("", s)
    keep, n = 0, 0
    for ch in plain:
        if n + cw(ch) > width - 1:
            break
        n += cw(ch)
        keep += 1
    if 0 < keep < len(plain) and not plain[keep].isspace() and not plain[keep - 1].isspace():
        at = plain.rfind(" ", 0, keep)
        if at >= max(1, keep // 2):
            keep = at
    while keep and plain[keep - 1] in " ,;:·":
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
    return "".join(out) + "…" + C["reset"]


LABEL_W = 9


def label(text, width=LABEL_W):
    return color("bold", clip(text, max(1, width - 1)).ljust(width))


def clip(text, width):
    if visible_len(text) <= width:
        return text
    if width < 2:
        return "…"[:max(0, width)]
    keep, n = 0, 0
    for ch in text:
        if n + cw(ch) > width - 1:
            break
        n += cw(ch)
        keep += 1
    if keep < len(text) and not text[keep].isspace():
        at = max(text.rfind(c, 0, keep) for c in " _-./")
        if at >= max(1, keep // 3):
            keep = at + (0 if text[at] == " " else 1)
    return text[:keep].rstrip(" ,;:·._-/") + "…"


def fit(parts, width, sep="   "):
    parts = [p for p in parts if p]
    if not parts:
        return cut("", width)
    out = parts[0]
    for p in parts[1:]:
        if visible_len(out) + visible_len(sep) + visible_len(p) <= width:
            out += sep + p
    return cut(out, width)


def pack(head, items, width, max_rows=1, sep="   ", gutter=LABEL_W):
    items = [x for x in items if x]
    rows, cur, left = [], label(head, gutter), 0
    for i, it in enumerate(items):
        if visible_len(cur) <= gutter:
            cur += it
        elif visible_len(cur) + visible_len(sep) + visible_len(it) <= width:
            cur += sep + it
        elif len(rows) + 1 < max_rows:
            rows.append(cut(cur, width))
            cur = " " * gutter + it
        else:
            left = len(items) - i
            break
    more = color("dim", "+%d more" % left) if left else ""
    if more and visible_len(cur) + visible_len(sep) + visible_len(more) <= width:
        cur += sep + more
    rows.append(cut(cur, width))
    return rows


def tokens(s):
    out, active = [], ""
    for piece in re.split(r"(\033\[[0-9;]*m)", s):
        if not piece:
            continue
        if piece.startswith("\033["):
            active = "" if piece in (C["reset"], "\033[m") else active + piece
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
            lines.append(cur + C["reset"])
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
            lines.append(cur + C["reset"])
            cur, n = lead, len(lead)
        if word:
            cur, n = cur + col + word, n + w
    if n or not lines:
        lines.append(cur + C["reset"])
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = cut(lines[-1] + "…", width)
    return [cut(line, width) for line in lines]


def section(title, width):
    text = " %s " % title if title else ""
    return cut(color("dim", "──") + color("bold", text)
               + color("dim", "─" * max(0, width - 2 - visible_len(text))), width)


LEGEND = False


def heartbeat(now):
    return "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(now.timestamp()) % 10]


def pane_size():
    for handle in (sys.__stdout__, sys.__stderr__):
        try:
            sz = os.get_terminal_size(handle.fileno())
            if sz.columns > 0:
                return max(24, sz.columns), max(8, sz.lines)
        except (OSError, ValueError, AttributeError):
            pass
    cols, rows = os.environ.get("COLUMNS", ""), os.environ.get("LINES", "")
    if cols.isdigit() and rows.isdigit():
        return max(24, int(cols)), max(8, int(rows))
    pane = os.environ.get("TMUX_PANE")
    if pane:
        try:
            out = subprocess.run(["tmux", "display", "-p", "-t", pane, "#{pane_width} #{pane_height}"],
                                 capture_output=True, text=True, timeout=5).stdout.split()
            return max(24, int(out[0])), max(8, int(out[1]))
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            pass
    return 120, 45


class Frame:

    FULL_EVERY = 30

    def __init__(self):
        self.prev, self.size, self.n = [], None, 0

    def paint(self, rows, size):
        full = size != self.size or len(rows) != len(self.prev) or self.n % self.FULL_EVERY == 0
        self.n += 1
        out = []
        if full:
            out.append("\033[H")
            for i, row in enumerate(rows):
                out.append(("\n" if i else "") + "\033[2K" + row)
            out.append("\033[J")
        else:
            for i, (row, was) in enumerate(zip(rows, self.prev)):
                if row != was:
                    out.append("\033[%d;1H\033[2K%s" % (i + 1, row))
        self.prev, self.size = list(rows), size
        if out:
            out.append("\033[%d;1H" % max(1, len(rows)))
        return "".join(out)


def color(kind, text):
    return C.get(kind, "") + text + C["reset"]


def pad(s, n):
    return s + " " * max(0, n - visible_len(s))


QUEUED, IN_FLIGHT = model.QUEUED, model.IN_FLIGHT


def gk(state):
    return state


def idkey(i):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", i or "")]


def msort(b, ms):
    return sorted(ms, key=lambda m: (b.order.index(m) if m in b.order else len(b.order), idkey(m)))


def snapshot(source=None):
    b = model.snapshot(source or load_source())
    b.hue = palette.hue_plan(b.order, b.focus, {m for m in b.order if b.ms_state(m) == "done"})
    return b


SOURCE = []


def usage_text(b):
    use = b.usage.windows if b.usage else []
    if not use:
        return color("dim", "usage unknown")
    out = []
    for w in use:
        tone = "red" if w.percent >= 90 else "yellow" if w.percent >= 75 else "green"
        item = C[tone] + "%s %d%%" % (w.name, w.percent) + C["reset"] + color("dim", " ↻" + w.resets)
        if w.rate is not None:
            item += color("dim", " %+.0f%%/h" % w.rate)
            if w.full:
                first = w.reset_at is None or w.full < w.reset_at
                item += color("amber" if first else "dim", " full ~%s%s" % (
                    when(b, w.full), ", before its reset" if first and w.reset_at else ""))
        out.append(item)
    return color("dim", "usage ") + color("dim", " · ").join(out)


Build = snapshot


def short_name(b, tid):
    t = b.by_id.get(tid)
    return t.short if t else ""


GRID_GUT = 1


def wave_rows(b, waves_of):
    out, run = [], []
    for w in waves_of:
        ids = [t["id"] for t in w["tasks"]]
        if ids and all(b.states[i][0] == "done" for i in ids):
            run.append(w)
            continue
        if run:
            out.append(_done_run(run))
            run = []
        out.append(("w%d " % w["n"], ids, len(ids), 0))
    if run:
        out.append(_done_run(run))
    return out


def _done_run(run):
    label = "w%d " % run[0]["n"] if len(run) == 1 else "w%d-w%d " % (run[0]["n"], run[-1]["n"])
    merged = sum(len(w["tasks"]) for w in run)
    return label, [], len("✔ %d" % merged), merged


def grid_cell(text, width):
    if visible_len(text) <= width:
        return text
    kept, n = [], 0
    for tok in text.split(" "):
        step = (1 if kept else 0) + visible_len(tok)
        if n + step > width:
            break
        kept.append(tok)
        n += step
    return " ".join(kept)


def graph_chart(b, width):
    order = b.order
    red = model.reduced_deps(b)
    tone = {"done": "green", "building": "yellow", "blocked": "red", "waiting": "dim", "healing": "cyan"}
    st = {m: b.ms_state(m) for m in order}
    mark_of = {m: {"done": "✔", "blocked": "✖", "healing": "✚", "waiting": "·"}.get(
        st[m], "▶" if m in b.running else "…") for m in order}
    ws_of = {m: [{"n": n, "tasks": [{"id": i} for i in ids]} for n, ids in b.static_waves(m)] for m in order}
    rows_of = {m: wave_rows(b, ws_of[m]) for m in order}
    head = {m: "%s%s %d/%d" % (mark_of[m], m, len([t for t in b.ms_tasks[m] if t in b.done]), len(b.ms_tasks[m]))
            for m in order}
    pre = {m: max([len(r[0]) for r in rows_of[m]] or [3]) for m in order}
    widest = {m: max([r[2] for r in rows_of[m]] or [1]) for m in order}
    numbered = {m: max([len(r[1]) for r in rows_of[m]] or [1]) for m in order}
    floor = {m: max(11, len(head[m]) + 2, 1 + pre[m] + widest[m]) for m in order}
    need = {m: max(floor[m], pre[m] + 5 * numbered[m]) for m in order}
    span = max(1, width // (11 + GRID_GUT))
    shown = order
    if len(order) > span:
        k = order.index(b.focus) if b.focus in order else 0
        lo = max(0, min(k - span // 2, len(order) - span))
        shown = order[lo:lo + span]
    fi = order.index(b.focus) if b.focus in order else 0
    while len(shown) > 1 and sum(floor[m] + GRID_GUT for m in shown) > width:
        drop = max(range(len(shown)), key=lambda i: abs(order.index(shown[i]) - fi))
        shown = shown[:drop] + shown[drop + 1:]
    W = {m: floor[m] for m in shown}
    spare = width - sum(W[m] + GRID_GUT for m in shown)
    for m in sorted(shown, key=lambda x: (x != b.focus, abs(order.index(x) - fi))):
        if st[m] != "done" and 0 < need[m] - W[m] <= spare:
            spare -= need[m] - W[m]
            W[m] = need[m]
    far = {m: [d for d in red[m] if order.index(d) != order.index(m) - 1] for m in shown}
    cols, cur_wave = {}, None
    for m in shown:
        leads = m != order[-1] and m in red[order[order.index(m) + 1]]
        lines = [color("bold", C[ms_colour(b, m)] + head[m] + C["reset"])
                 + (color("dim", "─" * max(0, W[m] - len(head[m]) - 2) + "─▶") if leads else " " * max(0, W[m] - len(head[m])))]
        if any(far.values()):
            lines.append(color("dim", "◀" + ",".join(far[m]) if far[m] else ""))
        if st[m] == "done":
            lines.append(color("dim", "w1-w%d " % len(ws_of[m]) if len(ws_of[m]) > 1 else "w1 ")
                         + color("green", "✔"))
        else:
            for n_row, (label, ids, _bare, merged) in enumerate(rows_of[m]):
                if merged:
                    lines.append(color("dim", " ") + C[ms_colour(b, m)] + label + C["reset"]
                                 + color("green", "✔ %d" % merged))
                    continue
                first_pending = m == b.focus and cur_wave is None and any(b.states[i][0] != "done" for i in ids)
                if first_pending:
                    cur_wave = label
                marker = "▶" if first_pending else ("▼" if n_row else " ")
                if W[m] >= need[m]:
                    marks = " ".join(color(KIND[gk(b.states[i][0])], GLYPH[gk(b.states[i][0])] + i[2:]) for i in ids)
                else:
                    marks = "".join(color(KIND[gk(b.states[i][0])], GLYPH[gk(b.states[i][0])]) for i in ids)
                lines.append(color("yellow" if first_pending else "dim", marker)
                             + C[ms_colour(b, m)] + label + C["reset"] + marks)
        cols[m] = lines
    b.grid_cols, x = [], 0
    for m in shown:
        b.grid_cols.append((m, x, W[m]))
        x += W[m] + GRID_GUT
    b.grid_rows = max(len(v) for v in cols.values())
    out = []
    for r in range(b.grid_rows):
        row = ""
        for m in shown:
            row += pad(grid_cell(cols[m][r] if r < len(cols[m]) else "", W[m]), W[m]) + " " * GRID_GUT
        out.append(cut(row, width))
    fit = ("%s..%s of %d" % (shown[0], shown[-1], len(order)) if list(shown) != list(order) else "")
    if LEGEND:
        out += wrap(color("dim", (fit + "; " if fit else "")
                          + "columns are milestones, rows are waves: one mark per task (✔ done ▶ building "
                            "≡ merging · queued ✖ blocked), with the task's number beside its mark in a column "
                            "wide enough to carry it, and one summary row for a milestone that is done; "
                            "▼ depends on the wave above, ▶ the current wave, ─▶ the next milestone depends on it, "
                            "◀ a farther one; ✚ a healer session triages the milestone's blocker row"),
                    width, indent=2, max_lines=3)
        out += wrap(color("dim", "hue = distance ahead, running brightest, done grey; colour = lane; elapsed "
                                 "amber past the mean, red past twice; usage green <50%, amber <80%, red 80%+"),
                    width, indent=2, max_lines=1)
    b.grid_fit = fit
    return out


LINE = {1: "│", 2: "│", 3: "│", 4: "─", 8: "─", 12: "─", 6: "┌", 10: "┐", 5: "└", 9: "┘",
        7: "├", 11: "┤", 14: "┬", 13: "┴", 15: "┼"}
DEEP_LAYERS = 14
READABLE_BOX = 18
BOX_ROWS = 5


def chain_row(b, layers, width):
    cells = []
    for ids in layers:
        cells.append(color("dim", "|").join(
            color(KIND[gk(b.states[i][0])], GLYPH[gk(b.states[i][0])] + i) for i in ids))
    return [fit([label("chain") + color("dim", "%s  " % b.focus) + color("dim", " ▸ ").join(cells),
                 color("dim", "zoom the pane for the drawing")], width)]


def node_graph(b, width, max_rows=22):
    order = b.order
    fi = order.index(b.focus) if b.focus in order else 0
    layers = [list(w.tasks) for w in b.waves_of(b.focus)] or [list(ids) for _n, ids in b.static_waves(b.focus)]
    if not layers:
        return [cut(color("dim", "%s has no task row to draw" % b.focus), width)]
    if max_rows < BOX_ROWS:
        return chain_row(b, layers, width)
    placed = {tid for L in layers for tid in L}
    base = len(layers)
    while len(layers) < DEEP_LAYERS:
        nxt = [t.id for t in b.tasks if t.id not in placed and t.milestone in order and order.index(t.milestone) > fi
               and any(d in placed for d in t.depends)
               and all(d in placed or d in b.done for d in t.depends)]
        if not nxt:
            break
        layers.append(nxt)
        placed |= set(nxt)
    for k in range(1, len(layers)):
        prev = {tid: i for i, tid in enumerate(layers[k - 1])}
        base_i = {tid: i for i, tid in enumerate(layers[k])}
        layers[k].sort(key=lambda tid: (sum(prev[d] for d in b.by_id[tid].depends if d in prev) / max(1, len([d for d in b.by_id[tid].depends if d in prev])) if any(d in prev for d in b.by_id[tid].depends if d in prev) else 99, base_i[tid]))
    gap, bw_min, bw_max, bw_far = 5, 8, 24, 9
    n_layers, bws = 0, []
    for n in range(min(len(layers), DEEP_LAYERS), 0, -1):
        near = min(base, n)
        room = width - gap * (n - 1) - bw_far * (n - near)
        if near and room // near >= READABLE_BOX:
            n_layers, bws = n, [min(bw_max, room // near)] * near + [bw_far] * (n - near)
            left, i = width - (sum(bws) + gap * (n - 1)), 0
            while left > 0 and any(w < bw_max for w in bws[:near]):
                if bws[i % near] < bw_max:
                    bws[i % near] += 1
                    left -= 1
                i += 1
            break
    if not n_layers:
        n_layers = max(1, min(len(layers), (width + gap) // (bw_min + gap)))
        bws = [max(bw_min, min(bw_max, (width - (n_layers - 1) * gap) // n_layers))] * n_layers
    layers = layers[:n_layers]
    xs, x = [], 0
    for w in bws:
        xs.append(x)
        x += w + gap
    per = max(1, (max_rows + 1) // 4)
    full = [len(L) for L in layers]
    layers = [L[:per if k < base else min(per, 2)] for k, L in enumerate(layers)]
    pos = {tid: (k, i) for k, L in enumerate(layers) for i, tid in enumerate(L)}
    rows = max(len(L) for L in layers) * 4
    trimmed = [k for k in range(n_layers) if full[k] > len(layers[k])]
    if trimmed:
        rows += 1
    ym = lambda i: i * 4 + 1
    lines = {}
    def seg(x1, y1, x2, y2):
        if y1 == y2:
            for x in range(min(x1, x2), max(x1, x2) + 1):
                lines[(x, y1)] = lines.get((x, y1), 0) | (4 if x < max(x1, x2) else 0) | (8 if x > min(x1, x2) else 0)
        else:
            for y in range(min(y1, y2), max(y1, y2) + 1):
                lines[(x1, y)] = lines.get((x1, y), 0) | (2 if y < max(y1, y2) else 0) | (1 if y > min(y1, y2) else 0)
    arrows = set()
    for tid, (j, ic) in pos.items():
        if j == 0:
            continue
        yc = ym(ic)
        bus = xs[j] - 3
        for d in b.by_id[tid].depends:
            if d not in pos or pos[d][0] >= j:
                continue
            k, ip = pos[d]
            yp = ym(ip)
            exit_x = xs[k] + bws[k]
            if j == k + 1:
                seg(exit_x, yp, bus, yp)
                seg(bus, yp, bus, yc)
            else:
                lane_y = yp + 2
                seg(exit_x, yp, exit_x + 1, yp)
                seg(exit_x + 1, yp, exit_x + 1, lane_y)
                seg(exit_x + 1, lane_y, bus, lane_y)
                seg(bus, lane_y, bus, yc)
            seg(bus, yc, xs[j] - 2, yc)
            arrows.add((xs[j] - 1, yc))
    grid = [[(" ", "dim") for _ in range(width)] for _ in range(rows)]
    for (x, y), m in lines.items():
        if 0 <= x < width and 0 <= y < rows:
            grid[y][x] = (LINE.get(m, "┼"), "dim")
    for (x, y) in arrows:
        if 0 <= x < width and 0 <= y < rows:
            grid[y][x] = ("▶", "dim")
    for k, L in enumerate(layers):
        for i, tid in enumerate(L):
            state, elapsed = b.states[tid]
            t = b.by_id[tid]
            ms = t.milestone or b.focus
            pulled = (order.index(ms) if ms in order else fi) < fi
            inner = bws[k] - 2
            label = "%s%s%s" % (GLYPH[gk(state)], tid, "*" if pulled else "")
            name, room = t.short, inner - len(label) - 1
            if name and room >= 3:
                if len(name) > room:
                    stem, _, ext = name.rpartition(".")
                    name = name[:room - len(ext) - 1] + "…" + ext if stem and ext and room >= len(ext) + 3 else name[:room]
                label += " " + name
            badge = hm(elapsed) if state in IN_FLIGHT and elapsed else ""
            lane = "review" if t.review else (t.lane or "")
            if lane and inner >= len(badge) + len(lane) + 4:
                badge = (badge + " " if badge else "") + lane
            top = "┌" + (("─" + badge) if badge else "").ljust(inner, "─")[:inner] + "┐"
            mid = "│" + label[:inner].ljust(inner) + "│"
            bot = "└" + "─" * inner + "┘"
            tone = "magenta" if pulled else KIND[gk(state)]
            for dy, text in ((-1, top), (0, mid), (1, bot)):
                y = ym(i) + dy
                for dx, ch in enumerate(text):
                    x = xs[k] + dx
                    if 0 <= x < width and 0 <= y < rows:
                        if dy == 0:
                            paint = tone
                        elif dy == -1 and badge and 1 <= dx <= len(badge) + 1:
                            paint = "lane:" + (lane or "")
                        else:
                            paint = ms_colour(b, ms)
                        grid[y][x] = (ch, paint)
    for k in trimmed:
        for dx, ch in enumerate("+%d more" % (full[k] - len(layers[k]))):
            x, y = xs[k] + dx, rows - 1
            if 0 <= x < width and 0 <= y < rows:
                grid[y][x] = (ch, "dim")
    out = []
    while rows > 1 and all(grid[rows - 1][x][0] == " " for x in range(width)):
        rows -= 1
    for y in range(rows):
        row, last = "", None
        for ch, kind in grid[y]:
            if kind != last:
                row += C["reset"] + (C["bold"] if kind in ("yellow",) else "") + C.get(kind, "")
                last = kind
            row += ch
        out.append(cut(row.rstrip() + C["reset"], width))
    deepest = b.by_id[layers[-1][0]].milestone if n_layers > base and layers and layers[-1] else ""
    head = ("%s as nodes and edges: %d layer(s), the first %d the waves of %s in boxes of %d columns and the rest "
            "the downstream work in boxes of %d%s; a box carries the state glyph, the task id, its short name, and "
            "its lane and elapsed minutes in the top border, each as the width allows; the border carries the state "
            "color, * marks a task pulled in from an earlier milestone (magenta), ▶ an edge into the task that "
            "depends on it%s") % (
        b.focus, n_layers, min(base, n_layers), b.focus, bws[0], bws[-1],
        " as far as " + deepest if deepest else "",
        "; %s" % ", ".join("layer %d drops %d box(es) the pane is too short for" % (k + 1, full[k] - len(layers[k]))
                           for k in trimmed) if trimmed else "")
    if not LEGEND:
        dropped = sum(full[k] - len(layers[k]) for k in trimmed)
        head = "%s%s  %d layers%s" % (
            b.focus, " ▸ " + deepest if deepest else "", n_layers,
            "  %d box(es) hidden, the pane is too short" % dropped if dropped else "")
        return [cut(color("dim", head), width)] + out
    return wrap(color("dim", head), width, indent=2, max_lines=3) + out


MERGE_BLOCK = " ▁▃▅▇"


def merged_times(b):
    return sorted(t.merged for t in b.tasks if t.merged)


def timeline(b, width, remaining_min, makespan_min):
    start, deadline = b.project.run.start, b.project.run.end
    finish_ms = b.now + datetime.timedelta(minutes=remaining_min)
    finish_all = b.now + datetime.timedelta(minutes=makespan_min)
    start = start or b.now
    end = max(x for x in (deadline, finish_ms, b.now + datetime.timedelta(minutes=30)) if x)
    span = max(60.0, (end - start).total_seconds() / 60)
    bar_w = max(10, width - LABEL_W - 15)

    def pos(t):
        return min(bar_w - 1, max(0, int((t - start).total_seconds() / 60 / span * bar_w)))
    bar = ["─"] * bar_w
    for c in b.cycles:
        if c.since and c.since >= start:
            bar[pos(c.since)] = "H"
    bar[pos(finish_ms)] = "F"
    if deadline:
        bar[pos(deadline)] = "D"
    bar[pos(b.now)] = "●"
    text = "".join(bar)
    text = text.replace("●", color("yellow", "●") + C["dim"]).replace("F", color("bold", "F") + C["dim"])
    text = text.replace("D", color("amber", "D") + C["dim"]).replace("H", color("cyan", "H") + C["dim"])
    l1 = cut("%s%s%s├%s┤ %s%s" % (label("night"), C["dim"], start.strftime("%H:%MZ"), text,
                                  end.strftime("%H:%MZ"), C["reset"]), width)
    lanes = [0] * bar_w
    for when in merged_times(b):
        if start <= when <= end:
            lanes[pos(when)] += 1
    strip = "".join(MERGE_BLOCK[min(n_merged, len(MERGE_BLOCK) - 1)] for n_merged in lanes)
    l1b = cut("%s%s%s %s" % (label("merges"), " " * 7, color("dim", strip),
                              color("dim", "n=%d" % sum(lanes))), width)
    left = ((" (%s left)" % hm((deadline - b.now).total_seconds() / 60)) if deadline > b.now else " passed") \
        if deadline else ""
    p = b.plan
    l2 = [fit([" " * LABEL_W + color("dim", "● now %s" % b.now.strftime("%H:%MZ")),
               color("dim", "F %s finishes ~%s%s" % (b.focus, finish_ms.strftime("%H:%MZ"),
                     " (builder mean %.0f min, n=%d)" % (p.builder_minutes, p.builder_n) if p.builder_n
                     else " (no builder reported yet; %d min)" % p.builder_minutes)),
               color("dim", "D deadline %s%s" % (deadline.strftime("%H:%MZ") if deadline else "none", left)),
               color("dim", "graph ~%s (%.1f h)" % (finish_all.strftime("%m-%d %H:%MZ"), makespan_min / 60))],
              width)]
    if not b.cycles:
        return [l1, l1b] + l2
    items = []
    for c in b.cycles:
        span = (c.since.strftime("%H:%MZ") if c.since else "?") + "→" + (c.until.strftime("%H:%MZ") if c.until else "now")
        state = c.outcome or ("healing" if c.milestone in b.healing else "no marker")
        items.append("%s %s %s %s (%s)" % (c.note, c.milestone, span, state, c.window or "?"))
    if LEGEND:
        l3 = pack("", [color("dim", "H heal cycles:")] + items, width, max_rows=3, sep=" · ")
        return [l1, l1b] + l2 + l3
    tally = {}
    for c in b.cycles:
        key = c.outcome or ("healing" if c.milestone in b.healing else "no marker")
        tally[key] = tally.get(key, 0) + 1
    glyph = {"done": "✔", "blocked": "✖", "none": "·", "no marker": "·", "healing": "✚"}
    tone = {"done": "green", "blocked": "red", "healing": "cyan"}
    counts = "  ".join(color(tone.get(k, "dim"), glyph.get(k, "·")) + color("dim", " %d %s" % (v, k))
                       for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))
    n_cyc = len(b.cycles)
    l3 = [fit([" " * LABEL_W + color("dim", "H %d heal cycle%s" % (n_cyc, "" if n_cyc == 1 else "s")),
               counts, color("dim", "last %s" % items[-1])], width)]
    return [l1, l1b] + l2 + l3


def measured_minutes(b):
    p = b.plan
    builder = int(round(p.builder_minutes)) if p.builder_n else p.builder_minutes
    merge = int(round(p.merge_minutes)) if p.merge_n else p.merge_minutes
    return max(1, builder), max(1, merge)


def id_cell(prefix, ids, width):
    shown = 1
    while shown < len(ids):
        rest = len(ids) - (shown + 1)
        trial = "%s %s%s" % (prefix, " ".join(ids[:shown + 1]), " +%d" % rest if rest else "")
        if len(trial) > width:
            break
        shown += 1
    rest = len(ids) - shown
    return "%s %s%s" % (prefix, " ".join(ids[:shown]), " +%d" % rest if rest else "")


def building(b):
    out = []
    for tid, (state, elapsed) in b.states.items():
        if state in IN_FLIGHT:
            t = b.by_id[tid]
            out.append((tid, "review" if t.review else (t.lane or "?"), elapsed or 0, state))
    return sorted(out, key=lambda r: -r[2])


def token(b, tid):
    state = gk(b.states.get(tid, ("waiting", None))[0])
    return color(KIND.get(state, "dim"), GLYPH.get(state, "·") + tid)


def table_groups(b):
    return b.groups() or [(b.focus, b.waves_of(b.focus))]


def focus_remaining(b):
    w = b.plan.projected.get(b.focus)
    return max(0.0, (w.end - b.now).total_seconds() / 60) if w and w.end else 0.0


def since_text(b, t):
    return hm((b.now - t).total_seconds() / 60) if t else "?"


def life(b, s):
    if not s.last:
        return ""
    back = (b.now - s.last).total_seconds()
    return ("●" if back < 30 else "◉" if back < 120 else "○" if back < 600 else "·") + " "


def now_row(b, width):
    pace = measured_minutes(b)[0]
    parts = [C["yellow"] + label("now")
             + color("yellow", b.now.strftime("%H:%MZ")) + " " + color("dim", heartbeat(b.now))]
    for m in msort(b, b.running):
        parts.append(life(b, b.running[m]) + "orchestrator %s for %s" % (m, since_text(b, b.running[m].since)))
    for m in msort(b, b.healing):
        parts.append(life(b, b.healing[m]) + color("cyan", "healer on %s" % m)
                     + " for %s" % since_text(b, b.healing[m].since))
    for s in b.walkers:
        parts.append("walker for %s" % since_text(b, s.since))
    for tid, lane, elapsed, state in building(b)[:4]:
        verb = "merging" if state == "merging" else "building"
        parts.append("%s %s on %s for %s" % (verb, token(b, tid), lane, color(ramp(elapsed, pace), hm(elapsed))))
    if len(parts) == 1:
        last = b.project.last_activity
        merged = max((t for t in b.tasks if t.merged), key=lambda t: t.merged, default=None)
        parts.append(color("dim", "nothing runs" + (" since %s" % last.strftime("%H:%MZ") if last else "")))
        if merged:
            parts.append(color("dim", "last merge %s at %s" % (merged.id, merged.merged.strftime("%H:%MZ"))))
    return fit(parts, width)


def blocked_row(b, width):
    stuck = [tid for tid, (st, _e) in sorted(b.states.items()) if st == "blocked"]
    n_open = sum(b.blocked_ms.values())
    if not stuck and not n_open:
        return fit([label("blocked") + color("green", "nothing blocked")], width)
    parts = [C["red"] + label("blocked")
             + (" ".join(token(b, t) for t in stuck) if stuck else color("dim", "no task held"))]
    if n_open:
        parts.append(color("red", "%d open blocker row%s" % (n_open, "" if n_open == 1 else "s"))
                     + " (%s)" % ", ".join(msort(b, b.blocked_ms)))
        parts.append(color("cyan", "the healer triages them now") if any(m in b.healing for m in b.blocked_ms)
                     else "they wait for the healer")
    return fit(parts, width)


def blocker_rows(b, width, most=4):
    out = []
    for r in b.blockers[:most]:
        held = (token(b, r.task) + " " + node_name(b, r.task)) if r.task in b.by_id else color("dim", "no task named")
        out.append(fit([" " * LABEL_W + color("red", "row %s" % r.id) + "  " + held,
                        "class (%s), %s answers, since %s" % (r.kind, r.who, r.since),
                        color("dim", r.text)], width, sep="  "))
    if len(b.blockers) > most:
        more = "+%d more open blocker rows" % (len(b.blockers) - most)
        out.append(cut(" " * LABEL_W + color("dim", more), width))
    return out


def next_row(b, width, remaining_ms=None):
    queued = [tid for _m, ws in table_groups(b) for w in ws for tid in w.tasks if b.states[tid][0] in QUEUED]
    ready = [t for t in queued if b.states[t][0] == "ready"]
    if ready:
        tail = color("dim", " ready to dispatch")
        shown = len(ready)
        while shown > 1 and LABEL_W + sum(len(t) + 2 for t in ready[:shown]) + 8 + visible_len(tail) > width:
            shown -= 1
        head = " ".join(token(b, t) for t in ready[:shown]) + tail
        if len(ready) > shown:
            head += color("dim", "   +%d more" % (len(ready) - shown))
    else:
        head = color("dim", "no row is ready to dispatch")
    parts = [C["blue"] + label("next") + head]
    if not ready and queued:
        waits = sorted({d for t in queued for d in b.by_id[t].depends if d not in b.done}, key=idkey)
        parts.append(color("dim", "the next rows wait for ") + id_cell("", waits, 30).strip())
    return fit(parts, width)


def critical_tasks(b):
    return set(b.plan.critical)


def graph_model(b):
    ids, seen = [], set()
    for _m, g_waves in table_groups(b):
        for w in g_waves:
            for tid in w.tasks:
                if tid not in seen and tid not in b.done:
                    seen.add(tid)
                    ids.append(tid)
    for m, _w in table_groups(b):
        for tid in b.ms_tasks.get(m, ()):
            if tid not in seen and tid not in b.done:
                seen.add(tid)
                ids.append(tid)
    layer = {}

    def depth(i, trail=()):
        if i not in layer:
            deps = [d for d in b.by_id[i].depends if d in seen and d not in trail]
            layer[i] = 1 + max((depth(d, trail + (i,)) for d in deps), default=-1)
        return layer[i]
    for i in ids:
        depth(i)
    edges = sorted({(d, i) for i in ids for d in b.by_id[i].depends if d in seen})
    groups = []
    for m, _w in table_groups(b):
        for n, wids in b.static_waves(m):
            if wids and all(t in b.done for t in wids):
                groups.append("%s w%d %d done" % (model.ms_number(m), n, len(wids)))
    rank = {m: k for k, m in enumerate(b.order)}
    order = sorted(ids, key=lambda i: (layer[i], rank.get(b.by_id[i].milestone, len(rank)), i))
    front = {d for i in ids for d in b.by_id[i].depends if d in b.done}
    front = sorted(sorted(front), key=lambda d: b.by_id[d].merged or b.now, reverse=True)[:6]
    if front:
        into = {(d, i) for i in ids for d in b.by_id[i].depends if d in front}
        edges = sorted(set(edges) | into)
        groups = []
        return [(d, 0) for d in front] + [(i, layer[i] + 1) for i in order], edges, groups
    return [(i, layer[i]) for i in order], edges, groups


def done_boxes(b, room):
    out = []
    for m, _w in table_groups(b):
        done = [(n, len(wids)) for n, wids in b.static_waves(m) if wids and all(t in b.done for t in wids)]
        if not done:
            continue
        runs = [[done[0]]]
        for n, k in done[1:]:
            if n == runs[-1][-1][0] + 1 and len(done) > room:
                runs[-1].append((n, k))
            else:
                runs.append([(n, k)])
        lines = [("w%d" % r[0][0] if len(r) == 1 else "w%d-w%d" % (r[0][0], r[-1][0])).ljust(7)
                 + "%d done" % sum(k for _n, k in r) for r in runs]
        mine = b.ms_tasks.get(m, ())
        count = "%d of %d tasks" % (len([t for t in mine if t in b.done]), len(mine))
        out.append(("%s done" % m, [count] + lines[:max(1, room - 1)]))
    return out


def node_name(b, tid):
    t = b.by_id.get(tid)
    return t.name if t else ""


BOX_IN = 15


def wrap_words(text, width):
    out, cur = [], ""
    for word in text.split():
        pieces = [p for p in re.findall(r"[^_\-./]*[_\-./]?", word) if p]
        for n, piece in enumerate(pieces):
            join = " " if cur and n == 0 else ""
            if len(cur) + len(join) + len(piece) <= width:
                cur += join + piece
                continue
            if cur:
                out.append(cur)
            while len(piece) > width:
                out.append(piece[:width])
                piece = piece[width:]
            cur = piece
    if cur:
        out.append(cur)
    return out or [""]


def box_lines(b, tid, crit, detail):
    state, elapsed = b.states.get(tid, ("waiting", None))
    t = b.by_id.get(tid) or model.Task(tid)
    running = elapsed and state in IN_FLIGHT
    head = tid + (" " + CRIT if tid in crit else "") + (" " + hm(elapsed) if running else "")
    if state == "blocked":
        head += " holds %d" % len(held_by(b, tid))
    name = t.name
    lines = [head + " " + name] if len(head) + 1 + len(name) <= BOX_IN else [head] + wrap_words(name, BOX_IN)
    if detail:
        lane = "main" if t.review else t.lane
        miss = [d for d in t.depends if d not in b.done]
        more = (" +%d" % (len(miss) - 1)) if len(miss) > 1 else ""
        why = "waits " + miss[0] + more if miss else ("done" if state == "done" else "ready")
        why = t.why or why
        lines += [x for x in ("%s, %s" % (lane, why), why) if len(x) <= BOX_IN][:1]
    return lines


def task_graph(b, width, rows):
    nodes, edges, _groups = graph_model(b)
    crit = critical_tasks(b)
    groups = done_boxes(b, max(1, rows - 2))
    if not nodes and not groups:
        return [cut(color("dim", "  no open task: every task of the open milestones is done"), width)] \
            + [""] * max(0, rows - 1)
    boxes, count = [], {}
    for tid, _lay in nodes:
        ms = b.by_id[tid].milestone if tid in b.by_id else ""
        count[ms] = count.get(ms, 0) + 1
    most = max(count, key=count.get) if count else ""
    for tid, lay in nodes:
        state = b.states.get(tid, ("waiting", None))[0]
        tone = "blue" if state == "ready" else KIND.get(gk(state), "dim")
        full, short = box_lines(b, tid, crit, True), box_lines(b, tid, crit, False)
        t = b.by_id.get(tid)
        head = GLYPH.get(gk(state), "·") + (" " + t.milestone if t and t.milestone != most else "")
        if state == "blocked":
            row = next((r for r in b.blockers if r.task == tid and r.opened), None)
            head = GLYPH["blocked"] + (" " + hm((b.now - row.opened).total_seconds() / 60) if row else "")
        tone = "critical" if tid in crit else tone
        boxes.append(dash_layout.Node(tid, short, full[len(short):], head, tone, tid in crit, lay))
    blocked = {t.id for t in b.tasks if t.state == model.State.BLOCKED}
    held = set(blocked).union(*[held_by(b, x) for x in blocked]) if blocked else set()
    d = dash_layout.layout(boxes, edges, width, rows, dash_layout.Style(box_in=BOX_IN),
                           [("✔ " + title, ls, "green") for title, ls in groups],
                           dashed={(s, t) for s, t in edges if s in held})
    b.graph_drawn = {"nodes": list(d.boxes), "hidden": d.hidden, "edges": d.edges, "layers": d.layers,
                     "total": d.total, "continued": d.continued, "boxes": d.boxes, "extra": d.extra,
                     "drawing": d, "given": boxes}
    out = []
    for row in d.cells:
        line, last = "", None
        for ch, tone in row:
            tone = "critical" if ch == CRIT else tone
            if tone != last:
                line += C["reset"] + ("" if tone == "default" else C.get(tone, ""))
                last = tone
            line += ch
        out.append(cut(line.rstrip() + C["reset"], width))
    return out


def status_rows(b, width, remaining_ms, makespan):
    g = b.project.gate
    day = [color("dim", "no whole gate in the last 24 h")]
    if g:
        failed = [STEP_NAMES[k] for k, s in enumerate(g.steps) if s == "fail" and k < len(STEP_NAMES)]
        verdict = "passed" if g.passed else "failed" + (" in " + " and ".join(failed) if failed else "")
        gate = steps_marks(g) + " " + color(health(g.passed), verdict) \
            + " at %s on %s" % (when(b, g.time) if g.time else "?", g.subject)
        gates = b.project.gates
        if gates:
            shown = gates[-DAY_GATES:]
            day = [("24 h " if len(shown) == len(gates) else "24 h, the last %d of %d " % (len(shown), len(gates)))
                   + "".join(color("green", "✔") if x.passed else color("red", "✖") for x in shown)
                   + " %d of %d passed" % (len([x for x in shown if x.passed]), len(shown))]
            if len(gates) > 1 and g.acceptance and gates[0].acceptance:
                day.append(color("dim", "acceptance %d, %+d in 24 h" % (g.acceptance, g.acceptance - gates[0].acceptance)))
    else:
        gate = color("dim", "no whole gate yet")
    cells, gone, live = [], [], []
    for lane, cap in b.plan.lanes.items():
        slots = [lk for lk in b.locks if lk.lane == lane]
        marks = "".join(color("yellow", "▶") if lk.live else color("red", "✖") for lk in slots)
        cells.append("%s %s" % (lane, marks + color("dim", "·" * max(0, cap - len(slots)))))
        gone += ["%s since %s" % (lk.holder, lk.since.strftime("%H:%MZ") if lk.since else "?")
                 for lk in slots if not lk.live]
        live += [lk.holder for lk in slots if lk.live]
    lanes = [label("lanes") + "  ".join(cells)]
    lanes += [color("red", "✖") + " held by a gone session: " + ", ".join(gone)] if gone else []
    lanes += [color("yellow", "▶") + " " + " ".join(live)] if live else []
    main = [lk for lk in b.locks if lk.name.startswith("main") and lk.live]
    lock = (color("yellow", "main lock: %s for %s" % (main[0].holder, since_text(b, main[0].since)))
            if main else color("dim", "main lock free"))
    use = usage_text(b)
    use = color("dim", "unknown") if ANSI.sub("", use) == "usage unknown" else use.replace(color("dim", "usage "), "", 1)
    return [fit([label("gate") + gate, lock] + day, width), fit(lanes, width),
            fit([label("usage") + use, "HEAD " + color("bold", b.project.head), "%d of %d milestones tagged" % (len([m for m in b.order if "ms-" + model.ms_number(m) in b.project.tags]),
                                                                             len(b.order))],
                width), day_row(b, width)] + estimate_rows(b, width)


def held_by(b, tid):
    kids = {}
    for e in b.edges:
        kids.setdefault(e.source, []).append(e.target)
    seen, todo = set(), [tid]
    while todo:
        for k in kids.get(todo.pop(), ()):
            if k not in seen and k not in b.done:
                seen.add(k)
                todo.append(k)
    return seen


def day_row(b, width):
    day = b.now - datetime.timedelta(hours=24)
    merged = len([t for t in b.tasks if t.merged and day < t.merged <= b.now])
    added = len([t for t in b.tasks if t.added and day < t.added <= b.now])
    rows = b.project.blocker_rows
    opened = len([r for r in rows if r.opened and day < r.opened <= b.now])
    closed = len([r for r in rows if r.closed and day < r.closed <= b.now])
    heals = len([s for s in b.sessions if s.role == "heal cycle" and s.since and day < s.since <= b.now])
    return fit([label("24 h") + color("green", "✔") + " %d merged" % merged, "%d task rows added" % added,
                color("red", "✖") + " %d blocker rows opened, %d closed" % (opened, closed),
                color("cyan", "✚") + " %d heal cycle%s" % (heals, "" if heals == 1 else "s")], width)


STEP_NAMES = ("guard", "index", "ruff", "mypy", "unit", "acceptance", "string lint")
DAY_GATES = 24


def steps_marks(g):
    return "".join(color("green", "✔") if s == "pass" else color("red", "✖") if s == "fail" else " "
                   for s in g.steps) if g.steps else ""


def when(b, t):
    return t.strftime("%H:%MZ") if t.date() == b.now.date() else t.strftime("%m-%d %H:%MZ")


def quartiles(values):
    return tuple(statistics.quantiles(sorted(values), n=4)) if len(values) >= 2 else None


RATE_HOURS, RATE_STEP = 72, 6


def merge_rate(b, hours=RATE_HOURS, step=RATE_STEP):
    bins = [0] * (hours // step)
    for t in b.tasks:
        back = (b.now - t.merged).total_seconds() / 3600 if t.merged else -1
        if 0 <= back < hours:
            bins[len(bins) - 1 - int(back // step)] += 1
    return sum(bins), bins


def spark(counts):
    top = max(list(counts) + [1])
    return "".join(STEPS[max(1, -(-7 * k // top))] if k else " " for k in counts)


def estimate_rows(b, width):
    p = b.plan
    open_n = len([t for t in b.tasks if t.state != model.State.DONE])
    if p.finish and open_n:
        first = "all %d open task%s land ~%s" % (open_n, "" if open_n == 1 else "s", when(b, p.finish))
        fs = p.finish_spread or model.Window()
        if fs.start and fs.end:
            first += color("dim", ", p25 %s to p75 %s" % (when(b, fs.start), when(b, fs.end)))
    else:
        first = color("green", "no open task")
    merged, bins = merge_rate(b)
    parts = [label("estimate") + first]
    if merged and open_n and p.finish:
        at_rate = b.now + datetime.timedelta(hours=open_n * RATE_HOURS / merged)
        late = (at_rate - p.finish).total_seconds() / 3600
        gap = ("%d h later" % round(late)) if late >= 0.5 else ("%d h earlier" % round(-late)) if late <= -0.5 \
            else "the same time"
        parts.append("at the merge rate of the last %d h ~%s: " % (RATE_HOURS, when(b, at_rate))
                     + color("amber" if late > 12 else "dim", gap))
    elif open_n:
        parts.append(color("dim", "no task merged in the last %d h, so no rate" % RATE_HOURS))
    q = quartiles(b.plan.builder_samples) if p.builder_n else None
    builder = ("%.0f min (n=%d)" % (p.builder_minutes, p.builder_n)) if p.builder_n \
        else "%d min, the planner's" % p.builder_minutes
    if q:
        builder += ", p25 %.0f, p75 %.0f" % (q[0], q[2])
    merge = ("%.0f min (n=%d)" % (p.merge_minutes, p.merge_n)) if p.merge_n \
        else "%g min, the planner's" % p.merge_minutes
    rate = "%d, %.2f an hour" % (merged, merged / RATE_HOURS) if merged else "none"
    second = [" " * LABEL_W + color("dim", "merged per %d h over %d h " % (RATE_STEP, RATE_HOURS))
              + color("green", spark(bins)) + color("yellow", "│") + color("dim", " " + rate),
              "builder " + builder, "merge " + merge]
    return [fit(parts, width), fit(second, width)]


LEGEND_ITEMS = (("green", "✔ done, passed"), ("yellow", "▶ building"), ("yellow", "≡ merging"), ("yellow", "◆ review"),
                ("blue", "· ready"), ("dim", "◌ waiting"),
             ("red", "✖ blocked, failed"), ("cyan", "✚ healing"),
                ("green", "█ in plan"), ("amber", "▒ past plan"), ("dim", "░ projected"), ("red", "▚ stuck"),
                ("critical", "» ┏┓ critical"), ("dim", "◂ before"), ("yellow", "│▼ now"), ("dim", "┬ day, 2 h"),
                ("dim", "─┼►◄ depends on"), ("dim", "↳ continued"), ("dim", "↻ reset"), ("dim", "× ratio"),
                ("dim", "→ to"), ("dim", "+n more, words left out"), ("dim", "⠋ live"), ("bold", "═ wave, tag, session"),
                ("dim", "●◉○ last act 30 s, 2 min, 10 min"), ("dim", "▁▇ a count, one scale to a row"),
                ("dim", "╌╎ held by a blocker"), ("dim", "─│─ crossing"))


def legend_rows(width):
    return pack("key", [color(tone, text) for tone, text in LEGEND_ITEMS], width, max_rows=3, sep="  ")


STEPS = " ▁▂▃▄▅▆▇"


def walk_rows(b, width):
    walks = b.project.walks
    if not walks or not walks[0].start or (b.now - walks[0].start).total_seconds() > 86400:
        return []
    w = walks[0]
    top = max(list(w.stages.values()) + [1])
    cells = []
    for n in range(13):
        k = w.stages.get("S%d" % n, 0)
        mark = STEPS[max(1, round(7 * math.log1p(k) / math.log1p(top)))] if k else "·"
        cells.append("S%d%s" % (n, color("yellow" if k else "dim", mark)))
    verdict = {"PASS": color("green", "✔ passed"), "FAIL": color("red", "✖ failed")}.get(
        w.verdict, color("dim", "no verdict"))
    times = "%s→%s" % (w.start.strftime("%H:%MZ"), w.end.strftime("%H:%MZ") if w.end else "now")
    row1 = fit([label("walk") + "%s %s" % (w.task, times), " ".join(cells), "%d notes" % w.notes,
                "last %s" % w.last if w.last else "", verdict], width)
    verdicts = [x.verdict for x in walks if x.verdict]
    fails = "all failed" if verdicts and set(verdicts) == {"FAIL"} else ", ".join(verdicts)
    row2 = fit([" " * LABEL_W + color("dim", "depth of the last %d walks: %s" % (len(walks), " ".join(
                x.depth or "·" for x in walks))), color("dim", "%d with a verdict%s" % (len(verdicts),
                                                       ", " + fails if fails else ""))], width)
    return [row1, row2]


def render(width, height, b=None):
    b = b or Build()
    remaining_ms = focus_remaining(b)
    makespan = max(0.0, (b.plan.finish - b.now).total_seconds() / 60) if b.plan.finish else 0.0
    head = [now_row(b, width), blocked_row(b, width), next_row(b, width, remaining_ms)]
    head += blocker_rows(b, width) + walk_rows(b, width)
    status = status_rows(b, width, remaining_ms, makespan)
    legend = legend_rows(width)
    room = max(3, height - len(head) - 1 - 1 - len(status) - len(legend))
    L = head + [section("task graph: what was done → what runs now → what is next", width)]
    L += task_graph(b, width, room)
    L += [section("status", width)] + status + legend
    return (L + [""] * max(0, height - len(L)))[:height]


def screen():
    width, height = pane_size()
    try:
        if not SOURCE:
            SOURCE.append(load_source())
        return render(width, height, Build(SOURCE[0])), (width, height)
    except Exception as exc:
        return ["dashboard error: %r (it retries at the next refresh)" % (exc,)], (width, height)


RESIZED = [False]


def on_winch(_signum, _frame):
    RESIZED[0] = True


def nap(secs):
    end = time.time() + secs
    while time.time() < end:
        if RESIZED[0]:
            RESIZED[0] = False
            time.sleep(0.2)
            RESIZED[0] = False
            return
        time.sleep(0.1)


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


def _reload_if_changed(stamp):
    try:
        for path, mtime in stamp:
            if not os.path.exists(path) or os.stat(path).st_mtime != mtime:
                sys.stdout.flush()
                os.execv(sys.executable, [sys.executable] + sys.argv)
    except OSError:
        pass

def main():
    if "--legend" in sys.argv:
        globals()["LEGEND"] = True
    if "--loop" in sys.argv:
        secs = float(os.environ.get("TMUX_TUI_DASHBOARD_PROGRESS_SECONDS", "2"))
        try:
            signal.signal(signal.SIGWINCH, on_winch)
        except (AttributeError, ValueError, OSError):
            pass
        frame, _stamp = Frame(), None
        while True:
            rows, size = screen()
            data = frame.paint(rows, size)
            if data:
                sys.stdout.write(data)
                sys.stdout.flush()
            _stamp = _stamp or _sources()
            _reload_if_changed(_stamp)
            nap(secs)
    else:
        print("\n".join(screen()[0]))


if __name__ == "__main__":
    main()
