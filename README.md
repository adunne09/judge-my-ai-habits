# judge-my-ai-habits

A bell curve for AI-assisted work. Every session in which you worked with an AI
agent gets two scores. **Complexity** is how much work it would take a skilled
professional, working without AI, to do everything you asked for, from a couple
of minutes up to months of work for a team. **Leverage** is how much of the work
you delegated versus steered, from a question answered from the model's own
knowledge up to an autonomous loop of agents working for days. The scores land
in SQLite, so you can plot the distribution, track its mean over time, and merge
results from every machine and every agent harness you use.

The point is the shape, not the count. "How many sessions did I run?" says
almost nothing. "Where is the bulk of my work on a scale from a minute to
team-months, and is it moving right, toward bigger jobs and more delegation?"
says a lot.

![Complexity histogram](charts/complexity.svg)

![Leverage histogram](charts/leverage.svg)

![Weekly trend](charts/trend.svg)

## How it works

- **One scoring request per session.** A session's user messages, the agent's
  actions, its final reply, and a few computed facts about how the session ran
  (steps per message, active working time, subagents launched, other AI tools
  invoked) are sent as one state to [TypeSafe](https://www.typesafe.ai)'s Jev
  scoring model. Jev answers several questions in parallel over that state.
- **Complexity is a 7-level scale anchored at both ends.** The bottom is
  calibrated on the smallest real sessions: greetings, tool checks, and
  questions answered from knowledge. The top is anchored on the most complex
  usage people post about publicly: autonomous multi-agent campaigns, such as a
  two-week framework migration shipped as ~600 pull requests, a compiler port,
  or hundreds of designed proteins sent for lab testing. Those score 5.3–6.0,
  above any session recorded so far, so the top of the scale has headroom.
- **Leverage is judged separately from size.** A tiny task can be delegated
  ("clean this up") and a huge one can be steered. The scale runs from answered
  from knowledge → a lookup → steered step by step → delegated goal →
  orchestrated agents → autonomous loop.
- **Only personal work feeds the trend.** Each session also gets an origin
  classification (personal work, scripted job, or test/benchmark) plus
  deterministic flags for forks and program-launched sessions. Everything is
  scored, but the report and charts track only the personal subset.
- **Validated against hand labels.** Against 65 hand-rated sessions (31 for
  development, 34 as a blind holdout), the headline score agrees at Spearman
  0.96 / 0.95. Repeat runs differ by at most 0.05.
- **Comparable over time and across tools.** The model is pinned, and every row
  records the scorer hash and model version. Changing the questions rescores
  everything automatically, and every harness shares the same questions.
- **Mergeable.** Each machine writes its own SQLite database. Databases from
  different machines and harnesses merge into one.
- **Shows the change.** By default the report compares your last 30 days with
  the 180 days before, for session complexity and token usage, so you can see
  whether the curve is moving.

The method is written up as a harness-independent [specification](SPEC.md), so it
can be reimplemented for any agent client.

## Supported harnesses

| Harness | Status | `--harness` |
| --- | --- | --- |
| [OpenCode](https://opencode.ai) v2 | Supported | `opencode` (default) |
| Claude Code | Coming soon | |
| Claude Desktop | Coming soon | |
| Codex CLI | Coming soon | |
| Cursor | Coming soon | |

More are coming very soon. To add one yourself, see
[Add support for another harness](#add-support-for-another-harness).

### Harness notes: OpenCode

Needs OpenCode v2 on `PATH` or in `~/.opencode/bin`. Sessions are read through
`opencode api`, so the adapter works with whatever server and storage the global
installation uses and never opens OpenCode's database directly. Responses are
written to a temp file, because `opencode api` can truncate large responses
written to a pipe. Child sessions (`parentID`) are subagents. A launcher
`metadata.source` or per-session `permissions` marks program-launched sessions.

## Run it

It's a single Python file with no dependencies. It needs Python 3.9+ on macOS or
Linux, a supported harness, and a TypeSafe API key.

```sh
export TYPESAFE_API_KEY=...            # https://console.typesafe.ai
./session-complexity                   # score new or changed sessions on this machine
./session-complexity report            # recent change, histograms, tokens, and a monthly trend
./session-complexity report --by week
python3 make_charts.py                 # regenerate the SVG charts in this README from the DB
```

`report` covers personal sessions over **all of your history** by default. It
opens with the **change**: your last 30 days compared with the 180 days before
them, for session complexity, leverage, and token usage. Windows of different
lengths are compared fairly, as rates per 30 days and as per-session figures. If
you have less than six months of history, the baseline is all the history before
the recent window. If you have less than a month, the recent window is all the
history there is, and there's no baseline yet. Example:

```text
CHANGE — last 30 days vs the 180 days before:
  recent:   Sep 20, 2026 – Oct 20, 2026 (30 days)
  baseline: Aug 3, 2026 – Sep 20, 2026 (48 days; all the history there is, 180 requested)

                                  recent   baseline   change
  sessions                           248        253
  sessions per 30 days               248        157   +57.5%
  complexity mean                   1.84       1.77   +0.08 (+4.3%, +0.08 sd)
  complexity median                 1.80       1.76   +0.04
  leverage mean                     2.47       2.45   +0.02
  tokens per 30 days               1.51B    566.47M   +165.7%
  tokens per session, mean         6.07M      3.60M   +68.7%
  tokens per session, median     602.02K    578.00K   +4.2%
```

The complexity change is also given in standard deviations of the baseline
(`sd`), which is the natural unit for "how far has the bell curve moved". Token
counts include subagents.

| `report` flag | Effect |
| --- | --- |
| `--since 2026-06-01`, `--until 2026-09-30` | Limit everything to a date range. `--until` also ends the recent window (default: now) |
| `--recent-days 30` | Length of the recent window |
| `--baseline-days 180` | Length of the baseline window just before it |
| `--by month\|week\|day` | Grouping for the trend table |
| `--all` | Include tests, scripted jobs, and forks |
| `--db PATH` | Read a different database, for example a merged one |

Results go to `~/.local/share/judge-my-ai-habits/sessions.sqlite`. Change that
with `--db`. (A database at the older `opencode-session-complexity` location
keeps being used if it exists.) Each row is keyed by `(machine, session_id)` and
records its `harness`. `machine` is the short hostname; override it with
`--machine`.

Runs are incremental. A session is only sent to Jev again if it changed since its
last score, if its last attempt failed, or if the questions changed. A full first
run on about 1,260 sessions took about a minute and used 3.4M Jev input tokens,
about $0.14.

Other `score` options:

| Flag | Effect |
| --- | --- |
| `--harness opencode` | Which harness to read sessions from |
| `--since 2026-09-01` | Only sessions created on or after that date |
| `--limit N` | Score at most N sessions, newest first |
| `--session <id>` | Score specific sessions (repeatable) |
| `--rescore` | Score again even if nothing changed |
| `--dry-run` | Print exactly what Jev would see, without calling it |
| `--workers 6` | Parallel sessions |
| `--model jev-1.13.0` | Jev model, pinned on purpose (see below) |

## Several machines and harnesses

Run the script on each machine, for each harness you use. Then copy the
databases to one place and merge them:

```sh
mkdir -p data
scp laptop:.local/share/judge-my-ai-habits/sessions.sqlite data/laptop.sqlite
scp desktop:.local/share/judge-my-ai-habits/sessions.sqlite data/desktop.sqlite
./session-complexity merge data/*.sqlite -o all.sqlite
./session-complexity report --db all.sqlite
```

Merging is idempotent: re-merging a newer copy from a machine replaces that
machine's rows. Databases created by older versions merge too. If the inputs
were scored with different questions or models, the merge prints a warning,
because those scores aren't directly comparable.

DuckDB can also read all of them together without merging:

```sql
INSTALL sqlite; LOAD sqlite;
SELECT * FROM sqlite_scan('data/laptop.sqlite', 'sessions')
UNION ALL BY NAME
SELECT * FROM sqlite_scan('data/desktop.sqlite', 'sessions');
```

## What gets scored

Each top-level session becomes one request to Jev. Subagent sessions are rolled
into their parent: their tokens and cost are added, and their work shows up in the
parent's actions. The request state contains:

- `session_title`
- `user_messages`: everything the user typed. Each message is capped at 2,500
  characters. If the total is over 12,000 characters, the first and latest
  messages are kept and messages from the middle are dropped.
- `agent_actions`: a one-line summary of each tool call in order, for example
  `shell: git clone …`, `edit: ~/repos/x/y.ts`, or `linear.save_issue: …`.
  Tool names from every harness are mapped onto one shared vocabulary, so the
  same work reads the same way whichever tool did it. Repeats are collapsed. The
  list is capped at 80 entries, sampled evenly from the middle when longer.
- `agent_final_reply`: the agent's last reply, capped at 1,800 characters.
- `work_pattern`: plain-language facts about how the session ran, computed in
  code: how many messages the user sent, how many agent steps per message, how
  long the agent actively worked (gaps over 30 minutes count as idle, not work),
  how many subagents were launched, and which other AI CLIs (`codex`, `claude`,
  `gemini`, `amp`, …) the agent ran from the shell.

Tool outputs, reasoning, and file contents are left out. A typical state is 1k to
7k tokens. [SPEC.md](SPEC.md) defines every rule exactly.

Sessions with no user message or no assistant reply get `status = 'empty'` and
aren't sent to Jev.

### Questions

All seven questions go in the same request, so they're answered in parallel over
the same state.

**`complexity` (0 to 6)** is the headline number. It's a Score question: "How much
work would it take skilled professionals, working without AI, to do everything the
user asked for in this session?" The levels are:

| Level | Meaning |
| --- | --- |
| 0 | A couple of minutes |
| 1 | Under an hour: one small, well-defined task |
| 2 | A few hours: a multi-step task |
| 3 | About a full day: a substantial piece of work |
| 4 | Several days: a multi-part project |
| 5 | Weeks: a large project for one person |
| 6 | Months of work for a team of specialists |

Level 6 is anchored on the most complex real usage people post about publicly
(frontier practice, found by surveying X/Twitter in October 2026): migrating a
large production web app to a different framework through hundreds of pull
requests (a two-week autonomous loop, ~600 PRs), porting a compiler to another
language, and computationally designing hundreds of candidate proteins and
sending them for lab testing. In these sessions the user only sets a goal and
checks in every few days. Ordinary interactive sessions sit far below that.

Each level also carries generic examples. The score is the probability-weighted
level, so it's continuous, for example 2.37. The probability for each level is
stored too, in `complexity_p0` through `complexity_p6`.

**`leverage` (0 to 5)** asks "How did the user put AI to work in this session?"
It judges the way work was delegated and organized, independent of size:

| Level | Meaning |
| --- | --- |
| 0 | Answered from the model's own knowledge, no actions taken |
| 1 | One or two lookups or commands run on the user's behalf |
| 2 | Steered step by step, agent acts between messages |
| 3 | Delegated a goal; the agent planned, carried out, and checked the work |
| 4 | Orchestrated several AI agents: subagents, worktrees, or other AI tools toward one goal |
| 5 | Ran an autonomous agent system: agents plan, implement, review, and verify over many hours or days with occasional check-ins |

The other four Scores are stored as separate dimensions, each from 0 to 3. They
aren't folded into `complexity`:

- `scope`: how many distinct deliverables the user asked for
- `expertise`: how much specialized skill the work needs
- `systems`: how many external systems or codebases the work coordinates
- `open_endedness`: how much the agent had to work out for itself

`origin` is a Choice between `personal_work`, `scripted_job`, and
`test_or_benchmark`. Rows also carry a deterministic flag, `launched_by_program`.
It's set from signals in the harness's own records that a program, not a
person, started the session, such as an SDK or API launch, a scheduler, or a
headless run.

The full Jev answers are kept in `answers_json`. You can recompute anything later
without calling Jev again.

### Why this design

Several designs were compared against hand ratings of 65 sessions on the same
0 to 4 effort scale. 31 of them were used to develop the questions and 34 were a
blind holdout, rated before seeing any Jev output. Spearman rank correlation with
the hand ratings:

| Design | Development | Holdout |
| --- | --- | --- |
| Title and first message only | 0.83 | 0.76 |
| All user messages | 0.94 | 0.93 |
| User messages, actions, and final reply | 0.96 | 0.97 |
| Same, with a generic example on each level | 0.96 | 0.96 |
| v2: 7 levels with a frontier-anchored top, plus `work_pattern` in the state | 0.96 | 0.95 |
| Weighted mix of scope, ambiguity, expertise, and systems | 0.79 | 0.92 |
| `jev-preview` (1.14) instead of 1.13 | 0.96 | 0.95 |
| Tool-call count alone, without Jev | 0.79 | 0.94 |

Takeaways:

- Including what the agent actually did matters. Asking from the first message
  alone misses follow-ups and underestimates sessions that grew.
- A single, concrete "how long would a skilled person take" question beat a
  weighted mix of narrower dimensions. Of those dimensions, `open_endedness`
  tracked overall size least (about 0.5). That makes it a useful separate signal:
  delegating more open-ended work over time is its own kind of progress.
- Counting tool calls is a decent proxy on average, but it rewards an agent that
  flails. Jev rates the request, not the agent's activity.
- Repeat runs differed by at most 0.05.
- Doubling the actions and user-text limits moved scores on the 10 largest
  sessions by about 0.1, which isn't enough to justify the extra tokens.
- The scale has a sixth level ("weeks") because the largest sessions were pinned
  at the top of a five-level scale. Without it, the right tail of the curve can't
  move. Rank agreement was unchanged (0.96 on both sets). Surveying frontier AI
  usage posted on X added a seventh level ("months of work for a team"), anchored
  on autonomous multi-agent campaigns (hundreds of PRs over weeks, compiler ports,
  protein design runs lab-tested in days). Synthetic sessions modelled on those
  posts score 5.3–6.0, above any session recorded so far, so the top of the scale
  has headroom. Rank agreement was unchanged (0.96 dev / 0.95 holdout).

`origin` alone isn't reliable for scripted jobs. In testing it caught all 15
eval sessions, but it called 9 of 13 launcher-created sessions personal work. That
is why the `human_sessions` view also requires `launched_by_program = 0`.

### Validation by harness

Each harness is validated separately with the protocol in
[SPEC.md section 8](SPEC.md#8-validating-a-new-harness), using
`validation/agreement.py` (hand labels vs. scores) and
`validation/check_frontier.py` (the synthetic frontier anchors must stay at the
top of the scale).

| Harness | Dev Spearman | Holdout Spearman | Frontier check | Repeat-run drift |
| --- | --- | --- | --- | --- |
| OpenCode v2 | 0.96 (31) | 0.95 (34) | Pass: 5.3–6.0 complexity, 4.9–5.0 leverage | ≤ 0.05 |

### Keeping scores comparable over time

The model is pinned to `jev-1.13.0` rather than the moving `jev-latest` alias.
Every row records `jev_model` and `scorer_hash`. The hash covers the questions and
the state limits, so if you edit a question, the next run rescores everything.
Compare trends only within one `scorer_hash` and `jev_model`. Every harness uses
the same questions, so they share one hash.

## Querying

The `human_sessions` view keeps scored sessions that are personal work, not forks,
and not launched by a program. Use `sessions` directly for everything.

```sql
-- Bell curve: counts in 0.25-wide bins
SELECT ROUND(complexity * 4) / 4.0 AS bin, COUNT(*) AS n
FROM human_sessions GROUP BY bin ORDER BY bin;

-- Mean shift per month, per machine and harness
SELECT month, machine, harness, COUNT(*) AS n, ROUND(AVG(complexity), 2) AS mean_complexity
FROM human_sessions GROUP BY month, machine, harness ORDER BY month, machine, harness;

-- Expected share of sessions at each level, per week (uses the probabilities, not the rounded score)
SELECT week, COUNT(*) AS n,
       ROUND(AVG(complexity_p0), 3) AS minutes, ROUND(AVG(complexity_p1), 3) AS under_hour,
       ROUND(AVG(complexity_p2), 3) AS hours,   ROUND(AVG(complexity_p3), 3) AS day,
       ROUND(AVG(complexity_p4), 3) AS days,    ROUND(AVG(complexity_p5), 3) AS weeks,
       ROUND(AVG(complexity_p6), 3) AS team_months
FROM human_sessions GROUP BY week ORDER BY week;

-- Leverage: are you delegating and orchestrating more over time?
SELECT month, ROUND(AVG(leverage), 2) AS mean_leverage,
       SUM(leverage >= 3) AS delegated_or_higher, SUM(leverage >= 4) AS multi_agent
FROM human_sessions GROUP BY month ORDER BY month;

-- Token usage over time, including subagents
SELECT month, SUM(tokens_total) AS tokens, ROUND(SUM(cost_usd), 2) AS cost_usd
FROM sessions GROUP BY month ORDER BY month;

-- Complexity per token: are you getting more done per unit of compute?
SELECT month, ROUND(AVG(complexity), 2) AS mean_complexity,
       ROUND(AVG(tokens_total) / 1e6, 2) AS mean_mtokens
FROM human_sessions GROUP BY month ORDER BY month;

-- Your most complex sessions
SELECT day, machine, harness, ROUND(complexity, 2) AS complexity, title
FROM human_sessions ORDER BY complexity DESC LIMIT 20;
```

The `day`, `week`, and `month` columns use the local time of the machine that ran
the script. `created_ms` and `created_at` (UTC) are there for anything finer.

## Add support for another harness

[SPEC.md](SPEC.md) defines the whole method independently of any harness: the
adapter contract, the common message format, the shared tool vocabulary, the
exact state rules, the Jev request, the storage schema, and the validation
protocol. A new harness needs only an adapter. The questions, limits, and model
stay the same, so its scores merge with everyone else's.

The fastest way to add one is to have an agent do it from inside the harness you
want to support. Copy the prompt below, paste it into that harness (for example
Claude Desktop, to analyze your Claude Desktop usage), and change the first line
to name it.

````text
Target harness: Claude Desktop

Add support for the target harness above to judge-my-ai-habits
(https://github.com/adunne09/judge-my-ai-habits). The tool scores AI agent
sessions for complexity (0–6) and leverage (0–5) with TypeSafe's Jev and stores
the results in mergeable SQLite. OpenCode v2 is supported today. Your goal:
`./session-complexity score --harness <id>` works for the target harness, and its
scores are comparable with the existing ones.

Ground rules
- Clone the repo (or open it if it's already local). Read README.md, SPEC.md,
  session-complexity, and validation/ end to end before changing anything.
  SPEC.md is the contract. The OpenCode adapter (class OpenCode, open_opencode,
  and the HARNESSES registry) is the worked example to follow.
- Stdlib-only Python 3.9+, macOS and Linux only. Add the adapter inside the
  single session-complexity script.
- Access the harness's data read-only. Never modify, lock, or migrate it.
- Never print, log, or commit the TypeSafe API key, session content, hand
  labels, or scratch databases.
- Do not change QUESTIONS, the state limits, or the model pin. The scorer hash
  must stay identical so the new rows merge with existing ones. If you become
  convinced a question must change, stop and show me the evidence first.

Step 1: Find the data. Work out where and how the target harness stores session
history on this machine: local files, a local database, a CLI or API, or an
official export. Verify this by inspecting real data rather than assuming.
Report what you found: the location and format, and how sessions, user
messages, assistant turns, tool calls (including MCP tools), subagents, titles,
timestamps, token usage, and program-launched sessions are represented. Also
report what's missing. If history isn't available locally, stop and propose
options (for example an official data export) before writing code.

Step 2: Write the adapter. Implement name, version(), sessions(), and
messages() as SPEC.md section 3 describes, mapping onto the session record and
the common message format, and register it in HARNESSES. Pay special attention
to:
- excluding synthetic user-role messages (tool results, reminders, summaries)
- mapping tool names onto the shared vocabulary, with MCP tools as server.tool
- child sessions and subagents
- the launched_by_program signal
- `updated` times that change whenever a session gains content
- id prefixes, if ids could collide with another harness's

Step 3: Inspect states. Run
`./session-complexity score --harness <id> --dry-run --limit 10`, then
`--dry-run --session <id>` on hand-picked sessions: tiny ones, huge ones,
tool-heavy ones, and ones with subagents. Read every state. The same kind of
work should read the same way it does for OpenCode.

Step 4: Iterate manually with Jev. Use the existing repo as guidance for how
to call the API: the Jev class and QUESTIONS in session-complexity, SPEC.md
section 6, and validation/check_frontier.py. If TYPESAFE_API_KEY isn't set, ask
me for it. Before scoring at scale:
  a. Pick about 30 varied sessions. Label each yourself on complexity (0–6,
     halves are fine) and leverage (0–5) from the states alone, before you see
     any Jev output. Save these as labels-dev.json. Label 20 more the same way
     as a blind holdout in labels-holdout.json, and don't look at their scores yet.
  b. Score the dev set into a scratch database (`--db /tmp/jmaih-dev.sqlite`,
     repeating `--session`), then run
     `python3 validation/agreement.py --db /tmp/jmaih-dev.sqlite --labels labels-dev.json`,
     once as is and once with `--field leverage`.
  c. Read the biggest disagreements. For each one, decide whether the state
     misrepresented the session (an adapter problem) or your label was wrong.
     Change the state construction, rescore with `--rescore`, and compare. To
     test an idea quickly, call Jev directly on a handcrafted or modified state:
     load the script with importlib as validation/check_frontier.py does, call
     `Jev(key, DEFAULT_MODEL).ask(state, QUESTIONS)`, and read each answer's
     `probabilities` and `confidence`, not only its `score`. Keep a table of
     every variant you tried and its Spearman.
  d. Stop when dev Spearman is at least 0.90 with no obvious systematic error.
     Then score the holdout once and report the result honestly, without
     tuning on it.
  e. Run `python3 validation/check_frontier.py`, which must pass. Rescore 20
     sessions twice and confirm that scores move by about 0.05 at most.

Step 5: Run in full and merge. Score every session into the default database
and run `./session-complexity report`. Spot-check the 10 most and 10 least
complex personal sessions, what was filtered out as tests, scripted jobs, or
forks, and the leverage distribution. If a database from another harness is
available, merge them (`./session-complexity merge a.sqlite b.sqlite -o all.sqlite`)
and confirm there's no scorer-hash warning.

Step 6: Document. In README.md, mark the harness as supported in the harness
table, add a "Harness notes" subsection (where the data comes from, mapping
decisions, known gaps), and add its row to "Validation by harness", along with
the variant table from step 4. If you found a gap or ambiguity in SPEC.md, fix
it. Commit on a branch, open a pull request, and summarize for me: what you
found, the decisions you made, the validation numbers, and anything you're
unsure about.
````

## Files

| Path | What it is |
| --- | --- |
| `session-complexity` | The tool: harness adapters, state builder, Jev client, `score`, `merge`, `report` |
| `SPEC.md` | Harness-independent specification of the method |
| `make_charts.py` | Regenerates `charts/*.svg` from a results database |
| `validation/agreement.py` | Spearman and error between your hand labels and the scores |
| `validation/check_frontier.py`, `validation/frontier.py` | Synthetic frontier sessions that must score at the top of the scale |
