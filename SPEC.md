# judge-my-ai-habits: specification

This document defines the method precisely enough to reimplement it for any agent
harness: Claude Code, Claude Desktop, Codex, Cursor, a custom agent loop, and so
on. The reference implementation is `session-complexity` (one stdlib-only Python
file). Where this spec and the code disagree, the code is the source of truth;
fix whichever one is wrong.

The goal of every implementation is the same: **scores from different harnesses
and machines must be comparable**, so their distributions can be merged into one
bell curve. Most of this spec exists to protect that property.

## 1. Terms

| Term | Meaning |
| --- | --- |
| Harness | The program that ran the agent: OpenCode, Claude Code, Claude Desktop, Codex, … |
| Session | One conversation thread between a person and an agent in a harness |
| Top-level session | A session the person started. It is the unit that gets scored |
| Child session | A session spawned by an agent: a subagent, task, or delegated worker. Rolled into its parent, never scored on its own |
| Turn | A user message plus all agent activity until the next user message |
| Agent action | One tool call (shell command, file edit, web search, MCP call, subagent launch, …) |
| Final reply | The last text the agent wrote in the session |
| State | The JSON object sent to Jev for one session |
| Personal session | Scored, classified as personal work, not a fork, not launched by a program |

## 2. Pipeline

For each machine and harness:

1. **List sessions** from the harness, read-only. Group child sessions under their parent.
2. **Skip unchanged sessions**: a session is re-scored only if it is new, its
   `updated` time changed, its last attempt errored, or the scorer hash changed.
3. **Normalize** each top-level session's messages into the common message format (section 4).
4. **Build the state** (section 5) and compute deterministic metrics.
5. **Ask Jev** all questions in one request (section 6).
6. **Upsert one row** per session into SQLite (section 7).
7. **Report** on personal sessions only: the distributions over the chosen
   period, and the change in the last 30 days against the 180 before (section 7).
   Merge databases across machines and harnesses.

The harness-specific part is steps 1 and 3: the **adapter**. Everything else is
shared and must behave identically.

## 3. Adapter contract

An adapter has a `name` (the `harness` value stored in every row, lowercase, for
example `opencode`, `claude-code`, `claude-desktop`, `codex`) and three operations:

- `version()`: the harness version string, stored per row.
- `sessions()`: every session the harness knows about on this machine, as session records.
- `messages(session_id)`: the session's messages in order, in the common message format.

Rules:

- **Read-only.** Never write to, lock, or migrate the harness's own storage. Prefer
  an official API, CLI, or export. When reading files directly, copy or open
  them read-only, and tolerate the harness writing to them at the same time.
- **Complete.** Paginate fully. Watch for silent truncation. OpenCode's
  `opencode api`, for example, truncates large responses written to a pipe,
  so the reference adapter writes to a temp file instead.
- **Unix and macOS only.** Windows is out of scope.
- **Stdlib only** if the implementation is Python. The tool must run anywhere with
  a stock `python3`.

### Session record

Field names follow the reference adapter. An adapter maps its harness's data onto them:

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable unique id. If ids could collide with another harness's, prefix them (for example `cc_…`) |
| `time.created`, `time.updated` | yes | Epoch milliseconds. `updated` must change whenever the session gains content |
| `title` | no | The harness's title for the session, if any |
| `parentID` | yes, if the harness has subagents | Parent session id for child sessions |
| `fork.sessionID` | no | Set when the session was forked or branched from another. Forks are excluded from the personal set |
| `metadata.source`, `permissions` | no | Any deterministic sign that a **program**, not a person, created the session: SDK/API launch, scheduler, CI, headless `-p` mode. It sets `launched_by_program = 1` |
| `tokens.{input,output,reasoning,cache.read,cache.write}`, `cost` | no | Usage, summed with child sessions into `tokens_total` and `cost_usd` |
| `model.{providerID,id}`, `agent`, `location.directory`, `projectID`, `outcome` | no | Descriptive columns |

### Common message format

This is what the state builder (`analyze()` in the reference code) consumes:

```json
{"type": "user", "time": {"created": 1760000000000}, "text": "…", "files": [ … ], "skills": [ … ]}
{"type": "assistant", "time": {"created": 1760000005000}, "model": {"providerID": "anthropic", "id": "claude-…"},
 "content": [
   {"type": "text", "text": "…"},
   {"type": "tool", "name": "shell", "state": {"input": {"command": "git status"}}}
 ]}
{"type": "shell", "time": {"created": …}, "command": "…"}
```

- `user` is a message the person typed. **Exclude** synthetic user-role messages
  that harnesses inject: tool results, system reminders, compaction summaries,
  hook output. Counting them as user messages inflates scores badly.
- `assistant` is one agent step. `content` holds its text and tool calls in order.
- `shell` is a command the person ran directly through the harness, if supported.
- `files` and `skills` are optional lists of attachments. Only their count and names are used.

### Tool-name vocabulary

Map each harness's tool names onto the reference vocabulary, so the same work
reads the same way to Jev whatever harness did it. Unknown tools fall through to
`name: <first string input>`, which works but carries less signal.

| Reference name | Input fields used | Claude Code equivalent (example mapping) |
| --- | --- | --- |
| `shell` | `command` | `Bash` |
| `read` | `path` or `filePath` | `Read` |
| `write`, `edit`, `patch`, `multiedit`, `apply_patch` | `path` or `filePath` | `Write`, `Edit`, `MultiEdit`, `NotebookEdit` |
| `glob`, `grep` | `pattern` | `Glob`, `Grep` |
| `subagent` | `description` or `prompt` | `Task` / `Agent` |
| `webfetch` | `url` | `WebFetch` |
| `websearch` | `query` | `WebSearch` |
| `skill` | `id` or `name` | `Skill` |
| `question` | `questions[].question` | `AskUserQuestion` |
| `execute` | `code` (tool calls are extracted from `tools.x.y(...)` references) | code-mode runtimes |
| `<server>.<tool>` | any string input | MCP tools such as `mcp__linear__save_issue` → `linear.save_issue` |

Chat-first harnesses such as Claude Desktop have fewer tools, but the same idea
applies. Represent artifacts as `write: <artifact title>`, analysis or code
execution as `execute`, web search as `websearch`, MCP calls as
`<server>.<tool>`, and uploaded files as `files` on the user message.

## 4. Subagents and child sessions

- Child sessions are never scored as their own rows.
- Their tokens and cost are added to the parent's `tokens_total` and `cost_usd`.
- Their count is the parent's `subagent_sessions` and the state's `work_pattern.subagents_launched`.
- The parent's own `subagent` tool calls appear in `agent_actions`, so Jev sees what was delegated.

If a harness records subagent work only inline, in the parent transcript, count
the subagent launches from the parent's tool calls.

## 5. State

One JSON object per top-level session, with exactly these keys:

```json
{
  "session_title": "…",
  "user_messages": [{"text": "…", "attachments": "2 attached file(s); skills: browser-control"}],
  "agent_actions": ["shell: git clone …", "edit: ~/repos/x/y.ts (×3)", "— user sent a new message —", "linear.save_issue: …"],
  "agent_final_reply": "…",
  "work_pattern": {
    "user_messages": 4,
    "agent_steps_per_user_message": 12,
    "agent_working_time": "about 1.5 hours",
    "subagents_launched": 3,
    "other_ai_agents_run_from_shell": ["codex"]
  }
}
```

Construction rules (constants are in the reference code):

- **`session_title`**: the harness title, or `(untitled)`.
- **`user_messages`**: every person-typed message in order. Each message is
  clipped to 2,500 characters, keeping the first 80% and the last 20% with an
  omission marker between. If the total exceeds 12,000 characters, the first and
  last messages are kept, then messages are taken alternately from the front and
  back of the middle until the budget runs out. The rest are replaced by
  `[N follow-up messages omitted]`. `attachments` appears only when there are files or skills.
- **`agent_actions`**: one line per tool call, in order, using the vocabulary
  formatting (`shell: <command, 140 chars>`, `edit: <path>`, …). Home-directory
  paths become `~`. A `— user sent a new message —` marker separates turns, and
  person-run shell commands appear as `user ran shell: …`. Consecutive identical
  lines collapse to `line (×N)`. If more than 80 lines remain, keep the first 40
  and last 20, insert `[… N more steps omitted …]`, and sample the middle evenly
  to fill the remaining 20.
- **`agent_final_reply`**: the last non-empty assistant text, clipped to 1,800
  characters (80% head, 20% tail), or `(no reply)`.
- **`work_pattern`**: deterministic facts, with numbers coarse or in words
  because Jev is weak at arithmetic.
  - `user_messages`: count of person-typed messages.
  - `agent_steps_per_user_message`: tool calls ÷ user messages, rounded.
  - `agent_working_time`: active time in words: `under 2 minutes`,
    `about N minutes`, `about N.N hours`, `about N.N days`. Active time is the
    sum, over each turn, of the gaps between consecutive messages from the user
    message to the last activity before the next one. **Each gap is capped at 30
    minutes**, so a session left open for days does not count as work. (A
    bug summing each message's own duration once produced 6,634 "hours".)
  - `subagents_launched`: number of child sessions, or of subagent launches, whichever is larger.
  - `other_ai_agents_run_from_shell`: distinct names matched in shell commands by
    `(?:^|[\s;&|/(])(codex|claude|gemini|cursor-agent|aider|amp|opencode run|aside|goose|droid)\b`,
    or the string `none`.

Leave out tool outputs, reasoning, file contents, and system prompts. A typical
state is 1k to 7k tokens.

A session with zero user messages or zero assistant messages gets
`status = 'empty'` and is not sent to Jev.

## 6. Jev

[TypeSafe](https://www.typesafe.ai) Jev is a small model that answers structured
questions over a JSON state.

- `POST https://api.typesafe.ai/v1/systemone`
- Headers: `Authorization: Bearer $TYPESAFE_API_KEY`, `Content-Type: application/json`
- Body: `{"model": "jev-1.13.0", "state": {…}, "questions": {"<name>": {…}, …}}`.
  `questions` is an **object keyed by name**, not a list. An array is rejected with HTTP 422.
- Response: `answers.<name>` with `score`, `probabilities` (per level, keys `"0"`, `"1"`, …),
  and `confidence` for Score questions, `choice` and `probabilities` for Choice
  questions. Also `model` (the resolved version) and `usage.input_tokens`.
- Limits: Score criteria have at most 10 levels; 32k tokens per question; 64k per request.
- Retry 408/429/5xx and connection errors with exponential backoff (1 s doubling to 30 s,
  7 attempts), honouring `retry-after`.
- Cost at the time of writing is about $0.04 per million input tokens: roughly
  $0.14 to score 1,260 sessions.

### Questions

All questions go in **one request**, so they are answered over the same state.
Copy their definitions **verbatim** from `QUESTIONS` in the reference code; a
paraphrase is a different instrument. In summary:

| Name | Type | Scale |
| --- | --- | --- |
| `complexity` | Score | 0–6. Headline. "How much work would it take skilled professionals, working without AI, to do everything the user asked for in this session?" 0 a couple of minutes · 1 under an hour · 2 a few hours · 3 about a day · 4 several days · 5 weeks for one person · 6 months for a team of specialists. Each level carries examples; level 6 is anchored on frontier autonomous multi-agent work |
| `leverage` | Score | 0–5. "How did the user put AI to work in this session?" answered from knowledge · one or two lookups · steered step by step · delegated a goal · orchestrated several agents · ran an autonomous agent system |
| `scope`, `expertise`, `systems`, `open_endedness` | Score | 0–3 side dimensions, stored separately and never folded into `complexity` |
| `origin` | Choice | `personal_work` / `scripted_job` / `test_or_benchmark`, judged from the first message and title |

### Pinning and the scorer hash

- Pin an exact model version (`jev-1.13.0`), never a moving alias such as `jev-latest`.
- `scorer_hash` = first 12 hex characters of SHA-256 over the JSON (sorted keys) of
  `[SCORER_VERSION, QUESTIONS, TRACE_CAP, USER_MSG_CHARS, USER_TOTAL_CHARS, FINAL_REPLY_CHARS]`.
  Any change to the questions or limits changes the hash and triggers a full rescore.
- An implementation for a new harness that uses the same questions and limits
  **must produce the same hash**. If it doesn't, its scores are not comparable,
  and `merge` will warn about it.

## 7. Storage

SQLite, one database per machine. The schema is `SCHEMA` in the reference code.
Key facts:

- Primary key `(machine, session_id)`. `machine` is the short hostname, overridable.
- `harness` records the adapter name. Incremental checks filter on `machine` and `harness`.
- `status` is `scored`, `empty`, or `error` (with `error` text; errors are retried next run).
- Scores: `complexity`, `complexity_p0` … `complexity_p6`, `complexity_confidence`,
  `leverage`, `scope`, `expertise`, `systems`, `open_endedness`, `origin` and its
  probabilities, plus the full answers in `answers_json`.
- Metrics: message counts, tool calls, distinct tools, subagent calls and sessions,
  files edited, `active_seconds`, `wall_seconds`, token and cost columns.
- Time: `created_ms`, `created_at` (UTC ISO), and `day`/`week`/`month` in machine-local time.
- Provenance: `jev_model`, `scorer_hash`, `state_tokens`, `scored_at`, and the
  harness version (column `opencode_version`, named for the first harness).
- View `human_sessions`: `status = 'scored' AND origin = 'personal_work' AND fork_of IS NULL AND launched_by_program = 0`.
  Every report and chart uses this view by default.
- `runs`: one row per scoring run.
- New columns are added with `ALTER TABLE … ADD COLUMN` on open. `merge` copies
  only the columns an input has, so older databases still merge.

### Report

Reports cover `human_sessions` (or every scored session with `--all`) over all
history by default, optionally limited with `--since`/`--until`. They always
include the **change** between two trailing windows ending at `--until` or now:

- **Recent**: the last `recent_days` (default 30) days.
- **Baseline**: the `baseline_days` (default 180) days **immediately before**
  the recent window. They don't overlap.
- Both windows are clipped to the first session in range. With less history than
  requested, the baseline is all the history before the recent window. With less
  than one recent window of history, the recent window is all of it and there is
  no baseline, which the report says instead of showing a change.
- Compared per window: session count and sessions per 30 days; complexity mean
  (as a difference, a percentage, and in baseline standard deviations) and
  median; leverage mean; `tokens_total` per 30 days; and mean and median tokens
  per session. Rates use each window's actual covered length, so windows of
  different lengths compare fairly.

## 8. Validating a new harness

An adapter is done when all of these hold:

1. **States look right.** Run `--dry-run` on 10 or more varied sessions: tiny
   ones, long ones, ones with subagents. Check that `user_messages` holds only
   what the person typed, that actions read naturally in the shared vocabulary,
   and that `work_pattern` numbers are plausible.
2. **Hand labels agree.** Label at least 30 sessions on the complexity scale
   **before** looking at their scores (development set), then 20 or more as a blind
   holdout. Use `validation/agreement.py`. Target Spearman ≥ 0.90 on both. The
   reference reached 0.96 and 0.95. Also label leverage on a subset and check it.
3. **The top of the scale still holds.** `validation/check_frontier.py` must pass:
   every synthetic frontier anchor scores complexity ≥ 5.0 and leverage ≥ 4.5.
4. **Scores are stable.** Rescoring the same 20 sessions twice moves no session by more than about 0.05.
5. **Filters work.** Spot-check that test runs and scripted or launched sessions
   are excluded from `human_sessions`, and that forks are flagged.
6. **Merge works.** Merge the new database with an existing one from another
   harness and check `report`. Merge should not warn about scorer hashes.

When iterating:

- **Change the adapter and state construction first**: what counts as a user
  message, how tools are named, what counts as a subagent. Leave the questions
  alone. The questions are shared across harnesses; changing them for one harness
  breaks comparability for all of them.
- If evidence shows a question itself must change, bump `SCORER_VERSION`,
  re-validate on **every** supported harness, and record the before and after numbers in the README.
- Keep numbers out of the state where words will do.
- Record each variant tried and its Spearman in the README's validation section,
  so the next person doesn't repeat it.

## 9. Known pitfalls

- Harnesses reuse titles across sibling sessions. Never treat the title as ground truth.
- Many sessions are generated by eval harnesses and launchers. Jev's `origin`
  missed 9 of 13 launcher sessions in testing, which is why `launched_by_program`
  exists. Find the deterministic signal in each new harness.
- Synthetic user-role messages (tool results, reminders, compaction summaries)
  must not be counted as user messages.
- Gaps between messages are not work. Cap them.
- Jev counts poorly: give it `about 3 hours`, not `10847 seconds`.
