#!/usr/bin/env bash
# Start the follow pane: python3 -m tmux_tui_dashboard.follow, with the arguments given (--once, --backlog, --poll).
cd "$(dirname "$0")/.." && exec python3 -m tmux_tui_dashboard.follow "$@"
