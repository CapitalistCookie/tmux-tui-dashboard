# tmux_tui_dashboard

tmux_tui_dashboard shows an automated build in three terminal panes. The panes are made for one tmux window on a monitor in portrait position.

- The top pane shows what runs now, what is blocked and what comes next. Its body is the task graph: the tasks are boxes and the depends-on relations are edges.
- The middle pane is a Gantt chart of the milestones. It has two time scales: the project in days, and the open waves from 12 hours before now to 12 hours after now.
- The bottom pane is the stream: one line for each event of the build, in time order.

The panes draw one model. A source fills the model with the data of your build. The panes read nothing else, and they write nothing.

## What each pane shows

The top pane:

- Row `now` shows the sessions that run, each with its last sign of life, and the tasks in flight. When nothing runs, it shows since when and the last merge.
- Row `blocked` shows the blocked tasks and the open blocker rows. Row `next` shows the tasks that a builder can start now.
- The rows `walk` show the newest walk of the program when it is less than one day old: the screens in each stage, the notes and the verdict.
- The task graph shows the tasks as boxes and the depends-on relations as edges. A blocked box shows the age of its blocker row and how many open tasks wait for it.
- Row `gate` shows the seven steps of the newest full gate, and one cell for each full gate of the last 24 hours.
- Row `lanes` shows each lane slot: live, gone or free. Row `usage` shows the usage windows, their rate and when they get to 100 per cent.
- Row `24 h` counts the tasks merged, the task rows added, the blocker rows opened and closed, and the heal cycles of the last 24 hours.
- The two rows `estimate` show when the last open task lands, the range from the p25 to the p75 of the builder minutes, and the finish at the merge rate of the last 72 hours.
- The key defines each glyph of the three panes.

The middle pane:

- One row for each milestone, on a band of days, with its planned window, its actual window, its slip, its tasks, its state and 12 cells that show where its hours went.
- The oldest finished milestones share one row when the pane has too few rows.
- An open milestone that has run for more than one day has burn-up rows: the task rows that it held, and the task rows merged.
- Row `held` shows how many blocker rows were open at each time.
- The wave band shows the past 12 hours (the builders at work and the merges) and the open waves of the next 12 hours.

The bottom pane:

- One line for each event, in whole words. A tool call shows its outcome first: `✔`, `✖` or `timed out`.
- A gray rule shows a gap of 10 minutes or more. A rule of `═` shows a recorded wave, a tag or a new session.
- The last row stays in place. It shows the calls that the live sessions wait for.

## Requirements

- Python 3.10 or later. The panes use the standard library only.
- A terminal with 256 colors, for the full palette. The panes also work with 8 colors and with no color.
- tmux, to put the three panes in one window.

## Start the panes with the sample feed

Run these commands in the root of the repository:

```
python3 -m tmux_tui_dashboard.progress
python3 -m tmux_tui_dashboard.phases
python3 -m tmux_tui_dashboard.follow --once
```

Each command draws its pane once from the sample feed `tmux_tui_dashboard/feed.sample.json`. The option `--loop` redraws the top pane and the middle pane in place. The stream follows the source until you stop it.

The scripts `bin/progress.sh`, `bin/phases.sh` and `bin/follow.sh` start the same panes from any directory.

To make the tmux window, split one window into three panes, one above the other. Start `bin/progress.sh --loop` in the top pane, `bin/phases.sh --loop` in the middle pane and `bin/follow.sh` in the bottom pane. The middle pane asks for its row count: `python3 -m tmux_tui_dashboard.phases --rows`.

## Give the panes the data of your build

The environment variable `TMUX_TUI_DASHBOARD_SOURCE` selects the source:

- `TMUX_TUI_DASHBOARD_SOURCE=json:<path>` reads a JSON feed file.
- `TMUX_TUI_DASHBOARD_SOURCE=python:<module>:<Class>` uses a source class of your own.
- Without the variable, the panes draw the sample feed.

### Write the feed

1. Read `tmux_tui_dashboard/feed.sample.json`. It shows each part of a feed.
2. Make your build write the feed each time its state changes. Write the feed to a temporary file first. Then rename the temporary file to the feed path. The panes then never read half a file.
3. Set `TMUX_TUI_DASHBOARD_SOURCE=json:<path>` in the environment of the three panes.

The panes use the clock of the machine that draws them. A task shows its elapsed time from its `started` time to now. So the panes stay current between two writes of the feed. The panes never parse an id. Any string can be an id.

### The fields of the feed

All times are in ISO 8601 format in UTC, for example `2026-09-20T12:00:00Z`. All durations are in minutes. A field that you do not write takes its default value. The panes ignore a field that the model does not have.

The feed is one JSON object with these keys:

| Key | Type | What the panes do with it |
|---|---|---|
| `schema` | text | The version of the feed: `dash-feed/1`. |
| `project` | object | The facts about the whole build. |
| `milestones` | list | One object for each milestone, in plan order. The order sets the rows and the colors. |
| `tasks` | list | One object for each task, in plan order. A task comes after each task that it depends on. |
| `edges` | list | The depends-on relations. The `depends` list of each task adds the edges that this list does not name. |
| `sessions` | list | The sessions that run now, and the past heal cycles. |
| `usage` | object or null | The usage windows. Write null when you do not know them. The pane then shows `unknown`. |
| `locks` | list | The locks that are held now. |
| `plan` | object | The schedule of the open work: the waves, the critical path and the projections. |
| `blockers` | list | The open blocker rows. |
| `events` | list | The lines of the stream, oldest first. Keep the newest few hundred. |

`project`:

| Field | Type | What the panes do with it |
|---|---|---|
| `name` | text | The name of the build. |
| `now` | time | The time that the feed was written. The panes keep it and draw with their own clock. |
| `head` | text | The commit on the main branch. The row `usage` shows it. |
| `tags` | list of text | The milestone tags. The row `usage` shows their count. |
| `focus` | text | The id of the milestone that the build works on now. When it is empty, the panes use the first milestone that is not done. |
| `seeded` | time | The time of the first plan. The middle pane counts the spent time from it. |
| `gate` | object or null | The newest full gate: `time`, `subject` (the task id), `passed` (true or false), `steps` (`pass`, `fail` or `skip` for each of the seven steps, in run order) and `acceptance` (the acceptance tests that passed). |
| `gates` | list | The full gates of the last 24 hours, oldest first, with the fields of `gate`. The row `gate` shows one cell for each. |
| `blocker_rows` | list | Each blocker row that the build held, open and closed, oldest first, with the fields of `blockers` and `opened` and `closed`. The row `held` and the row `24 h` use them. |
| `run` | object | The run of the driver: `start`, and the deadline as `end`. |
| `last_activity` | time | The newest action of a session. When nothing runs, the row `now` says since when. |
| `walks` | list | The newest walks of the program, newest first. Each walk has `name`, `task`, `start`, `end`, `depth` (the deepest stage), `stages` (each stage and its screens), `notes`, `last` (the last screen) and `verdict`. The rows `walk` show the newest walk when it is less than one day old. |

`milestones`, one object for each milestone:

| Field | Type | What the panes do with it |
|---|---|---|
| `id` | text | The id. |
| `title` | text | The name. The middle pane writes it beside the bar. |
| `purpose` | text | One sentence about what the milestone is for. |
| `planned` | window | The window that the plan gives: `start` and `end`. |
| `actual` | window | The first task that landed, and the tag. `end` is null while the milestone is open. |
| `tasks` | list of text | The ids of its tasks. When the list is empty, the panes use the tasks that name this milestone. |
| `state` | text | One of `done`, `building`, `blocked`, `healing` or `waiting`. |
| `minutes` | number | The cost of its own plan, with nothing done. |
| `blockers` | number | The count of open blocker rows that hold it. |

`tasks`, one object for each task:

| Field | Type | What the panes do with it |
|---|---|---|
| `id` | text | The id. |
| `name` | text | The name in the box. It wraps between words. |
| `short` | text | The short name in the one-line lists, often a file name. |
| `purpose` | text | One sentence about what the task is for. |
| `milestone` | text | The id of its milestone. |
| `wave` | number or null | Its wave in the plan of its milestone with nothing done. The box of finished waves counts these waves. |
| `lane` | text | The kind of slot that it builds in, for example `cpu`. |
| `state` | text | One of `done`, `building`, `merging`, `review`, `ready`, `waiting`, `blocked`, `healing` or `pulled`. |
| `depends` | list of text | The ids of the tasks that must land first. |
| `outputs` | list of text | The paths that it writes. |
| `elapsed` | number or null | The minutes in flight. The panes use it only when `started` is null. |
| `started` | time | The time that a builder took the task. The elapsed time starts here. |
| `merged` | time | The time that the task landed. The estimate counts the merges of the last 72 hours. |
| `added` | time | The time that the row of the task went into the plan. The burn-up rows count the task rows at each time. |
| `why` | text | The reason that the task is where it is. The box shows it in place of the reason that the panes find. |
| `review` | true or false | True for a review task. Its lane shows as `main`. |

`edges`, one object for each depends-on relation: `source` is the task that lands first, and `target` is the task that waits for it.

`sessions`, one object for each session:

| Field | Type | What the panes do with it |
|---|---|---|
| `role` | text | `orchestrator`, `healer` or `walker` for a session that runs now. `heal cycle` for a past healer run. `builder`, `merge` and `review` for a run of a task: the note gives the task. The hours column and the past 12 hours of the wave band use these runs. |
| `milestone` | text | The milestone of the session. |
| `since` | time | The start. The row `now` shows the time since then. |
| `window` | text | The place where a person can watch the session, for example a tmux window. |
| `until` | time | The end. It is null while the session runs. |
| `outcome` | text | How a past run ended, for example `done` or `blocked`. |
| `note` | text | A short fact, for example `2/3` for the second of three heal cycles. |
| `last` | time | The last sign of life: the time of the newest action. The row `now` shows `●` under 30 seconds, `◉` under 2 minutes and `○` under 10 minutes. |

`usage`: one object with the list `windows`. Each window has `name` (for example `5h`), `percent` and `resets` (for example `3h`). A window can also have `reset_at` (the reset as a time), `rate` (per cent for each hour, measured) and `full` (the time that it gets to 100 per cent at that rate).

`locks`, one object for each lock that is held:

| Field | Type | What the panes do with it |
|---|---|---|
| `name` | text | The name. The row `gate` shows a lock whose name starts with `main` as the main lock. |
| `holder` | text | Who holds the lock, in words, for example `merge of t59`. |
| `since` | time | The time that the holder took the lock. |
| `lane` | text | The lane of a slot lock. The row `lanes` shows the slots of each lane. |
| `live` | true or false | False when the process that holds the lock is gone. The row `lanes` shows the slot as gone and names its holder. The panes never count it as busy. |

`plan`:

| Field | Type | What the panes do with it |
|---|---|---|
| `waves` | list | The open waves of each open milestone, in run order. Each wave has `milestone`, `n`, `tasks`, `minutes` (at the terms of the planner) and `paced` (at the measured pace). |
| `critical` | list of text | The tasks on the critical path to the tag of each open milestone. |
| `projected` | object | For each milestone that is not done, its projected window: `start` and `end`. |
| `finish` | time | The projected finish of all open tasks. |
| `builder_minutes`, `builder_n` | number | The minutes of one builder run, and the count of runs that they come from. A count of 0 means the minutes of the planner. |
| `merge_minutes`, `merge_n` | number | The same for one merge. |
| `lanes` | object | Each lane and its count of slots, in the order that the row `lanes` shows them. |
| `builder_samples` | list of numbers | The minutes of each measured builder run. The estimate shows their p25 and p75. |
| `schedule` | object | For each open task, its projected window: `start` is the start of its build and `end` is its landing. A wave, a milestone tag and `finish` end at the last landing of their tasks. |
| `spread` | object | For each open milestone, the window of its tag: its tag at the p25 and at the p75 of the builder minutes. It is empty with fewer than two samples. |
| `finish_spread` | window | The finish of all open tasks at the p25 and at the p75 of the builder minutes. The estimate shows it as the range. |

`blockers`, one object for each open blocker row. Its fields are `id` (its number), `task` (the task that it holds), `milestone` and `kind` (its class). The other fields are `who` (who answers it), `since` (the date that it was opened) and `text` (its first sentence). `opened` is the time of the commit that added the row, and `closed` the time of the commit that removed it; `closed` is null while the row is open.

`events`, one object for each line of the stream:

| Field | Type | What the panes do with it |
|---|---|---|
| `time` | text | The time of the event. When it is empty, the pane uses the minute that it reads the event. |
| `source` | text | Who did it. The first word selects the color: `driver`, `orchestrator`, `builder`, `healer`, `walker` or `merge`. |
| `text` | text | What happened. |
| `level` | text | `info` or `error`. The pane shows an error in red. |
| `kind` | text | `log`, `says`, `result`, `prompt`, `heartbeat`, `error` or the name of a tool. A tool name shows in bold before the text. The kind `reset` starts a new backlog. The kind `divider` shows as a rule of `═`. |
| `outcome` | text | For a tool call with its result: `ok`, `failed` or `timed out`. An event with a tool kind, no outcome and no result is a call that waits: the last row of the stream shows it. |
| `result` | text | The first line of the result of the call. |

### Implement Source

1. Read the protocol `Source` in `tmux_tui_dashboard/source.py`. It has one method for each part of the model: `project()`, `milestones()`, `tasks()`, `edges()`, `sessions()`, `events(since)`, `usage()`, `locks()`, `plan()` and `blockers()`. The method `open_calls()` is optional: it gives the tool calls that wait for their results, for the last row of the stream.
2. Write a class with these methods. Each method gives objects of the types in `tmux_tui_dashboard/model.py`.
3. Read all of your data in `refresh()`. The panes call `refresh()` once before each frame, and then the other methods.
4. Make `events(None)` give all the events that you have. Make each later call give only the new events.
5. Set `TMUX_TUI_DASHBOARD_SOURCE=python:<module>:<Class>`. The module must be on the Python path.
6. Run `python3 -m tmux_tui_dashboard.source --dump FEED.json`. Compare the feed with `tmux_tui_dashboard/feed.sample.json`.

## The files

| File | Job |
|---|---|
| `tmux_tui_dashboard/model.py` | The types of the model, and `Snapshot`, the model that one frame of a pane draws. |
| `tmux_tui_dashboard/source.py` | The protocol `Source` and the function `load_source()`. |
| `tmux_tui_dashboard/json_source.py` | The source that reads a JSON feed file. |
| `tmux_tui_dashboard/layout.py` | The layout of the task graph. |
| `tmux_tui_dashboard/progress.py` | The top pane. |
| `tmux_tui_dashboard/phases.py` | The middle pane. |
| `tmux_tui_dashboard/follow.py` | The bottom pane. |
| `tmux_tui_dashboard/palette.py` | The one color table of the three panes. |
| `tmux_tui_dashboard/feed.schema.json` | The JSON schema of the feed. |
| `tmux_tui_dashboard/feed.sample.json` | A sample feed of a small build with three milestones. |
| `bin/*.sh` | Start the three panes. |
| `tests/check_panes.py` | The checks of the panes. |
| `scrub.py` | The scrub check. |
| `check.sh` | Runs all the checks. |
| `CHANGELOG.md` | The history of the panes, newest first: each commit that changed them. |
| `LICENSE` | The MIT License. |

## The task graph

- Each open task is a box. A box stands to the right of each task that it depends on.
- A box is as tall as its text. A long name wraps between words, and no text is cut.
- The top border of a box shows the state glyph and the milestone.
- A box on the critical path has a heavy border and the sign `»`, both in orange.
- The layers flow from left to right. When the next layer does not fit the width, it continues on the free rows below a column, under the mark `↳ continued`.
- Only the layers that fit nowhere go into one box `+n more ▸`, in a free corner of the graph.
- An edge runs only in the gaps between the columns and along the last row of the graph. No edge crosses a box.

## The color rule

- Each color has one meaning. Green is done or passed, yellow is in flight, and red is blocked or failed. Aqua is a healer at work.
- Orange is the critical path. Orange also marks time past the plan.
- Blue is a task that is ready. Gray is queued, projected or the frame of the pane.
- Color never carries a meaning alone. Each state also has its glyph or its word.
- `TMUX_TUI_DASHBOARD_COLOR=none`, `8` or `256` sets the color depth. A gruvbox-material palette module sets the colors when it is installed (`TMUX_TUI_DASHBOARD_THEME`).

## The checks

Run `./check.sh`. It runs `tests/check_panes.py` and `scrub.py`, and its last line is `check: PASS`.

- `tests/check_panes.py` draws the three panes from the sample feed. It checks the widths, the word wrap and the frame painter. It also checks the text at each color depth, the feed read again, the layout of the task graph and the three pane commands.
- `scrub.py` makes sure that the tree holds no path, hostname, address or name of the machine or the build that it came from.

## License

This repository uses the MIT License. The file `LICENSE` holds the text of the license.
