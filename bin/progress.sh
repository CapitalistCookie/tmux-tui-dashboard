#!/usr/bin/env bash
# Start the progress pane: python3 -m tmux_tui_dashboard.progress, with the arguments given (--loop to redraw in place).
cd "$(dirname "$0")/.." && exec python3 -m tmux_tui_dashboard.progress "$@"
