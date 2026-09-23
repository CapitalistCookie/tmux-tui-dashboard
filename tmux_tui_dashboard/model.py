"""The model of the three panes: what a source says about a build. Times are UTC datetimes (ISO 8601 with
a Z in a feed); durations are minutes; ids are plain strings the panes compare and never parse.
"""
from __future__ import annotations

import dataclasses
import datetime
import enum
import os
import re
import types
import typing

UTC = datetime.timezone.utc


class State(str, enum.Enum):
    DONE = "done"
    BUILDING = "building"
    MERGING = "merging"
    REVIEW = "review"
    READY = "ready"
    WAITING = "waiting"
    BLOCKED = "blocked"
    HEALING = "healing"
    PULLED = "pulled"


QUEUED = (State.READY.value, State.WAITING.value, State.PULLED.value)
IN_FLIGHT = (State.BUILDING.value, State.MERGING.value)


@dataclasses.dataclass
class Window:
    start: datetime.datetime | None = None
    end: datetime.datetime | None = None


@dataclasses.dataclass
class Task:
    id: str
    name: str = ""
    short: str = ""
    purpose: str = ""
    milestone: str = ""
    wave: int | None = None
    lane: str = ""
    state: State = State.WAITING
    depends: list[str] = dataclasses.field(default_factory=list)
    outputs: list[str] = dataclasses.field(default_factory=list)
    elapsed: float | None = None
    started: datetime.datetime | None = None
    merged: datetime.datetime | None = None
    added: datetime.datetime | None = None
    why: str = ""
    review: bool = False


@dataclasses.dataclass
class Milestone:
    id: str
    title: str = ""
    purpose: str = ""
    planned: Window = dataclasses.field(default_factory=Window)
    actual: Window = dataclasses.field(default_factory=Window)
    tasks: list[str] = dataclasses.field(default_factory=list)
    state: State = State.WAITING
    minutes: float = 0.0
    blockers: int = 0


@dataclasses.dataclass
class Edge:
    source: str
    target: str


@dataclasses.dataclass
class Session:
    role: str
    milestone: str = ""
    since: datetime.datetime | None = None
    window: str = ""
    until: datetime.datetime | None = None
    outcome: str = ""
    note: str = ""
    last: datetime.datetime | None = None


@dataclasses.dataclass
class Event:
    time: str = ""
    source: str = ""
    text: str = ""
    level: str = "info"
    kind: str = "log"
    outcome: str = ""
    result: str = ""


@dataclasses.dataclass
class UsageWindow:
    name: str
    percent: int = 0
    resets: str = ""
    reset_at: datetime.datetime | None = None
    rate: float | None = None
    full: datetime.datetime | None = None


@dataclasses.dataclass
class Usage:
    windows: list[UsageWindow] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Lock:
    name: str
    holder: str = ""
    since: datetime.datetime | None = None
    lane: str = ""
    live: bool = True


@dataclasses.dataclass
class Blocker:
    id: str
    task: str = ""
    milestone: str = ""
    kind: str = ""
    who: str = ""
    since: str = ""
    text: str = ""
    opened: datetime.datetime | None = None
    closed: datetime.datetime | None = None


@dataclasses.dataclass
class Gate:
    time: datetime.datetime | None = None
    subject: str = ""
    passed: bool = False
    steps: list[str] = dataclasses.field(default_factory=list)
    acceptance: int = 0


@dataclasses.dataclass
class Walk:
    name: str
    task: str = ""
    start: datetime.datetime | None = None
    end: datetime.datetime | None = None
    depth: str = ""
    stages: dict[str, int] = dataclasses.field(default_factory=dict)
    notes: int = 0
    last: str = ""
    verdict: str = ""


@dataclasses.dataclass
class Wave:
    milestone: str
    n: int = 1
    tasks: list[str] = dataclasses.field(default_factory=list)
    minutes: float = 0.0
    paced: float = 0.0


@dataclasses.dataclass
class Plan:
    waves: list[Wave] = dataclasses.field(default_factory=list)
    critical: list[str] = dataclasses.field(default_factory=list)
    projected: dict[str, Window] = dataclasses.field(default_factory=dict)
    finish: datetime.datetime | None = None
    builder_minutes: float = 30.0
    builder_n: int = 0
    merge_minutes: float = 1.0
    merge_n: int = 0
    lanes: dict[str, int] = dataclasses.field(default_factory=dict)
    builder_samples: list[float] = dataclasses.field(default_factory=list)
    schedule: dict[str, Window] = dataclasses.field(default_factory=dict)
    spread: dict[str, Window] = dataclasses.field(default_factory=dict)
    finish_spread: Window = dataclasses.field(default_factory=Window)


@dataclasses.dataclass
class Project:
    name: str = ""
    now: datetime.datetime | None = None
    head: str = ""
    tags: list[str] = dataclasses.field(default_factory=list)
    focus: str = ""
    seeded: datetime.datetime | None = None
    gate: Gate | None = None
    run: Window = dataclasses.field(default_factory=Window)
    last_activity: datetime.datetime | None = None
    walks: list[Walk] = dataclasses.field(default_factory=list)
    gates: list[Gate] = dataclasses.field(default_factory=list)
    blocker_rows: list[Blocker] = dataclasses.field(default_factory=list)


def parse_time(value):
    if value is None or isinstance(value, datetime.datetime):
        return value if value is None or value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def iso(dt):
    if dt is None:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def clock():
    pinned = parse_time(os.environ.get("TMUX_TUI_DASHBOARD_NOW"))
    return pinned or datetime.datetime.now(UTC)


def to_feed(value):
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_feed(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, datetime.datetime):
        return iso(value)
    if isinstance(value, dict):
        return {str(k): to_feed(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_feed(v) for v in value]
    return value


def _load(tp, value):
    if value is None:
        return None
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if origin in (typing.Union, types.UnionType):
        inner = [a for a in args if a is not type(None)]
        return _load(inner[0], value) if inner else value
    if origin is list:
        return [_load(args[0], v) for v in value]
    if origin is dict:
        return {str(k): _load(args[1], v) for k, v in value.items()}
    if tp is datetime.datetime:
        return parse_time(value)
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return tp(value)
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        return from_feed(tp, value)
    if tp is float:
        return float(value)
    if tp is int:
        return int(value)
    if tp is bool:
        return bool(value)
    return value


def from_feed(cls, data):
    hints = typing.get_type_hints(cls)
    known = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: _load(hints[k], v) for k, v in (data or {}).items() if k in known})


class Snapshot:

    def __init__(self, project, milestones, tasks, edges, sessions, usage, locks, plan, blockers=()):
        self.project = project
        self.now = project.now or clock()
        self.milestones = list(milestones)
        self.tasks = list(tasks)
        self.edges = list(edges)
        self.sessions = list(sessions)
        self.usage = usage
        self.locks = list(locks)
        self.plan = plan
        self.blockers = list(blockers)
        self.by_id = {t.id: t for t in self.tasks}
        self.ms_by_id = {m.id: m for m in self.milestones}
        self.order = [m.id for m in self.milestones]
        for t in self.tasks:
            if t.milestone and t.milestone not in self.ms_by_id:
                self.ms_by_id[t.milestone] = Milestone(id=t.milestone)
                self.milestones.append(self.ms_by_id[t.milestone])
                self.order.append(t.milestone)
        self.ms_tasks = {m.id: [i for i in m.tasks if i in self.by_id] for m in self.milestones}
        for m, ids in self.ms_tasks.items():
            if not ids:
                ids.extend(t.id for t in self.tasks if t.milestone == m)
        self.done = {t.id for t in self.tasks if t.state == State.DONE}
        self.states = {t.id: (t.state.value, self.elapsed(t)) for t in self.tasks}
        self.running = {s.milestone: s for s in self.sessions if s.role == "orchestrator" and s.until is None}
        self.healing = {s.milestone: s for s in self.sessions if s.role == "healer" and s.until is None}
        self.walkers = [s for s in self.sessions if s.role == "walker" and s.until is None]
        self.cycles = [s for s in self.sessions if s.role == "heal cycle"]
        self.blocked_ms = {m.id: m.blockers for m in self.milestones if m.blockers}
        focus = project.focus if project.focus in self.ms_by_id else ""
        self.focus = focus or next((m for m in self.order if self.ms_state(m) != State.DONE.value),
                                   self.order[-1] if self.order else "")

    def elapsed(self, t):
        if t.state == State.DONE:
            return None
        if t.started is not None:
            return (self.now - t.started).total_seconds() / 60
        return t.elapsed

    def ms_state(self, m):
        ms = self.ms_by_id.get(m)
        return ms.state.value if ms else State.WAITING.value

    def waves_of(self, m):
        return [w for w in self.plan.waves if w.milestone == m]

    def groups(self):
        have = {w.milestone for w in self.plan.waves}
        return [(m, self.waves_of(m)) for m in self.order if m in have]

    def static_waves(self, m):
        out = {}
        for i in self.ms_tasks.get(m, ()):
            n = self.by_id[i].wave
            if n is not None:
                out.setdefault(n, []).append(i)
        return sorted(out.items())

    @property
    def structure(self):
        return {m: {"id": m, "minutes": self.ms_by_id[m].minutes,
                    "waves": [{"n": n, "tasks": [{"id": i} for i in ids]} for n, ids in self.static_waves(m)]}
                for m in self.order}


def ms_number(m):
    hit = re.search(r"(\d+)$", m or "")
    return hit.group(1) if hit else (m or "")


def milestone_deps(snap):
    deps = {m: set() for m in snap.order}
    for e in snap.edges:
        a, b = snap.by_id.get(e.target), snap.by_id.get(e.source)
        if a and b and a.milestone != b.milestone and a.milestone in deps:
            deps[a.milestone].add(b.milestone)
    return deps


def reduced_deps(snap):
    deps = milestone_deps(snap)

    def reach(m, seen):
        for d in deps.get(m, ()):
            if d not in seen:
                seen.add(d)
                reach(d, seen)
        return seen
    index = {m: k for k, m in enumerate(snap.order)}
    return {m: sorted((d for d in deps[m] if not any(d in reach(o, set()) for o in deps[m] if o != d)),
                      key=lambda x: index.get(x, 0)) for m in snap.order}


def snapshot(source):
    refresh = getattr(source, "refresh", None)
    if refresh:
        refresh()
    return Snapshot(source.project(), source.milestones(), source.tasks(), source.edges(), source.sessions(),
                    source.usage(), source.locks(), source.plan(), getattr(source, "blockers", lambda: [])())


FEED_SCHEMA = "dash-feed/1"


def feed_of(snap, events=None):
    doc = {"schema": FEED_SCHEMA, "project": to_feed(snap.project), "milestones": to_feed(snap.milestones),
           "tasks": to_feed(snap.tasks), "edges": to_feed(snap.edges), "sessions": to_feed(snap.sessions),
           "usage": to_feed(snap.usage), "locks": to_feed(snap.locks), "plan": to_feed(snap.plan),
           "blockers": to_feed(snap.blockers)}
    if events is not None:
        doc["events"] = to_feed(events)
    return doc


def feed(source, events=True):
    snap = snapshot(source)
    return feed_of(snap, source.events(None) if events else None)
