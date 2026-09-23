"""A Source that reads one JSON feed file, again whenever it changes. The panes draw with their own
clock, so a task's elapsed time runs on between two writes of the feed.
"""
from __future__ import annotations

import json
import os

from tmux_tui_dashboard import model


class JsonSource:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.doc, self.stamp, self.written = {}, None, None
        self.seen, self.last = set(), ""

    def _read(self):
        try:
            st = os.stat(self.path)
        except OSError as exc:
            raise SystemExit("the feed %s cannot be read: %s" % (self.path, exc))
        stamp = (st.st_mtime_ns, st.st_size)
        if stamp != self.stamp:
            with open(self.path, encoding="utf-8") as fh:
                doc = json.load(fh)
            if not isinstance(doc, dict) or not isinstance(doc.get("tasks", []), list):
                raise SystemExit("the feed %s is not a dash feed: an object with a tasks list" % self.path)
            self.doc, self.stamp = doc, stamp
        return self.doc

    def refresh(self):
        self._read()

    def _list(self, key, cls):
        return [model.from_feed(cls, x) for x in self._read().get(key) or []]

    def project(self):
        p = model.from_feed(model.Project, self._read().get("project") or {})
        self.written = p.now
        p.now = model.clock()
        return p

    def milestones(self):
        return self._list("milestones", model.Milestone)

    def tasks(self):
        return self._list("tasks", model.Task)

    def edges(self):
        out = []
        for x in self._read().get("edges") or []:
            out.append(model.Edge(*x) if isinstance(x, list) else model.from_feed(model.Edge, x))
        edges = {(e.source, e.target) for e in out}
        for t in self.tasks():
            for d in t.depends:
                if (d, t.id) not in edges:
                    edges.add((d, t.id))
                    out.append(model.Edge(d, t.id))
        return out

    def sessions(self):
        return self._list("sessions", model.Session)

    def usage(self):
        u = self._read().get("usage")
        return model.from_feed(model.Usage, u) if u else None

    def locks(self):
        return self._list("locks", model.Lock)

    def plan(self):
        return model.from_feed(model.Plan, self._read().get("plan") or {})

    def blockers(self):
        return self._list("blockers", model.Blocker)

    def open_calls(self):
        plain = ("log", "says", "result", "prompt", "heartbeat", "reset", "divider", "error")
        return sorted((e for e in self._list("events", model.Event) if e.kind not in plain and not e.outcome
                       and not e.result and e.time), key=lambda e: e.time)

    def events(self, since):
        evs = self._list("events", model.Event)
        key = lambda e: (e.time, e.source, e.kind, e.text)
        if since is None:
            self.seen = {key(e) for e in evs}
            self.last = max((e.time for e in evs), default="")
            return evs
        out = [e for e in evs if key(e) not in self.seen and e.time >= self.last]
        for e in out:
            self.seen.add(key(e))
        self.last = max([self.last] + [e.time for e in out])
        return out
