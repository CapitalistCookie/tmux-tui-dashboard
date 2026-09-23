"""The middle pane: the milestones as a Gantt chart on two time scales, the project in days and the
open waves 12 hours back and ahead.

  python3 -m tmux_tui_dashboard.phases [--loop] [--rows]
"""
import bisect
import datetime
import os
import re
import signal
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.abspath(__file__))
from tmux_tui_dashboard import progress as P
from tmux_tui_dashboard import palette
from tmux_tui_dashboard import model

C = palette.C
TICKS = (60, 120, 180, 360, 720, 1440, 2880, 4320)
IN_PLAN, PAST_PLAN, PROJECTED, BLOCKED, NOW_LINE = "█", "▒", "░", "▚", "│"
CRIT, BEFORE = "»", "◂"
LBL = 8
BAND_MAX = 100
ZOOM_W = 48
ZOOM_HOURS = 12
ROWS_MAX = 30
STREAM_MIN = 17
ROWS = 15
KIND = {"done": "green", "building": "yellow", "healing": "cyan", "blocked": "red", "ready": "blue", "waiting": "dim"}
MS_GLYPH = {"done": "✔", "building": "▶", "healing": "✚", "blocked": "✖", "ready": "·", "waiting": "◌"}


dur = P.dur


def paint(tone, text):
    return C.get(tone, "") + text + C["reset"]


def first_fit(texts, width):
    for text in texts:
        text = " ".join((text or "").split())
        if text and P.visible_len(text) <= width:
            return text
    return ""


def forms(ms):
    head = re.sub(r"\s*\([^)]*\)", "", ms.title.split(":")[0]).strip()
    items = re.split(r",\s+|\s+and\s+", head)
    lead = [", ".join(items[:k]) for k in range(len(items) - 1, 0, -1)]
    return [description((ms.title, ms.purpose)), ms.title, head] + lead


def day(t):
    return t.strftime("%m-%d") if t else "-"


def window(a, z, open_end=False):
    if not a:
        return "-"
    return "%s→%s" % (day(a), "now" if open_end else day(z))


def slip_text(minutes):
    if minutes is None:
        return "-"
    if abs(minutes) < 30:
        return "on plan"
    sign = "+" if minutes > 0 else "-"
    m = abs(minutes)
    return sign + ("%dm" % m if m < 60 else "%dh" % round(m / 60) if m < 2880 else "%.1fd" % (m / 1440))


def description(block):
    name, purpose = block
    return name + (". " + purpose if purpose else "")


SOURCE = []


def planned(b, m):
    ms = b.ms_by_id.get(m)
    return ms.minutes if ms else 0


def spans(b):
    out = []
    for m in b.order:
        ms, state = b.ms_by_id[m], b.ms_state(m)
        ids = b.ms_tasks[m]
        done = len([t for t in ids if t in b.done])
        if state == "done":
            t0 = ms.actual.start or b.now
            t1 = ms.actual.end or b.now
            out.append((m, state, done, len(ids), t0, max(t1, t0), True))
        else:
            w = b.plan.projected.get(m) or model.Window(b.now, b.now)
            t0 = w.start or b.now
            out.append((m, state, done, len(ids), t0, max(w.end or t0, t0), False))
    return out


def axis_step(span_min, bar_w):
    for step in TICKS:
        if bar_w and step / max(1e-9, span_min / bar_w) >= 7:
            return step
    return TICKS[-1]


def band(col, width, start=None, end=None, plan_end=None, projected=None, kind="dim", blocked=False):
    cells = [(" ", "dim")] * width
    if start is not None and end is not None:
        a, z = col(start), col(end)
        p = col(plan_end) if plan_end is not None else a - 1
        for x in range(max(0, a), min(width - 1, max(a, z)) + 1):
            if blocked:
                cells[x] = (BLOCKED, "red")
            else:
                cells[x] = (IN_PLAN, kind) if x <= p else (PAST_PLAN, "amber")
        if a < 0 <= z:
            cells[0] = (BEFORE, cells[0][1])
    if projected:
        a, z = col(projected[0]), col(projected[1])
        for x in range(max(0, a), min(width - 1, max(a, z)) + 1):
            if cells[x][0] == " ":
                cells[x] = (PROJECTED, "dim")
    return cells


def draw(cells, now_col):
    cells = list(cells)
    if 0 <= now_col < len(cells):
        ch, _tone = cells[now_col]
        cells[now_col] = (NOW_LINE if ch == " " else ch, "yellow")
    out, last = "", None
    for ch, tone in cells:
        if tone != last:
            out += C["reset"] + C.get(tone, "")
            last = tone
        out += ch
    return out + C["reset"]


def label_bar(cells, text_of, now_col):
    used = [x for x, (ch, _t) in enumerate(cells) if ch != " "]
    if not used:
        return cells, ""
    a, z = used[0], used[-1]
    after_room = max(0, min(len(cells), now_col - 1 if now_col > z else len(cells)) - (z + 2))
    before_room = max(0, a - 1)
    after, before = text_of(after_room), text_of(before_room)
    cells = list(cells)
    if after and len(after) >= len(before):
        for i, ch in enumerate(after):
            cells[z + 2 + i] = (ch, "dim")
        return cells, after
    if before:
        x0 = a - 1 - len(before)
        for i, ch in enumerate(before):
            cells[x0 + i] = (ch, "dim")
        return cells, before
    return cells, ""


def ms_state(b, m):
    if b.ms_state(m) == "done":
        return "done", ""
    open_ids = [t for t in b.ms_tasks.get(m, ()) if t not in b.done]
    rows = b.blocked_ms.get(m, 0)
    stuck = [t for t in open_ids if b.states[t][0] == "blocked"]
    live = [t for t in open_ids if b.states[t][0] in model.IN_FLIGHT]
    held = ("%d blocker row%s" % (rows, "" if rows == 1 else "s")) if rows else ""
    if stuck:
        held += (", " if held else "") + "%s cannot move" % P.id_cell("", stuck, 26).strip()
    if m in b.healing:
        return "healing", "the healer is at work" + ("; " + held if held else "")
    if held:
        return "blocked", held
    if live:
        return "building", ", ".join("%s %s" % (b.states[t][0], t) for t in live[:3])
    ready = [t for t in open_ids if b.states[t][0] == "ready"]
    if ready:
        return "ready", P.id_cell("", ready, 30).strip()
    miss = sorted({d for t in open_ids for d in b.by_id[t].depends if d not in b.done and d not in open_ids},
                  key=P.idkey)
    if miss:
        owners = P.msort(b, {b.by_id[d].milestone if d in b.by_id else "?" for d in miss})
        return "waiting", "waits %s (%s)" % (", ".join(owners), P.id_cell("", miss, 22).strip())
    return "waiting", ""


def open_milestones(b):
    return [m for m in b.order if any(t not in b.done for t in b.ms_tasks.get(m, ()))
            and (b.ms_by_id[m].actual.start or m == b.focus)]


def wave_rows(b, m):
    _builder, merge = P.measured_minutes(b)
    out, cursor = [], b.now
    for w in b.waves_of(m):
        placed = [b.plan.schedule.get(i) for i in w.tasks if i not in b.done]
        ids = list(w.tasks)
        if not ids or all(i in b.done for i in ids):
            continue
        state = {i: b.states.get(i, ("waiting", None)) for i in ids}
        spent = [el for st, el in state.values() if el and st in ("building", "merging", "blocked")]
        run = [el or 0 for st, el in state.values() if st in model.IN_FLIGHT]
        left = max(merge, w.paced - max(run)) if run else w.paced
        start = b.now - datetime.timedelta(minutes=max(spent)) if spent else None
        plan = w.minutes
        stuck = any(st == "blocked" for st, _e in state.values()) and not run
        proj = (cursor, cursor + datetime.timedelta(minutes=left))
        if placed and all(x and x.start and x.end for x in placed):
            proj = (max(b.now, min(x.start for x in placed)), max(x.end for x in placed))
        out.append({"label": "%s w%d" % (model.ms_number(m), w.n), "ids": ids, "ms": m, "start": start,
                    "spent": max(spent) if spent else None, "plan": plan, "blocked": stuck,
                    "plan_end": start + datetime.timedelta(minutes=plan) if start and plan else None,
                    "proj": proj})
        cursor += datetime.timedelta(minutes=left)
    return out


def fold(rows, keep):
    if len(rows) <= keep or keep < 1:
        return rows[:max(0, keep)]
    head, rest = rows[:keep - 1], rows[keep - 1:]
    starts = [r["start"] for r in rest if r["start"]]
    spent = [r["spent"] for r in rest if r["spent"]]
    plan = sum(r["plan"] for r in rest)
    start = min(starts) if starts else None
    first, last = rest[0]["label"].split()[-1], rest[-1]["label"].split()[-1][1:]
    return head + [{"label": "%s %s-%s" % (rest[0]["label"].split()[0], first, last), "ms": rest[0]["ms"],
                    "ids": [i for r in rest for i in r["ids"]], "start": start, "plan": plan,
                    "spent": max(spent) if spent else None, "blocked": all(r["blocked"] for r in rest),
                    "plan_end": start + datetime.timedelta(minutes=plan) if start and plan else None,
                    "proj": (min(r["proj"][0] for r in rest), max(r["proj"][1] for r in rest))}]


def wave_kind(b, ids):
    states = [b.states.get(i, ("waiting", None))[0] for i in ids if i not in b.done]
    for st, tone in (("blocked", "red"), ("building", "yellow"), ("merging", "yellow")):
        if st in states:
            return tone
    return "dim"


def task_token(b, tid, crit, brief=False):
    state, elapsed = b.states.get(tid, ("waiting", None))
    t = b.by_id.get(tid) or model.Task(tid)
    if brief:
        head = paint(P.KIND.get(P.gk(state), "dim"), P.GLYPH.get(P.gk(state), "·") + tid)
        return head + (paint("critical", CRIT) if tid in crit else "") + " " + (t.name or t.short)
    bits = [t.name or t.short, "main" if t.review else (t.lane or "?")]
    if elapsed and state not in ("done",) + model.QUEUED:
        bits.append(P.hm(elapsed))
    if state == "blocked":
        bits.append(t.why or "blocker row")
    elif state in model.QUEUED:
        miss = [d for d in t.depends if d not in b.done]
        bits.append(("waits " + " ".join(miss[:2]) + (" +%d" % (len(miss) - 2) if len(miss) > 2 else ""))
                    if miss else "ready")
    head = paint(P.KIND.get(P.gk(state), "dim"), P.GLYPH.get(P.gk(state), "·") + tid)
    return head + (paint("critical", CRIT) if tid in crit else "") + " " + " ".join(bits)


def tokens_fit(parts, width, sep="  ", first=None):
    out, n = [], 0
    if first and parts and P.visible_len(parts[0]) + len("%s+%d more" % (sep, len(parts) - 1)) * (len(parts) > 1) > width:
        parts = [first] + list(parts[1:])
    for k, part in enumerate(parts):
        rest = len(parts) - k - 1
        more = ("%s+%d more" % (sep, rest)) if rest else ""
        add = P.visible_len(part) + (len(sep) if out else 0)
        if n + add + len(more) > width:
            tail = "+%d more" % (len(parts) - k)
            fits = n + len(sep) + len(tail) <= width
            return sep.join(out) + ((sep if out else "") + paint("dim", tail) if fits else "")
        out.append(part)
        n += add
    return sep.join(out)


def columns(width_count):
    return (11, 11, 7, width_count, 8)


BURN_DAYS = 1


def burnup_wanted(b, m):
    ms = b.ms_by_id.get(m)
    first = ms.actual.start if ms else None
    return (b.ms_state(m) != "done" and first is not None and (b.now - first).days >= BURN_DAYS
            and any(b.by_id[i].added for i in b.ms_tasks.get(m, ()) if i in b.by_id))


def layout(b, height=None):
    budget = ROWS_MAX if height is None else height
    done = [m for m in b.order if b.ms_state(m) == "done"]
    ms_rows = 1 + 2 + sum(1 if m in done else 2 + 2 * burnup_wanted(b, m) for m in b.order) \
        + (1 if b.project.blocker_rows else 0)
    groups = []
    for m in open_milestones(b):
        rows = wave_rows(b, m)
        if rows:
            groups.append((m, rows))
    want = ms_rows + (4 + sum(len(r) for _m, r in groups) if groups else 0)
    fold_n = min(len(done), want - budget + 1) if want > budget and len(done) > 1 else 0
    if fold_n > 1:
        ms_rows -= fold_n - 1
    else:
        fold_n = 0
    wave_room = budget - ms_rows - 4
    out = []
    for k, (m, rows) in enumerate(groups):
        share = max(1, wave_room - sum(len(r) for _m, r in out) - (len(groups) - k - 1))
        out.append((m, fold(rows, share)))
    out = [(m, r) for m, r in out if r]
    if wave_room < 1:
        out = []
    return ms_rows, out, done[:fold_n]


def rows_cap():
    session = os.environ.get("TMUX_TUI_DASHBOARD_TMUX_SESSION", "tmux_tui_dashboard")
    try:
        out = subprocess.run(["tmux", "list-panes", "-t", session + ":build", "-F",
                              "#{pane_top} #{pane_height}"], capture_output=True, text=True,
                             timeout=5).stdout.split("\n")
        panes = sorted(tuple(int(x) for x in line.split()) for line in out if line.strip())
        win = int(subprocess.run(["tmux", "display", "-p", "-t", session + ":build", "#{window_height}"],
                                 capture_output=True, text=True, timeout=5).stdout.strip())
        if len(panes) >= 2:
            return max(ROWS, min(ROWS_MAX, win - panes[0][1] - 2 - STREAM_MIN))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return ROWS_MAX


def rows_for(b, cap):
    ms_rows, groups, _folded = layout(b, cap)
    return max(ROWS, min(cap, ms_rows + (4 + sum(len(r) for _m, r in groups) if groups else 0)))


def rows_needed():
    try:
        return rows_for(P.Build(), rows_cap())
    except (Exception, SystemExit):
        return ROWS


def render(width, height, b=None):
    b = b or P.Build()
    rows = spans(b)
    t_now = b.now
    ms_rows, groups, folded = layout(b, height)
    crit = set(b.plan.critical)
    t0 = min([r[4] for r in rows] + [t_now])
    t1 = max([r[5] for r in rows] + [t_now])
    if (t1 - t0).total_seconds() < 3600:
        t1 = t0 + datetime.timedelta(hours=1)
    span_min = (t1 - t0).total_seconds() / 60

    recs = []
    for m, _st, done, total, s, e, real in rows:
        state, why = ms_state(b, m)
        first = b.ms_by_id[m].actual.start
        begun = bool(first) and not real
        plan_end = b.ms_by_id[m].planned.end
        recs.append({
            "m": m, "state": state, "why": why, "real": real, "begun": begun, "first": first,
            "end": e, "s": s,
            "plan_end": plan_end, "count": "%d/%d" % (done, total),
            "plan": window(first or s, plan_end),
            "actual": window(first, e) if real else window(first, None, open_end=True) if begun else "-",
            "slip": slip_text((e - plan_end).total_seconds() / 60) if (real or begun) and plan_end else "-"})
    fold = fold_rec([r for r in recs if r["m"] in folded])
    for r in recs + ([fold] if fold else []):
        ms = [x["m"] for x in r["rs"]] if "rs" in r else [r["m"]]
        first = min((x["first"] or x["s"]) for x in r["rs"]) if "rs" in r else r["first"]
        last = max(x["end"] for x in r["rs"]) if "rs" in r else (r["end"] if r["real"] else t_now)
        r["hours"], r["spent"] = hours_cells(b, ms, first, last)
    count_w = max([len(r["count"]) for r in recs + ([fold] if fold else [])] + [5])
    cols = [("planned", 11, "plan", "l"), ("actual", 11, "actual", "l"), ("slip", 7, "slip", "r"),
            ("tasks", count_w, "count", "r"), ("state", 8, "state", "l"), ("hours", HOURS_W, "hours", "l")]
    band_w = width - LBL - 1 - 1 - sum(w + 1 for _h, w, _k, _a in cols) + 1
    for drop in ("hours", "planned", "actual", "slip"):
        if band_w >= 24:
            break
        gone = next(c for c in cols if c[0] == drop)
        cols.remove(gone)
        band_w += gone[1] + 1
    band_w = max(0, min(BAND_MAX, band_w))
    x_bar = LBL + 1

    def col(t):
        return int((t - t0).total_seconds() / 60 / span_min * band_w) if band_w else 0
    now_col = max(0, min(band_w - 1, col(t_now))) if band_w else 0

    def figures(r):
        out = []
        for _h, w, key, align in cols:
            text = r[key]
            cell = text if key == "hours" else text.rjust(w) if align == "r" else text.ljust(w)
            out.append(paint(KIND.get(r["state"], "dim"), cell) if key == "state" else cell)
        return " ".join(out)

    L = []
    plan_all, ran_all = P.plan_and_spent(b)
    L.append(P.fit([paint("bold", "milestones") + "  " + paint("dim", "project band %s→%s, ┬ a day" % (
                        day(t0), t1.strftime("%m-%d %H:%MZ"))),
                    paint("dim", "wave band %d h back to %d h ahead of now, ┬ each 2 h"
                          % (ZOOM_HOURS, ZOOM_HOURS)),
                    paint(P.ramp(ran_all, plan_all), "plan %s  spent %s  ×%.0f"
                          % (dur(plan_all), dur(ran_all), ran_all / plan_all if plan_all else 0))], width))

    if band_w:
        step = axis_step(span_min, band_w)
        anchor = t0.replace(hour=0, minute=0, second=0, microsecond=0)
        whole = int((t0 - anchor).total_seconds() / 60 // step)
        first_tick = anchor + datetime.timedelta(minutes=step * whole)
        while first_tick < t0:
            first_tick += datetime.timedelta(minutes=step)
        L += axis_rows(band_w, now_col, first_tick, t1, step, col, "┬", " ",
                       lambda t: t.strftime("%m-%d") if step >= 1440 or t.hour == 0 else t.strftime("%H:%MZ"),
                       " " * x_bar, " " + " ".join((h.rjust(w) if a == "r" else h.ljust(w))
                                                   for h, w, _k, a in cols), width)

    for r in recs:
        m = r["m"]
        if m in folded:
            if m == folded[0]:
                L.append(fold_row(fold, col, band_w, now_col, figures, width))
            continue
        head = paint(KIND.get(r["state"], "dim"), (MS_GLYPH.get(r["state"], "·") + m).ljust(LBL)) + " "
        if band_w:
            if r["real"]:
                cells = band(col, band_w, r["first"] or r["s"], r["end"], r["plan_end"], None, "green")
            elif r["begun"]:
                cells = band(col, band_w, r["first"], t_now, r["plan_end"], (t_now, r["end"]),
                             KIND[r["state"]])
            else:
                cells = band(col, band_w, None, None, None, (r["s"], r["end"]))
            if r["state"] == "done":
                cells, _shown = label_bar(cells, lambda room, ms=b.ms_by_id[m]: first_fit(forms(ms), room), now_col)
            head += draw(cells, now_col) + " "
        L.append(P.cut(head + figures(r), width))
        if r["state"] != "done":
            tail = paint(KIND.get(r["state"], "dim"), r["state"] + (": " + r["why"] if r["why"] else ""))
            if not r["real"]:
                tail += "   " + paint("bold", "tag ~%s" % P.when(b, r["end"]))
            spent = r["spent"]
            if spent and P.visible_len(spent) + P.visible_len(tail) + 3 <= width - x_bar:
                tail = spent + "   " + tail
            room = width - x_bar - P.visible_len(tail) - 3
            desc = first_fit(forms(b.ms_by_id[m]), room) if room >= 12 else ""
            body = (paint("dim", desc.ljust(room)) + "   " if desc else "") + tail
            L.append(P.cut(" " * x_bar + body, width))
            if burnup_wanted(b, m):
                L += burnup_rows(b, m, t0, span_min, band_w, now_col, width)

    if b.project.blocker_rows and band_w:
        L.append(held_row(b, t0, span_min, band_w, now_col, width))
    if groups and band_w:
        zoom_w = max(min(24, band_w), min(ZOOM_W, band_w, width - x_bar - 1 - 16 - 40))
        zs = t_now - datetime.timedelta(hours=ZOOM_HOURS)
        span_z = 2 * ZOOM_HOURS * 60

        def zcol(t):
            return int((t - zs).total_seconds() / 60 / span_z * zoom_w)
        z_now = max(0, min(zoom_w - 1, zcol(t_now)))
        tick = zs.replace(minute=0, second=0, microsecond=0)
        while tick.hour % 2 or tick < zs:
            tick += datetime.timedelta(hours=1)
        detail_w = width - x_bar - zoom_w - 1
        heads = " " + P.cut("finish   tasks  open tasks: id » name lane elapsed why", detail_w)
        heads = heads.replace(CRIT, C["critical"] + CRIT + C["dim"])
        L += axis_rows(zoom_w, z_now, tick, zs + datetime.timedelta(minutes=span_z), 120, zcol, "┬", "─",
                       lambda t: t.strftime("%H:%MZ") if t.hour % 4 == 0 else "",
                       paint("bold", "waves".ljust(LBL)) + " ", heads, width)
        L += run_rows(b, zs, span_z, zoom_w, z_now, zcol, width)
        for m, wrows in groups:
            for w in wrows:
                marked = any(i in crit for i in w["ids"])
                label = ((CRIT if marked else " ") + w["label"]).ljust(LBL)
                cells = band(zcol, zoom_w, w["start"], t_now if w["start"] else None, w["plan_end"],
                             w["proj"], wave_kind(b, w["ids"]), blocked=w["blocked"])
                n_done = len([i for i in w["ids"] if i in b.done])
                fig = "~%s  %5s  " % (w["proj"][1].strftime("%H:%MZ"), "%d/%d" % (n_done, len(w["ids"])))
                toks = [task_token(b, i, crit) for i in w["ids"] if i not in b.done]
                short = task_token(b, toks and [i for i in w["ids"] if i not in b.done][0], crit, brief=True) \
                    if toks else None
                room = width - x_bar - zoom_w - 1 - len(fig)
                label = paint("critical", CRIT) + paint("bold", label[1:]) if marked else paint("dim", label)
                L.append(P.cut(label + " " + draw(cells, z_now) + " "
                               + fig + tokens_fit(toks, room, first=short), width))
    L += phase_tasks(b, width, height - len(L))
    return L[:height]


HOURS_W = 12
RUNS = (("builder", "▶", "yellow"), ("merge", "≡", "yellow"), ("review", "◆", "yellow"), ("heal cycle", "✚", "cyan"))


def hours_cells(b, ms, start, end, samples=96):
    if not start or not end or end <= start:
        return " " * HOURS_W, ""
    def ends(s):
        live = s.role != "heal cycle" or s.milestone in b.healing
        return s.until or (b.now if live else b.project.last_activity or s.since)
    runs = {role: [(s.since, ends(s)) for s in b.sessions if s.role == role and s.milestone in ms and s.since]
            for role, _g, _t in RUNS}
    span = (end - start).total_seconds()
    counts = [0] * (len(RUNS) + 1)
    for k in range(samples):
        t = start + datetime.timedelta(seconds=(k + 0.5) * span / samples)
        kind = next((n for n, (role, _g, _t) in enumerate(RUNS) if any(a <= t < z for a, z in runs[role])), len(RUNS))
        counts[kind] += 1
    exact = [c * HOURS_W / samples for c in counts]
    cells = [int(x) for x in exact]
    for n in sorted(range(len(exact)), key=lambda i: exact[i] - cells[i], reverse=True)[:HOURS_W - sum(cells)]:
        cells[n] += 1
    glyphs = list(RUNS) + [("idle", "·", "dim")]
    text = "".join(paint(tone, g * cells[n]) for n, (_r, g, tone) in enumerate(glyphs) if cells[n])
    hours = lambda c: "%dh" % round(c * span / samples / 3600) if c * span / samples >= 3600 \
        else "%dm" % round(c * span / samples / 60)
    words = "  ".join(paint(tone, g) + " " + hours(counts[n]) for n, (_r, g, tone) in enumerate(glyphs) if counts[n])
    return text, (words + " nothing ran" if counts[-1] else words)


def run_rows(b, zs, span_z, zoom_w, z_now, zcol, width):
    step = span_z / zoom_w
    builders, healing, merged = [0] * zoom_w, [False] * zoom_w, [0] * zoom_w
    runs = [(s.since, s.until or b.now) for s in b.sessions if s.role == "builder" and s.since]
    heals = [(s.since, s.until or (b.now if s.milestone in b.healing else b.project.last_activity or s.since))
             for s in b.sessions if s.role == "heal cycle" and s.since]
    for c in range(max(0, z_now)):
        a = zs + datetime.timedelta(minutes=c * step)
        z = a + datetime.timedelta(minutes=step)
        builders[c] = sum(1 for x, y in runs if x < z and y > a)
        healing[c] = any(x < z and y > a for x, y in heals)
    landed = sorted((t.merged, t.id) for t in b.tasks if t.merged and zs <= t.merged <= b.now)
    for when, _tid in landed:
        merged[max(0, min(zoom_w - 1, zcol(when)))] += 1
    top = max(builders + [1])
    ran = [(P.STEPS[max(1, -(-7 * n // top))], "yellow") if n else ("✚", "cyan") if healing[c] else (" ", "dim")
           for c, n in enumerate(builders)]
    marks = [("✔", "green") if n else (" ", "dim") for n in merged]
    last = ("the last %s at %s" % (landed[-1][1], landed[-1][0].strftime("%H:%MZ"))) if landed else ""
    texts = ["builders at work each half hour, ✚ a healer with no builder",
             "%d merged in %d h%s" % (len(landed), span_z // 120, ", " + last if last else "")]
    return [P.cut(paint("dim", ("  " + name).ljust(LBL)) + " " + draw(cells, z_now) + " " + paint("dim", text), width)
            for name, cells, text in (("ran", ran, texts[0]), ("merged", marks, texts[1]))]


def held_row(b, t0, span_min, band_w, now_col, width):
    rows = [(r.opened, r.closed or b.now) for r in b.project.blocker_rows if r.opened]
    step = datetime.timedelta(minutes=span_min / band_w)
    counts = []
    for c in range(band_w):
        a = t0 + step * c
        counts.append(sum(1 for x, y in rows if x < a + step and y > a) if c <= now_col else 0)
    top = max(counts + [1])
    cells = [(P.STEPS[max(1, -(-7 * n // top))], "red") if n else (" ", "dim") for n in counts]
    spans = sorted(rows)
    held, cur = 0.0, None
    for x, y in spans:
        if cur and x <= cur[1]:
            cur = (cur[0], max(cur[1], y))
        else:
            held += (cur[1] - cur[0]).total_seconds() if cur else 0
            cur = (x, y)
    held += (cur[1] - cur[0]).total_seconds() if cur else 0
    open_now = len([r for r in b.project.blocker_rows if r.closed is None])
    text = "%d blocker rows, %s with one or more open, %d open now" % (len(rows), dur(held / 60), open_now)
    return P.cut(paint("dim", "  held".ljust(LBL)) + " " + draw(cells, now_col) + " " + paint("dim", text), width)


def fold_rec(rs):
    if not rs:
        return None
    first = min(r["first"] or r["s"] for r in rs)
    plans = [r["plan_end"] for r in rs if r["plan_end"]]
    end = max(r["end"] for r in rs)
    done = sum(int(r["count"].split("/")[0]) for r in rs)
    total = sum(int(r["count"].split("/")[1]) for r in rs)
    slips = sorted((((r["end"] - r["plan_end"]).total_seconds() / 60, r["m"]) for r in rs if r["plan_end"]),
                   reverse=True)
    big = ["%s %s" % (m, slip_text(s)) for s, m in slips[:2] if s >= 30]
    return {"m": rs[0]["m"], "rs": rs, "state": "done", "count": "%d/%d" % (done, total),
            "plan": window(first, max(plans)) if plans else "-", "actual": window(first, end),
            "slip": slip_text(slips[0][0]) if slips else "-",
            "texts": (["%d done, largest slips %s" % (len(rs), ", ".join(big))] if big else [])
            + ["%d done, largest slip %s" % (len(rs), big[0])] * bool(big) + ["%d done" % len(rs)]}


def fold_row(fold, col, band_w, now_col, figures, width):
    rs = fold["rs"]
    head = paint("green", ("✔%s-%s" % (rs[0]["m"], model.ms_number(rs[-1]["m"]))).ljust(LBL)) + " "
    if band_w:
        cells = [(" ", "dim")] * band_w
        for r in rs:
            for x, cell in enumerate(band(col, band_w, r["first"] or r["s"], r["end"], r["plan_end"], None, "green")):
                if cell[0] != " ":
                    cells[x] = cell
        cells, _shown = label_bar(cells, lambda room: first_fit(fold["texts"], room), now_col)
        head += draw(cells, now_col) + " "
    return P.cut(head + figures(fold), width)


def burnup_rows(b, m, t0, span_min, band_w, now_col, width):
    ids = [i for i in b.ms_tasks.get(m, ()) if i in b.by_id]
    added = sorted(b.by_id[i].added for i in ids if b.by_id[i].added)
    merged = sorted(b.by_id[i].merged for i in ids if b.by_id[i].merged)
    if not ids or not added or not band_w:
        return []
    total = len(ids)

    def at(c):
        return t0 + datetime.timedelta(minutes=(c + 1) * span_min / band_w)

    def cells(times, tone):
        out = []
        for c in range(band_w):
            n = bisect.bisect_right(times, at(c)) if c < now_col else 0
            out.append((P.STEPS[max(1, -(-7 * n // total))] if n else " ", tone))
        return out
    seeded = sum(1 for t in added if t == added[0])
    n_done = len([i for i in ids if i in b.done])
    out = []
    for name, times, tone, text in (("rows", added, "dim", "%d rows seeded on %s, %d now" % (seeded, day(added[0]),
                                                                                             total)),
                                    ("merged", merged, "green", "%d merged, %d open" % (n_done, total - n_done))):
        out.append(P.cut(paint("dim", ("  " + name).ljust(LBL)) + " " + draw(cells(times, tone), now_col) + " "
                         + paint("dim", text), width))
    return out


def axis_rows(band_w, now_col, first, last, step, col, tick, base, text_of, lead, after, width):
    marks, labels, placed = [base] * band_w, [" "] * band_w, []
    t = first
    while t <= last:
        x = col(t)
        if 0 <= x < band_w:
            marks[x] = tick
            text = text_of(t)
            clear = all(c == " " for c in labels[max(0, x - 1):x + len(text) + 1])
            if text and x + len(text) <= band_w and clear:
                labels[x:x + len(text)] = list(text)
                placed.append((x, len(text)))
        t += datetime.timedelta(minutes=step)
    tag = "now"
    a = max(0, min(band_w - len(tag), now_col - len(tag) + 1))
    for x, n in placed:
        if x <= a + len(tag) and x + n >= a:
            labels[x:x + n] = [" "] * n
    labels[a:a + len(tag)] = list(tag)
    marks[now_col] = "▼"
    lead_plain = P.visible_len(lead)
    row1 = lead + " " * max(0, (LBL + 1) - lead_plain) if lead.strip() else " " * (LBL + 1)
    row1 += (paint("dim", "".join(labels[:a])) + paint("yellow", tag)
             + paint("dim", "".join(labels[a + len(tag):])))
    row2 = " " * (LBL + 1) + paint("dim", "".join(marks[:now_col])) + paint("yellow", "▼") \
        + paint("dim", "".join(marks[now_col + 1:]))
    return [P.cut(row1 + paint("dim", after), width), P.cut(row2, width)]


def phase_tasks(b, width, rows):
    if rows < 3:
        return []
    ids = []
    for w in b.waves_of(b.focus):
        for tid in w.tasks:
            ids.append((w.n, tid))
    if not ids:
        return []
    name_w = max(10, min(24, width - 46))
    mine = [i for _w, i in ids if i in b.by_id and b.by_id[i].milestone == b.focus]
    out = [P.fit([P.label("tasks", P.LABEL_W) + P.color("bold", "%s has %d of %d tasks open"
                                                        % (b.focus, len(mine), len(b.ms_tasks[b.focus]))),
                  P.color("dim", "the same tasks as the task table above")], width),
           P.cut(P.color("dim", "  %-4s %-6s %-*s %-7s %-9s %-7s %s"
                         % ("wave", "task", name_w, "name", "lane", "state", "elapsed", "waits for")), width)]
    for wave_n, tid in ids[:max(0, rows - 2)]:
        state, elapsed = b.states[tid]
        t = b.by_id[tid]
        waits = [d for d in t.depends if d not in b.done]
        out.append(P.cut(P.color(P.KIND[P.gk(state)], "  %-4d %-6s %-*s %-7s %-9s %-7s %s"
                                 % (wave_n, tid, name_w, P.clip(t.name or t.short, name_w),
                                    "review" if t.review else (t.lane or ""),
                                    state, P.hm(elapsed) if elapsed and state not in ("done",) + model.QUEUED else "",
                                    " ".join(waits) or "nothing")), width))
    if len(ids) > max(0, rows - 2):
        out.append(P.cut(P.color("dim", "  +%d more tasks than the pane has rows for" % (len(ids) - (rows - 2))),
                         width))
    return out


def screen():
    width, height = P.pane_size()
    try:
        if not SOURCE:
            SOURCE.append(P.load_source())
        return render(width, height, P.Build(SOURCE[0])), (width, height)
    except Exception as exc:
        return ["phase timeline error: %r (it retries at the next refresh)" % (exc,)], (width, height)


def main():
    if "--rows" in sys.argv:
        print(rows_needed())
        return
    if "--loop" in sys.argv:
        secs = float(os.environ.get("TMUX_TUI_DASHBOARD_PHASES_SECONDS", "20"))
        try:
            signal.signal(signal.SIGWINCH, P.on_winch)
        except (AttributeError, ValueError, OSError):
            pass
        frame, stamp = P.Frame(), None
        while True:
            rows, size = screen()
            data = frame.paint(rows, size)
            if data:
                sys.stdout.write(data)
                sys.stdout.flush()
            stamp = stamp or P._sources()
            P._reload_if_changed(stamp)
            P.nap(secs)
    else:
        print("\n".join(screen()[0]))


if __name__ == "__main__":
    main()
