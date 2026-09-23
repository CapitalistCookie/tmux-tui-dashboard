#!/usr/bin/env bash
# Start the phases pane: python3 -m tmux_tui_dashboard.phases, with the arguments given (--loop to redraw in place).
cd "$(dirname "$0")/.." && exec python3 -m tmux_tui_dashboard.phases "$@"
