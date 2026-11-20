# Tareas: AI → Jira

[Español](README.md) · **English**

Local web app to log the team's work in **Jira Cloud** and follow sprint progress.

- **Tasks:** you describe the work you did in your own words, or upload log files, and an AI
  (Claude or a local Ollama model) breaks it down into epics and tasks ready for Jira. You review them in a table
  and upload them with one click.
- **Sprint progress:** completed-work report for the team and for each person, plus tasks uploaded per day.
  Data is read from Jira and weekends are left out of the time axis.

Built with FastAPI, SQLite and a single HTML page with no front-end dependencies.

## Requirements

- Python 3.11+
- A Jira Cloud account with an [API token](https://id.atlassian.com/manage-profile/security/api-tokens)
- At least one AI:
  - [Claude Code](https://claude.com/claude-code) with an active session: uses your Claude account, no API key needed
  - an Anthropic API key
  - [Ollama](https://ollama.com) running locally (a 7B model or larger is recommended)

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env      # then fill it in
```

Main `.env` variables (all of them are explained in `.env.example`):

| Variable | Purpose |
|---|---|
| `JIRA_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` | Jira connection |
| `LLM_PROVIDER` | Default AI: `claude_code`, `claude` or `ollama` (can be changed in the app) |
| `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` | Only for `claude` (Anthropic API) |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Only for `ollama` |
| `JIRA_STORY_POINTS_FIELD`, `JIRA_START_DATE_FIELD` | Optional; if left empty they are detected by name |

## Usage

```bash
./tareas check    # checks the connection to Jira, Claude and Ollama
./tareas          # opens the app at http://127.0.0.1:8765
```

### Autostart

`inicio.sh` starts the app in the background (if it is not already running) and opens a Chrome window with the app and
the tabs listed in `pestanas.txt` (one URL per line). To run it when you log in to GNOME, create
`~/.config/autostart/tareas.desktop` with `Exec=<project path>/inicio.sh`; disable it by deleting that file
or in "Startup Applications". Each startup is logged in `inicio.log`.

### Tasks

1. In **⚙️ Settings** you choose the assignee, sprint and dates given to new tasks.
   If the dates are left empty, each task starts today and ends on the last day of the month.
2. **New breakdown** has three modes:
   - ✍️ **Write:** describe what you did. If you name someone on the team, the task is assigned to that person.
   - 📄 **Upload .txt:** `.txt`, `.md`, `.log`, `.csv` or `.json` files up to 2 MB.
   - 📋 **Quick list:** one task per line, no AI; a `# PROJECT` line picks the epic.
   With the Planner → Story → sub-tasks method, the AI receives the open Stories from Jira (the Planner tasks)
   with their sub-tasks and attaches each piece of work as a **sub-task** of its Story (1 point each; the sprint is the
   Story's sprint). Anything that does not fit a Story stays "No Story" and is uploaded as a standalone task of the epic.
   If the text says something is already done, the task is marked "Done" and uploaded as Finished; and if that work
   already existed as a planned sub-task, it is not duplicated: the app offers to **mark it as finished** in Jira.
3. The **task list** groups tasks by epic and shows title, assignee, sprint, dates and Jira key (or
   "Pending"); it can be filtered by epic, person or status. Clicking a task opens a side panel to edit
   title, epic, assignee, sprint, dates, points, type, priority, labels and description, and to upload or delete it.
   Checkboxes apply changes to several tasks at once, upload them or delete them. Changes are saved automatically.
4. **Upload to Jira** creates the epics and their tasks and moves them into the sprint. Tasks that already have a key
   (e.g. `PRJ-123`) are updated instead of duplicated. Deleting a task in the app does not delete it in Jira.

Breakdown rules:
- Each task is a meaningful deliverable (1 story point, from a few hours to a day). Intermediate steps
  go as bullet points in the description.
- Epics are the projects. If the project already exists as an epic in Jira, that epic is used.
- Titles follow the format `PROJECT - description - extra info`, where the project is the epic name.
- In Jira, each task is created with its epic as parent and without labels.

### Sprint progress

Open it from the **📈 Sprint progress** tab or at `http://127.0.0.1:8765/#sprint`. At the top you choose the
sprint and the person (by default, the connected Jira user).

- **Completed work report:** the same report Jira shows, for the whole team.
  - **Work scope (red):** points of the tasks in the sprint.
  - **Completed work (green):** points of closed tasks.
  - **Guideline (grey):** ideal pace, from 0 at the start to the current scope at the end of the sprint.
  - Lines step at the moment each event happens, and from "Today" on the scope is projected as a dotted line.
  - Below, the **activity table** lists each event and its change.
- **My completed work:** the same report, only with the tasks assigned to the selected person.
- **Uploaded tasks:** tasks created in the sprint per working day, cumulative and per day.

Time axis:
- It runs from the start to the planned end of the sprint. If the sprint is still open after that date, it is
  extended to today (or to its close date) and the planned end is marked.
- Saturdays and Sundays are removed; anything that happened on a weekend is shown at the start of Monday.

Data is read from Jira when the view opens, when the sprint changes or when you press ↻.

### Individual historical performance

Collapsed section at the end of the sprint view. It is only requested from Jira when expanded, because it goes through
every issue in the project (about 10 s); the server caches the result for 10 minutes and ↻ reloads it.

- You choose the person (by default, the Jira user), the measure (points or tasks) and the period (full
  history or the last 6 / 3 closed sprints).
- Each closed issue (excluding epics) counts in the last sprint it was in and for its current assignee; if it
  never had a sprint, in the sprint whose period contains its resolution date.
- So that being in more or fewer sprints gives no advantage, the whole comparison uses only the closed sprints the
  selected person was in (within the period), and compares the average per sprint, not the cumulative total. For each
  person, only those sprints in which they were on the team count (from their first to their last sprint with something
  closed, including sprints at 0 in between); the table shows how many sprints they have in common. The current sprint
  is not included in the averages.
- "vs rest" compares the person's average with the per-person average of everyone else in those same sprints, and
  "% of team" is their share of what was closed in those sprints.
- It shows indicators, a chart per sprint (person against the average and range of the rest), a ranking by average
  and a team table.
- **Trend:** average of the latest sprints compared with the earlier ones (3 and 3, or fewer if there are not many;
  4 sprints are needed), next to the rest of the team in those sprints.
- **Split by project:** for each epic, what % of the person's work goes to it compared with the team's %, and
  what share of the project they did. Sub-tasks and tasks without an epic count as "No epic".

### Limitations

- The completed work report uses the internal API Jira uses to draw its own report
  (`/rest/greenhopper/1.0/rapid/charts/scopechangeburndownchart.json`). It is not a public API, so it may
  change without notice.
- The personal report counts each task for its current assignee; it does not reflect reassignments during the sprint.
- The sprint selector shows active and future sprints.
- Historical performance attributes everything to whoever has the task assigned today, and a sprint with very little
  work from someone can extend their period on the team; with fewer than 3 sprints it is marked "little data".
- If Jira rejects an optional field (priority, story points, start date) because it is not on the project's screen,
  the task is created without it and a warning is shown in the result.

### My tasks

The app has a side menu with five sections: three **My tasks** views (Inbox, Board and Table),
**AI breakdown** and **Sprint progress** (both with a header summarising the plan or the sprint); at the bottom, the
light/dark mode switch. The logo goes to the Inbox and the avatar goes back to your own tasks. The three My tasks views
show the Jira Stories and tasks assigned to the person selected at the top (by default, the connected user),
with a scope selector: **🏃 Current sprint**, **📥 Backlog** or **All**.

- **Inbox:** greeting with open and overdue items and working days left in the sprint; the **Needs your attention**
  block (overdue and due soon, with "Mark as finished" and "Move to" the end of the sprint); collapsible epics with their
  progress (finished ones are hidden under "See N finished"); and on the right the sprint ring, the summary by status
  and the session activity.
- **Board:** To do / In progress / Finished columns; dragging a card changes its status in Jira.
- **Table:** filter chips (open, overdue, due soon, finished, all), rows grouped by epic.

In all of them, the status pill opens a menu to change it, and clicking a task opens the **detail panel**:
title, status, assignee, start, end, epic or Story, description and, for a Story, its sub-tasks (with a
checkbox to close or reopen them and a field to create another one). **Save changes** writes directly to Jira:

- Sub-tasks can only be edited if the user created them; the rest open as read-only (🔒).
- Changing a Story shows a warning first, because it mirrors a Planner task.
- If the issue changed in Jira since it was loaded, you are asked which version to keep.
- Closing a Story with open sub-tasks offers to close them too.

**Sprint and backlog dates.** Only the dates of items in the active sprint are urgent: "Overdue" and
"Due soon" (red and orange, in the Inbox, the alerts and the menu counter) only count those. In the backlog the
date is a guide: it is shown in grey ("· past" if it has passed) and late items go to the "Backlog with past date"
alert group. Each task has a 🏃 Sprint or 📥 Backlog tag. Overdue and due-soon items show the quick
**→ end of month** button ("→ Oct 31"), which moves the end date to the last day of the current month; the detail panel
has an "End of month" button next to the end date field.

The search box at the top (**Ctrl+K**) goes to the filtered Table. The 🔔 bell opens the **alerts** side panel
(overdue, due soon, pending Stories, ready to close, without sub-tasks and inconsistent dates); the red
number in the menu is the overdue and due-soon items of the connected user. Titles are shown without the uppercase
project prefix ("PROJECT/CLIENT - …"), because the epic is already shown in its colour tag.

## Structure

| File | Contents |
|---|---|
| `tareas_app/llm.py` | Breakdown prompt, calls to each AI and plan building (epics, titles, assignees, dates) |
| `tareas_app/jira.py` | Jira client: metadata, issue creation and update, sprint chart data |
| `tareas_app/models.py` | Data models: AI output and app plan |
| `tareas_app/server.py` | API (FastAPI) |
| `tareas_app/store.py` | SQLite persistence (`tareas.db`) |
| `tareas_app/config.py` | Reads `.env` |
| `tareas_app/static/index.html` | Whole interface: task and sprint views, SVG charts |

| Endpoint | Description |
|---|---|
| `GET /api/config` | Jira project data: team, issue types, sprints, epics and connected user |
| `GET /api/state` · `PUT /api/plan` · `PUT /api/defaults` | Saved plan and settings |
| `POST /api/breakdown/text` · `POST /api/breakdown/file` | AI breakdown |
| `POST /api/push` | Upload to Jira |
| `GET /api/sprint/{id}/issues` | Sprint tasks with creation date and assignee |
| `GET /api/sprint/{id}/burnup?assignee=` | Completed work report (team or one person) |
| `GET /api/performance?refresh=` | Closed points and tasks per person and sprint across the whole history (10 min cache) |
| `GET /api/mywork?account_id=&done=` | A person's Stories and sub-tasks, with epics and progress |
| `PATCH /api/issues/{key}` | Edits an issue in Jira (403 if it is someone else's sub-task, 409 if it changed since it was loaded) |
| `POST /api/issues/{key}/status` | Changes the status (to do, in progress, finished) |
| `POST /api/issues/{key}/subtasks` | Creates a sub-task in a Story |

## Development

- The server does not reload by itself: restart it after changing Python code.
- `.env` (Jira token) and `tareas.db` (local data) are in `.gitignore`.

## License

[MIT](LICENSE)
