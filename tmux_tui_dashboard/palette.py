"""The one colour table of the three panes. TMUX_TUI_DASHBOARD_COLOR=none, 8 or 256 sets the depth; the colours
come from a gruvbox-material palette module when one is installed (TMUX_TUI_DASHBOARD_THEME), else from
the fallback indices here. Colour never carries a meaning alone: each state keeps its glyph.
"""
import os

THEME_MODULE = os.environ.get("TMUX_TUI_DASHBOARD_THEME") or os.path.expanduser("~/.config/gruvbox-material/palette.py")


def theme(path=THEME_MODULE):
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("gruvbox_material_palette", path)
        box = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(box)
        names = list(box.ACCENTS) + list(box.GREYS)
        out = {name: box.idx(name) for name in names}
    except (OSError, ImportError, AttributeError, KeyError, ValueError, TypeError):
        return {}
    return {k: v for k, v in out.items() if isinstance(v, int) and 16 <= v <= 255}


THEME = theme()


def ix(name, before):
    return THEME.get(name, before)


AHEAD = 4
HUE_256 = (ix("orange", 208), ix("yellow", 220), ix("aqua", 108), ix("blue", 110), ix("purple", 141))
HUE_8 = (33, 33, 32, 36, 35)
LANE_256 = {"cpu": ix("blue", 110), "gpu": ix("orange", 214), "laptop": ix("purple", 176),
            "review": ix("aqua", 108), "main": ix("grey", 245), "": ix("grey", 245)}
LANE_8 = {"cpu": 34, "gpu": 33, "laptop": 35, "review": 36, "main": 37, "": 37}
BASE = {"green": 32, "yellow": 33, "red": 31, "cyan": 36, "magenta": 35, "blue": 34, "white": 37}


def level():
    want = (os.environ.get("TMUX_TUI_DASHBOARD_COLOR") or "").strip().lower()
    if want in ("none", "0", "off"):
        return 0
    if want in ("8", "16"):
        return 8
    if want in ("256", "truecolor", "24bit"):
        return 256
    term = os.environ.get("TERM", "")
    if not term or term == "dumb":
        return 0
    if "256color" in term or "truecolor" in term or (os.environ.get("COLORTERM") or "") in ("truecolor", "24bit"):
        return 256
    return 8


LEVEL = level()


def fg(index):
    if LEVEL == 0:
        return ""
    if LEVEL >= 256:
        return "\033[38;5;%dm" % index
    return "\033[%dm" % (index if 30 <= index <= 37 else 37)


def sgr(code):
    return "" if LEVEL == 0 else "\033[%dm" % code


def hue_plan(order, focus, finished):
    plan, here = {}, order.index(focus) if focus in order else 0
    for i, m in enumerate(order):
        if m in finished:
            plan[m] = "ms:done"
        elif i == here:
            plan[m] = "ms:running"
        elif here < i <= here + AHEAD:
            plan[m] = "ms:ahead%d" % (i - here)
        else:
            plan[m] = "ms:far"
    return plan


def role(name, basic, before=None):
    if LEVEL >= 256:
        idx = THEME.get(name, before)
        if idx is not None:
            return fg(idx)
    return sgr(basic)


def build():
    table = {
        "reset": sgr(0), "bold": sgr(1), "dim": role("grey", 2),
        "green": role("green", BASE["green"]), "yellow": role("yellow", BASE["yellow"]),
        "red": role("red", BASE["red"]),
        "cyan": role("aqua", BASE["cyan"]), "magenta": role("purple", BASE["magenta"]),
        "level": sgr(0), "amber": role("orange", BASE["yellow"], 214),
        "hot": role("red", BASE["red"], 203),
        "pass": role("green", BASE["green"]), "warn": role("yellow", BASE["yellow"]),
        "fail": role("red", BASE["red"]),
        "parked": role("aqua", BASE["cyan"], 80),
        "critical": role("orange", BASE["red"], 208),
        "blue": role("blue", BASE["blue"], 110),
    }
    table["ms:done"] = table["dim"]
    table["ms:far"] = table["dim"]
    table["ms:running"] = fg(HUE_256[0]) if LEVEL >= 256 else sgr(HUE_8[0])
    for n in range(1, AHEAD + 1):
        table["ms:ahead%d" % n] = fg(HUE_256[n]) if LEVEL >= 256 else sgr(HUE_8[n])
    for lane, hue in LANE_256.items():
        table["lane:" + lane] = fg(hue) if LEVEL >= 256 else sgr(LANE_8[lane])
    return table


C = build()


def lane(name):
    return C.get("lane:" + (name or ""), C["lane:"])


def ramp(value, mean):
    if not mean or value is None:
        return "level"
    if value > 2 * mean:
        return "hot"
    return "amber" if value > mean else "level"


def health(ok, warn=False):
    return "warn" if warn else ("pass" if ok else "fail")
