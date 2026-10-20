# opencode-session-complexity

Scores every OpenCode v2 session on a machine for how complex the work was, using
TypeSafe's Jev model, and writes the results to SQLite so you can plot the
distribution and watch it move over time. Databases from several machines merge
into one.

It's a single Python file with no dependencies. It needs Python 3.9+, OpenCode v2
on `PATH` (or in `~/.opencode/bin`), and a TypeSafe API key. It reads sessions
through `opencode api`, so it works with whatever server and storage the global
installation uses. It never opens OpenCode's database directly.

## Run it

```sh
export TYPESAFE_API_KEY=...            # https://console.typesafe.ai
./session-complexity                   # score new or changed sessions on this machine
./session-complexity report            # histogram plus a monthly trend
./session-complexity report --by week
```

Results go to `~/.local/share/opencode-session-complexity/sessions.sqlite`. Change
that with `--db`. Each row is keyed by `(machine, session_id)`. `machine` is the
short hostname; override it with `--machine`.

Runs are incremental. A session is only sent to Jev again if it changed since its
last score, if its last attempt failed, or if the questions changed. A full first
run on about 1,260 sessions took about a minute and used 2.8M Jev input
tokens, about $0.12.

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

Tool outputs, reasoning, and file contents are left out. A typical state is 1k to
7k tokens.

Sessions with no user message or no assistant reply get `status = 'empty'` and
aren't sent to Jev.

### Questions

All six questions go in the same request, so they're answered in parallel over the
same state.

**`complexity` (0 to 5)** is the headline number. It's a Score question: "How much
work would it take a skilled professional, working without AI, to do everything the
user asked for in this session?" The levels are:

| Level | Meaning |
| --- | --- |
| 0 | A couple of minutes |
| 1 | Under an hour: one small, well-defined task |
| 2 | A few hours: a multi-step task |
| 3 | About a full day: a substantial piece of work |
| 4 | Several days: a multi-part project |
| 5 | Weeks: a large project |

Each level also carries generic examples. The score is the probability-weighted
level, so it's continuous, for example 2.37. The probability for each level is
stored too, in `complexity_p0` through `complexity_p5`.

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
  move. Rank agreement was unchanged (0.96 on both sets).

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
       ROUND(AVG(complexity_p4), 3) AS days,    ROUND(AVG(complexity_p5), 3) AS weeks
FROM human_sessions GROUP BY week ORDER BY week;

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
