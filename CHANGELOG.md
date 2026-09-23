# Changelog

tmux_tui_dashboard started as the dashboard of the BLQC build, an automated build of a desktop program. Its history there
is summarised below, newest first; the short sha is the commit in that build's repository.

## 2026-09-23
++ b/ttd-428800d/CHANGELOG.md

- `ab2608e` What blocks what, and for how long: the history of every blocker row, the age of a blocker row and the
  open tasks it holds on a blocked box, a row that counts the last 24 hours, and a row of the chart that shows how
  many blocker rows were open at each time.
- `4e08bf8` Where the hours went: 12 cells on each milestone row for building, merging, review, healing and nothing
  running, and the past 12 hours of the wave band: the builders at work and the merges.
- `faf3487` The stream pane survives a restart: the follower clears its pinned row and its margins when it stops.
- `3f7f256` The stream shows each tool call with its outcome on one line, keeps a row pinned under it for the calls
  in flight, draws a rule for a recorded wave, a tag and a new session, and keeps whole words with no ellipsis.
- `14e889a` The stream stops restarting after its first batch.
- `18ee57e` The gate row shows the seven steps of the newest full gate and the gates of the last 24 hours; the usage
  row shows the rate of each window and when it fills; the stream draws a rule over a quiet gap of 10 minutes.
- `ffde811` One finish from one schedule of the open tasks: the estimate shows the finish with its p25 to p75 range
  and the finish at the merge rate of the last 72 hours; the chart draws the burn-up of a long milestone, folds the
  oldest finished milestones only when rows are short, and shows each description whole or not at all.
- `7fd8529` A task carries one name in both panes: the timeline prints the graph's name, whole.
- `8d6ebcb` Each running session shows its last sign of life; an idle build says since when and what landed last;
  a walk row shows the newest walk of the program stage by stage; the stream prints the walker's notes.
- `f82678c` The panes stop contradicting themselves: every open task is a box, waiting has its own glyph, one
  finish for each milestone, names read as words, and the stream drops boilerplate and temporary paths.
- `8d20fd3` The gate row shows the newest whole gate; a lanes row marks slots whose session is gone; the stream
  says once that a gone session went silent; a check fails on a blank row.
- `86d5348` The critical path takes the palette's orange: the heavy borders and the » of the task graph, the » of
  the timeline and the legend. The usage warning turns yellow from 75 per cent. The stream keeps its newest line on
  the bottom row of its pane.
- `5cadac5` The task graph is laid out by a pure function: layers by the longest chain of dependencies, boxes ordered
  by the barycenter of their neighbours, each box as tall as its text, the layers flowing left to right and then
  down the free rows below, and one `+n more ▸` box only for what fits nowhere. Edges stay orthogonal and never
  cross a box.
- `61b1311` The three panes draw one model through a Source: the model's types, the Source protocol, the source of
  the build, a JSON feed with its schema and a sample, and a check that the build's source and its own feed draw
  the same panes.
- `cecad6a` Each open blocker row gets a row under the head rows; the finished tasks the open ones depend on are
  drawn as green boxes in the first column of the graph.
- `5da8b6a` A layer that does not fit across continues on the free rows under the rightmost columns.
- `bec72c6` More colours of the one palette, each with one meaning; the `+n more` box moves to the corner.
- `4892d89` Boxes wrap their text and are as tall as it; each box shows its milestone on its border.
- `dd20dff` Each box is as wide as its text, and shows the whole name of its task.
- `2d14840` The task graph is drawn as boxes in dependency layers, with edges box to box.
- `319d9a4` The top pane's body becomes the task graph.
- `531d008` The colour table reads the machine's one palette.
- `9260405` The stream draws one line for each event, with its own time and its real source.

## 2026-09-22

- `2607c03` The top pane is decluttered: now, blocked and next first, one table, a status strip, one legend last.
- `1c4392f` The middle pane becomes a Gantt chart on two time scales.
- `bc223ee` Review rows are told from build rows by one rule.
- `bba7157` Three panes, one design.

## 2026-09-22, earlier commits

- `9385b4b` The open rows of a cut are cut to their cell on the phase timeline, so the caption beside them stays in line.
- `6292f10` The dashboard's top two panes show the milestone rows by wave and the overrun of the timeline.

## 2026-09-19, earlier commits

- `3766a37` The panes price a merge at its median - the time from a report to its landing also holds every stall between them.
- `26d3ffe` The pace of the panes is measured over the milestone's recent sessions, and the main lock names a merge in either order of its note.
- `db4e9d3` The panes read a tagged milestone with open tasks as not done, a built task as waiting when no session runs, and a healer at work as now.
- `4d38504` The three panes read the live build - a builder has reported at its end_turn, the gate row reads the verdict of run_checks.
- `c201c6a` A gate started inside another gate takes nothing by process ancestry rather than by an environment variable a test can drop, a rule.
- `23a233c` The stream pane follows an orchestrator or a healer by the prompt that session was given, never by a tool result that quotes one.

## 2026-09-18, earlier commits

- `4ca5068` The dashboard panes always come back to live output — a pane held in copy mode is cancelled after one heal cycle,.
- `d60397b` The pane counts a merge, finds the ci/fast line and keeps the heal rows.
- `fd2f318` A milestone needing only its review is ready, a pane reloads its own code, and the pre-wave budget instruction is withdrawn.

## 2026-09-17, earlier commits

- `e00e8a9` The dashboard shows movement, not only state.
- `1a253b6` The drawing gets two fifths of the pane, and the phase column stops repeating itself.
- `9aa9e61` The top pane shows where it used to explain.
- `449d009` The milestone picture holds the milestone's own tasks.
- `b5ab739` The colour group renders every depth from one frozen snapshot.
- `2034920` The check suite holds the stream too, as a follow group.
- `ad7dc00` The palette reads the box's gruvbox-material table.
- `bef4397` The furniture that carried no colour goes dim too.
- `d0c9990` The screen's furniture goes grey and the accent is kept for state.
- `ce05080` Hue is spent by distance from now, so a finished milestone is grey.
- `806d19e` The usage parse is split from the pane read and put under check, with the gate cases restored.
- `8c7e650` One rule for a commit message the shell reads first, and ci/check_panes.py keeps the pane checks.
- `7e62efe` The two usage windows in the header, read from a running session and never inferred.
- `2164c56` The gate's pytest row states a test result, not any line that quotes one.
- `8257f5e` One palette for the three panes, with colour as a second channel.
- `a8388d1` The dashboard repaints in place instead of erasing the screen, and the stream scrubs control characters.
- `4fddbd3` Titled section rules, the open blocker by name and class, a velocity strip, and a stall flag on the builder.
- `f0c1795` A zoomed phase pane lists the running phase's tasks, and ci/tmux.sh goes back to mode 644.
- `9132129` A third pane, the phase timeline.
- `0277c2e` The wave grid gets a gutter, a token-boundary cut, a chain header and a collapsed row for a finished milestone.
- `b893444` The task graph sizes from the pane, with wider boxes, deeper layers and task numbers in the wave grid.
- `91e5dd5` The tmux dashboard fits the pane at any width, wraps instead of clipping, and keeps the operator's zoom.
- `d775226` Two findings of the healer rehearsal, the heal cycles keyed by their start line and the count file read without a shell error.
- `58bfb00` The dashboard, the stream and the tmux window know the healer.
- `4fedc14` The stream says idle when only the driver spoke last, not that the driver composes.
- `7268b12` The stream heartbeat says which builder the orchestrator waits for and how far it is.
- `728ad14` The stream heartbeat names who is composing, what it last said and what its worktree holds.
- `ee06211` The stream heartbeat says the model is composing, not quiet.
- `76ef32b` The follower and the dashboard find the orchestrator marker in an interactive transcript.
- `22ba81a` Node-and-edge task graph, pane-true rendering and a pane restart.
- `5480495` The dashboard keeps its header line in a pane of any height.
- `524bea2` Task-graph dashboard and follower heartbeat.
- `3042b9b` Task-level dependency proposal, the two guard defects a task found, the portrait tmux window and the pane launch (a rule), on the owner's instruction.
- `3088ee2` Clanker integration of the concurrent driver and the tmux session (a rule), on the owner's instruction.
- `ae8aaef` Concurrent milestone orchestrators, lane locks and the tmux dashboard (a rule), on the owner's instruction.
