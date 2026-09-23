"""Where the panes get their data: the Source protocol and load_source().

  TMUX_TUI_DASHBOARD_SOURCE=json:<path>             a JSON feed file (tmux_tui_dashboard/feed.schema.json)
  TMUX_TUI_DASHBOARD_SOURCE=python:<module>:<Class>  a Source class of your own

Without it the panes draw the sample feed. `python3 -m tmux_tui_dashboard.source --dump FEED.json` writes the
feed of the chosen source.
"""
from __future__ import annotations

import json
import os
import sys
import typing

from tmux_tui_dashboard import model

DEFAULT = "json:" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "feed.sample.json")


class Source(typing.Protocol):

    def refresh(self) -> None: ...

    def project(self) -> model.Project: ...

    def milestones(self) -> list[model.Milestone]: ...

    def tasks(self) -> list[model.Task]: ...

    def edges(self) -> list[model.Edge]: ...

    def sessions(self) -> list[model.Session]: ...

    def events(self, since: str | None) -> list[model.Event]:
        ...

    def usage(self) -> model.Usage | None: ...

    def locks(self) -> list[model.Lock]: ...

    def plan(self) -> model.Plan: ...

    def blockers(self) -> list[model.Blocker]: ...

    def open_calls(self) -> list[model.Event]:
        ...


def load_source(spec=None, **options):
    spec = (spec or os.environ.get("TMUX_TUI_DASHBOARD_SOURCE") or DEFAULT).strip()
    if spec.startswith("python:") and spec.count(":") == 2:
        import importlib
        _kind, mod, cls = spec.split(":")
        return getattr(importlib.import_module(mod), cls)(**options)
    if spec.startswith("json:") and len(spec) > 5:
        from tmux_tui_dashboard.json_source import JsonSource
        return JsonSource(spec[5:])
    raise SystemExit("TMUX_TUI_DASHBOARD_SOURCE=%r names no source: use `json:<path of a feed>` or `python:<module>:<Class>`" % spec)


def main(argv):
    if len(argv) == 2 and argv[0] == "--dump":
        doc = model.feed(load_source())
        tmp = argv[1] + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, argv[1])
        print("feed: %s (%d tasks, %d events)" % (argv[1], len(doc["tasks"]), len(doc.get("events") or [])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
