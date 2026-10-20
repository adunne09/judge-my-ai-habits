# session-complexity

A bell curve for AI-assisted work. Every session in which you worked with an AI
agent gets two scores: **complexity** — how much work it would take a skilled
professional, working without AI, to do everything you asked for (from a couple
of minutes up to months of work for a team) — and **leverage** — how much of the
work you delegated versus steered (from a question answered from knowledge, up
to an autonomous loop of agents working for days). The scores land in SQLite, so
you can plot the distribution, track its mean over time, and merge results from
every machine you work on.

The point is the shape, not the count. "How many sessions did I run?" says
almost nothing. "Where is the bulk of my work on a scale from a minute to
team-months, and is it moving right — bigger jobs, more delegation?" says a lot.

![Complexity histogram](charts/complexity.svg)

![Leverage histogram](charts/leverage.svg)

![Weekly trend](charts/trend.svg)

## How it works

- **One scoring request per session.** A session's user messages, the agent's
  actions, its final reply, and a few computed facts about how the session ran
  (steps per message, active working time, subagents launched, other AI tools
  invoked) are sent as one state to [TypeSafe](https://www.typesafe.ai)'s Jev
  scoring model, which answers several questions in parallel over that state.
- **Complexity is a 7-level scale anchored at both ends.** The bottom is
  calibrated on the smallest real sessions (greetings, tool checks, questions
  answered from knowledge). The top is anchored on the most complex usage
  people post about publicly: autonomous multi-agent campaigns — a two-week
  framework migration shipped as ~600 pull requests, a compiler port, hundreds
  of designed proteins sent for lab testing. Those score 5.3–6.0, above any
  session recorded so far, so the top of the scale has headroom.
- **Leverage is judged separately from size.** A tiny task can be delegated
  ("clean this up") and a huge one can be steered. The scale runs from answered
  from knowledge → a lookup → steered step by step → delegated goal →
  orchestrated agents → autonomous loop.
- **Only personal work feeds the trend.** Each session also gets an origin
  classification (personal work, scripted job, test/benchmark) plus deterministic
  flags for forks and program-launched sessions. The report tracks the personal
  subset; everything else is scored too but excluded from the bell curve.
- **Validated against hand labels.** Ranked against 65 sessions rated by hand
  (31 development, 34 blind holdout), the headline score agrees at Spearman
  0.96 / 0.95. Repeat runs differ by at most 0.05.
- **Comparable over time.** The model is pinned, and every row records the
  scorer hash and model version; changing the questions rescores everything
  automatically.
- **Mergeable.** Each machine writes its own SQLite database; databases merge
  into one without losing rows.

The current implementation reads sessions from a local OpenCode v2 install —
it's a single Python file with no dependencies, needing Python 3.9+, OpenCode v2
on `PATH` (or in `~/.opencode/bin`), and a TypeSafe API key. It reads sessions
through `opencode api`, so it works with whatever server and storage the global
installation uses, and never opens OpenCode's database directly.

## Run it

```sh
export TYPESAFE_API_KEY=...            # https://console.typesafe.ai
./session-complexity                   # score new or changed sessions on this machine
./session-complexity report            # histogram plus a monthly trend
./session-complexity report --by week
python3 make_charts.py                 # regenerate the SVG charts in this README from the DB
```

Results go to `~/.local/share/opencode-session-complexity/sessions.sqlite`. Change
that with `--db`. Each row is keyed by `(machine, session_id)`. `machine` is the
short hostname; override it with `--machine`.

Runs are incremental. A session is only sent to Jev again if it changed since its
last score, if its last attempt failed, or if the questions changed. A full first
run on about 1,260 sessions took about a minute and used 3.4M Jev input tokens,
about $0.14.

Other options:

| Flag | Effect |
| --- | --- |
| `--since 2026-09-01` | Only sessions created on or after that date |
| `--limit N` | Score at most N sessions, newest first |
| `--session ses_...` | Score specific sessions (repeatable) |
| `--rescore` | Score again even if nothing changed |
| `--dry-run` | Print exactly what Jev would see, without calling it |
| `--workers 6` | Parallel sessions |
| `--model jev-1.13.0` | Jev model, pinned on purpose (see below) |

## Several machines

Run the script on each machine. Then copy the databases to one place and merge
them:

```sh
mkdir -p data
scp laptop:.local/share/opencode-session-complexity/sessions.sqlite data/laptop.sqlite
scp desktop:.local/share/opencode-session-complexity/sessions.sqlite data/desktop.sqlite
./session-complexity merge data/*.sqlite -o all.sqlite
./session-complexity report --db all.sqlite
```

Merging is idempotent. Re-merging a newer copy from a machine replaces that
machine's rows. If the inputs were scored with different questions or models, the
merge prints a warning, because those scores aren't directly comparable.

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
  `shell: git clone …`, `edit: ~/repos/x/y.ts`, or `execute: linear.save_issue`.
  Repeats are collapsed. The list is capped at 80 entries, sampled evenly from
  the middle when longer.
- `agent_final_reply`: the agent's last reply, capped at 1,800 characters.
- `work_pattern`: plain-language facts about how the session ran, computed in
  code: how many messages the user sent, how many agent steps per message, how
  long the agent actively worked (gaps over 30 minutes count as idle, not work),
  how many subagents were launched, and which other AI CLIs (`codex`, `claude`,
  `gemini`, `amp`, …) the agent ran from the shell.

Tool outputs, reasoning, and file contents are left out. A typical state is 1k to
7k tokens.

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
requests (a two-week autonomous loop, ~600 PRs); porting a compiler to another
language; computationally designing hundreds of candidate proteins and sending
them for lab testing. These are sessions where the user only sets a goal and
checks in every few days. Ordinary interactive sessions sit far below it.

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
| 5 | Ran an autonomous agent system: agents plan/implement/review/verify over many hours or days with occasional check-ins |

The other four Scores are stored as separate dimensions, each from 0 to 3. They
aren't folded into `complexity`:

- `scope`: how many distinct deliverables the user asked for
- `expertise`: how much specialized skill the work needs
- `systems`: how many external systems or codebases the work coordinates
- `open_endedness`: how much the agent had to work out for itself

`origin` is a Choice between `personal_work`, `scripted_job`, and
`test_or_benchmark`. Rows also carry a deterministic flag, `launched_by_program`.
It's set when OpenCode recorded a launcher source or per-session permission rules,
which is how sessions created through the API look.

The full Jev answers are kept in `answers_json`. You can recompute anything later
without calling Jev again.

### Why this design

Several designs were compared against hand ratings of 65 sessions on the same
0 to 4 effort scale. 31 of them were used to develop the questions and 34 were a
blind holdout, rated before seeing any Jev output. Spearman rank correlation with the hand ratings:

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

### Keeping scores comparable over time

The model is pinned to `jev-1.13.0` rather than the moving `jev-latest` alias.
Every row records `jev_model` and `scorer_hash`. The hash covers the questions and
the state limits, so if you edit a question, the next run rescores everything.
Compare trends only within one `scorer_hash` and `jev_model`.

## Querying

The `human_sessions` view keeps scored sessions that are personal work, not forks,
and not launched by a program. Use `sessions` directly for everything.

```sql
-- Bell curve: counts in 0.25-wide bins
SELECT ROUND(complexity * 4) / 4.0 AS bin, COUNT(*) AS n
FROM human_sessions GROUP BY bin ORDER BY bin;

-- Mean shift per month, per machine
SELECT month, machine, COUNT(*) AS n, ROUND(AVG(complexity), 2) AS mean_complexity
FROM human_sessions GROUP BY month, machine ORDER BY month, machine;

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

-- Token usage over time (metric 1), including subagents
SELECT month, SUM(tokens_total) AS tokens, ROUND(SUM(cost_usd), 2) AS cost_usd
FROM sessions GROUP BY month ORDER BY month;

-- Complexity per token: are you getting more done per unit of compute?
SELECT month, ROUND(AVG(complexity), 2) AS mean_complexity,
       ROUND(AVG(tokens_total) / 1e6, 2) AS mean_mtokens
FROM human_sessions GROUP BY month ORDER BY month;

-- Your most complex sessions
SELECT day, machine, ROUND(complexity, 2) AS complexity, title
FROM human_sessions ORDER BY complexity DESC LIMIT 20;
```

The `day`, `week`, and `month` columns use the local time of the machine that ran
the script. `created_ms` and `created_at` (UTC) are there for anything finer.
