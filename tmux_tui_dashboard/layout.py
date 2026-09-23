"""The layout of the task graph: a pure function from boxes and edges to a grid of cells.

Layers by the longest chain of dependencies; boxes ordered by the barycenter of their neighbours;
each box as tall as its text. The layers flow left to right in columns, then continue down the free
rows below a column under a `↳ continued` mark. Several ways are tried and the one that draws the
most layers is kept; only what fits nowhere goes into one `+n more ▸` box. Edges are orthogonal,
run in the gaps and along the last row, and never cross a box.
"""
import dataclasses

LINE = {1: "│", 2: "│", 3: "│", 4: "─", 8: "─", 12: "─", 6: "┌", 10: "┐", 5: "└", 9: "┘",
        7: "├", 11: "┤", 14: "┬", 13: "┴", 15: "┼"}
MARK = "↳ continued"


@dataclasses.dataclass
class Node:
    id: str
    lines: list
    detail: list = dataclasses.field(default_factory=list)
    head: str = ""
    tone: str = "dim"
    heavy: bool = False
    rank: int = 0


@dataclasses.dataclass
class Style:
    box_in: int = 15
    gap: int = 4
    fold_w: int = 12


@dataclasses.dataclass
class Drawing:
    cells: list
    boxes: dict
    edges: list
    hidden: list
    layers: int
    total: int
    continued: int = 0
    extra: list = dataclasses.field(default_factory=list)
    wires: set = dataclasses.field(default_factory=set)


def layers_of(nodes, edges):
    ids = [n.id for n in nodes]
    known, rank_min = set(ids), {n.id: n.rank for n in nodes}
    parents = {i: [] for i in ids}
    children = {i: [] for i in ids}
    for s, t in edges:
        if s in known and t in known and s != t and s not in parents[t]:
            parents[t].append(s)
            children[s].append(t)
    rank = {}

    def depth(i, trail):
        if i not in rank:
            rank[i] = max([rank_min[i]] + [depth(p, trail | {i}) + 1 for p in parents[i] if p not in trail])
        return rank[i]
    for i in ids:
        depth(i, frozenset())
    top = max(rank.values(), default=-1)
    return [[i for i in ids if rank[i] == k] for k in range(top + 1)], parents, children


def ordered(layers, parents, children, sweeps=3):
    layers = [list(L) for L in layers]
    where = {}

    def mark():
        for L in layers:
            for k, i in enumerate(L):
                where[i] = (k + 0.5) / len(L)
    mark()

    def sort(L, links):
        now = {i: where[i] for i in L}
        L.sort(key=lambda i: (sum(where[j] for j in links[i]) / len(links[i]) if links[i] else now[i],
                              now[i]))
    for _ in range(sweeps):
        for L in layers[1:]:
            sort(L, parents)
            mark()
        for L in reversed(layers[:-1]):
            sort(L, children)
            mark()
    for L in layers[1:]:
        sort(L, parents)
        mark()
    return layers


def heights(nodes, ids, detail):
    return [2 + len(nodes[i].lines) + (len(nodes[i].detail) if detail else 0) for i in ids]


def stack(nodes, ids, top, room, whole, plain=False):
    for detail, spacing in ((False, 0),) if plain else ((True, 1), (False, 1), (False, 0)):
        hs = heights(nodes, ids, detail)
        if top + sum(hs) + spacing * (len(ids) - 1) <= room:
            break
    else:
        if whole:
            return None, ids
    keep, y = [], top
    for k, i in enumerate(ids):
        need = (spacing if keep else 0) + hs[k] + (3 if k + 1 < len(ids) else 0)
        if y + need > room and not (k + 1 == len(ids) and y + (spacing if keep else 0) + hs[k] <= room):
            break
        y += spacing if keep else 0
        keep.append((i, y, detail))
        y += hs[k]
    return keep, [i for i in ids[len(keep):]]


def place(nodes, layers, parents, width, rows, style, x0, strategy, reserve, plain):
    bw = style.box_in + 2
    room = rows - 1
    xs, x = [], x0
    for _L in layers:
        if x + bw + (2 if reserve else 0) > width:
            break
        xs.append(x)
        x += bw + style.gap
    if not xs:
        return None
    spots, dropped, bottom, col_of = {}, {}, {}, {}
    for c in range(len(xs)):
        keep, left = stack(nodes, layers[c], 0, room, False, plain and len(layers) > len(xs))
        for i, y0, detail in keep:
            spots[i] = (c, y0, detail)
            col_of[i] = c
        dropped[c] = left
        bottom[c] = (keep[-1][1] + heights(nodes, [keep[-1][0]], keep[-1][2])[0]) if keep else 0
        if left:
            bottom[c] = room
    marks, cont, cur = [], 0, len(xs) - 1
    for k in range(len(xs), len(layers)):
        ids = layers[k]
        pc = max([col_of[p] for i in ids for p in parents[i] if p in col_of] or [0])
        if strategy == "left":
            cands = [cur] if cur >= 0 and pc <= cur else []
        elif strategy == "down":
            cands = [c for c in range(cur, -1, -1) if c >= pc]
        else:
            cands = [c for c in range(len(xs) - 1, -1, -1) if c >= pc] + [c for c in range(pc - 1, -1, -1)]
        done = False
        for c in cands:
            if c == 0 and x0 < 3 and any(col_of.get(p, 0) != 0 for i in ids for p in parents[i]
                                         if p in col_of):
                continue
            keep, left = stack(nodes, ids, bottom[c] + 1, room, True)
            if keep is None or left:
                continue
            marks.append((c, bottom[c]))
            for i, y0, detail in keep:
                spots[i] = (c, y0, detail)
                col_of[i] = c
            bottom[c] = keep[-1][1] + heights(nodes, [keep[-1][0]], keep[-1][2])[0]
            cur = c - 1 if strategy == "left" else c
            cont += 1
            done = True
            break
        if not done:
            break
    return xs, spots, dropped, marks, cont


def layout(nodes, edges, width, rows, style=None, groups=(), dashed=()):
    style = style or Style()
    bw = style.box_in + 2
    by = {n.id: n for n in nodes}
    layers, parents, children = layers_of(nodes, edges)
    layers = ordered(layers, parents, children)
    gw = max([len(x) + 2 for title, ls, _t in groups for x in list(ls) + [title + "  "]] or [0])
    x0 = gw + style.gap if gw else 0
    best = None
    for reserve in (True, False):
        for plain in (False, True):
            for strategy in ("down", "left", "any"):
                got = place(by, layers, parents, width, rows, style, x0, strategy, reserve, plain)
                if got is None:
                    continue
                xs, spots, dropped, marks, cont = got
                if xs[-1] + bw + 2 > width and any(s in spots and t in spots and spots[s][0] == len(xs) - 1
                                                   for s, t in edges):
                    continue
                drawn = len({k for k, L in enumerate(layers) if any(i in spots for i in L)})
                back = sum(1 for s, t in edges if s in spots and t in spots and spots[t][0] < spots[s][0])
                score = (drawn, len(spots), -back, not plain)
                if best is None or score > best[0]:
                    best = (score, got)
    if best is None and groups:
        return layout(nodes, edges, width, rows, style, (), dashed)
    grid = [[" ", "dim"] for _x in range(width)]
    cells = [[list(c) for c in grid] for _y in range(rows)]
    if best is None:
        text = "the graph needs %d columns" % (x0 + bw)
        for dx, ch in enumerate(text[:width]):
            cells[0][dx] = [ch, "dim"]
        ids = [i for L in layers for i in L]
        return Drawing(cells, {}, [], ids, 0, len(layers))
    xs, spots, dropped, marks, cont = best[1]
    lines, across, along, solid = {}, {}, {}, set()
    held, edge = set(dashed), [None]

    def seg(x1, y1, x2, y2):
        if y1 == y2:
            lo, hi = min(x1, x2), max(x1, x2)
            for xx in range(lo, hi + 1):
                lines[(xx, y1)] = lines.get((xx, y1), 0) | (4 if xx < hi else 0) | (8 if xx > lo else 0)
                across.setdefault((xx, y1), set()).add(edge[0])
                if edge[0] not in held:
                    solid.add((xx, y1))
        else:
            lo, hi = min(y1, y2), max(y1, y2)
            for yy in range(lo, hi + 1):
                lines[(x1, yy)] = lines.get((x1, yy), 0) | (2 if yy < hi else 0) | (1 if yy > lo else 0)
                along.setdefault((x1, yy), set()).add(edge[0])
                if edge[0] not in held:
                    solid.add((x1, yy))
    rail, arrows, drawn_edges = rows - 1, {}, []
    for s, t in edges:
        if s not in spots or t not in spots or s == t:
            continue
        (cs, ys0, _d), (ct, yt0, _e) = spots[s], spots[t]
        edge[0] = (s, t)
        ys, yt = ys0 + 1, yt0 + 1
        exit_x = xs[cs] + bw
        if ct == cs:
            seg(exit_x, ys, exit_x + 1, ys)
            seg(exit_x + 1, ys, exit_x + 1, yt)
            seg(exit_x + 1, yt, exit_x, yt)
            arrows[(exit_x, yt)] = "◄"
        else:
            bus = xs[ct] - 3
            if ct == cs + 1:
                seg(exit_x, ys, bus, ys)
                seg(bus, ys, bus, yt)
            else:
                seg(exit_x, ys, exit_x + 1, ys)
                seg(exit_x + 1, ys, exit_x + 1, rail)
                seg(exit_x + 1, rail, bus, rail)
                seg(bus, rail, bus, yt)
            seg(bus, yt, xs[ct] - 2, yt)
            arrows[(xs[ct] - 1, yt)] = "►"
        drawn_edges.append((s, t))
    for (xx, yy), m in lines.items():
        if 0 <= xx < width and 0 <= yy < rows:
            ch = LINE.get(m, "┼")
            if m == 15 and not (across.get((xx, yy), set()) & along.get((xx, yy), set())):
                ch = "│"
            elif (xx, yy) not in solid:
                ch = {"─": "╌", "│": "╎"}.get(ch, ch)
            cells[yy][xx] = [ch, "dim"]
    for (xx, yy), ch in arrows.items():
        if 0 <= xx < width and 0 <= yy < rows:
            cells[yy][xx] = [ch, "bold"]
    boxes, extra = {}, []

    def box(x0_, y0, w, head, body, tone, heavy=False):
        c = "┏━┓┃┗┛" if heavy else "┌─┐│└┘"
        text = [c[0] + head + c[1] * max(0, w - 2 - len(head)) + c[2]]
        text += [c[3] + t.ljust(w - 2)[:w - 2] + c[3] for t in body] + [c[4] + c[1] * (w - 2) + c[5]]
        for dy, row in enumerate(text):
            for dx, ch in enumerate(row):
                if 0 <= x0_ + dx < width and 0 <= y0 + dy < rows:
                    inside = 0 < dx < w - 1 and 0 < dy < len(text) - 1
                    cells[y0 + dy][x0_ + dx] = [ch, "default" if inside else tone]
        return (x0_, y0, w, len(text))
    for i, (c, y0, detail) in spots.items():
        n = by[i]
        body = list(n.lines) + (list(n.detail) if detail else [])
        boxes[i] = box(xs[c], y0, bw, n.head, body, n.tone, n.heavy)
    for c, left in dropped.items():
        if left:
            last = max([spots[i][1] + boxes[i][3] for i in spots if spots[i][0] == c and i in layers[c]]
                       or [0])
            extra.append(box(xs[c], min(last, rows - 4), bw, "", ["+%d more" % len(left)], "dim"))
    for c, y0 in marks:
        for dx, ch in enumerate(MARK):
            if xs[c] + dx < width:
                cells[y0][xs[c] + dx] = [ch, "dim"]
    y = 0
    for title, ls, tone in groups:
        if y >= rows - 2:
            break
        extra.append(box(0, y, gw, title, list(ls)[:max(1, rows - y - 2)], tone))
        y += len(ls) + 2
    hidden = [i for L in layers for i in L if i not in spots]
    folded = [k for k, L in enumerate(layers) if not any(i in spots for i in L)]
    if folded:
        text = ["+%d more →" % sum(len(layers[k]) for k in folded),
                "%d layer%s" % (len(folded), "" if len(folded) == 1 else "s")]
        spot = free_rect(cells, style.fold_w, 4, width, rows)
        if spot:
            extra.append(box(spot[0], spot[1], style.fold_w, "", text, "dim"))
        else:
            short = "+%d more →" % sum(len(layers[k]) for k in folded)
            spot = free_rect(cells, len(short), 1, width, rows)
            if spot:
                for dx, ch in enumerate(short):
                    cells[spot[1]][spot[0] + dx] = [ch, "dim"]
                extra.append((spot[0], spot[1], len(short), 1))
    return Drawing(cells, boxes, drawn_edges, hidden, len(layers) - len(folded), len(layers), cont, extra,
                   set(lines) | set(arrows))


def free_rect(cells, w, h, width, rows):
    run = []
    for y in range(rows):
        r, n = [0] * (width + 1), 0
        for x in range(width - 1, -1, -1):
            n = n + 1 if cells[y][x][0] == " " else 0
            r[x] = n
        run.append(r)
    for y in range(rows - 1 - h, -1, -1):
        for x in range(width - w, -1, -1):
            if all(run[yy][x] >= w for yy in range(y, y + h)):
                return x, y
    return None
