"""Synthetic sessions modelled on frontier AI usage posted on X (Oct 2026). Used only to check the top of the scale."""


def rep(items, n):
    return [items[i % len(items)].format(i=i // len(items) + 1) for i in range(n)]


def S(title, users, actions, reply, pattern):
    return {"session_title": title, "user_messages": [{"text": u} for u in users], "agent_actions": actions, "agent_final_reply": reply, "work_pattern": pattern}


FRONTIER = {}
FRONTIER["steipete: 2-week planner + codex worktrees + reviewer loop, ~600 PRs"] = S(
    "Migrate OpenClaw web frontend from Lit to Solid 2.0",
    ["Kick off a loop to move OpenClaw's Lit-based web frontend to Solid 2.0. You plan; run codex cli in separate git worktrees to implement each slice and open a PR per slice. A second agent reviews every PR and keeps you on track. Keep going until we can delete Lit entirely, then move everything to idiomatic Solid patterns.",
     "checking in. status? anything blocked?", "looks good, keep going. watch for button shape regressions", "Lit is gone, nice. now do the idiomatic Solid pass"],
    ["subagent: inventory every Lit component and its dependents", "[… 4100 more steps omitted …]"] + rep([
        "shell: git worktree add ../wt-{i} -b solid/slice-{i}",
        "shell: codex exec --cd ../wt-{i} 'Port the components in slice {i} from Lit to Solid 2.0; keep behavior identical; run the tests'",
        "shell: pnpm -C ../wt-{i} test && pnpm -C ../wt-{i} build",
        "subagent: review the PR for slice {i} against the migration plan",
        "shell: gh pr merge --squash solid/slice-{i}"], 70),
    "Lit has been removed. 612 PRs merged over 13 days; JS bundle down 31%, CSS down 22%. The idiomatic Solid pass is complete; review caught 4 small UI regressions, all fixed.",
    {"user_messages": 4, "agent_steps_per_user_message": 1100, "agent_working_time": "about 13 days", "subagents_launched": 640, "other_ai_agents_run_from_shell": ["codex"]})
FRONTIER["Citrini: 300 agents, 64h, 211 antivenom proteins sent for lab testing"] = S(
    "Design protein binders for a scorpion antivenom",
    ["Design candidate protein binders that neutralize the major toxins in Androctonus scorpion venom. Launch agents to survey the toxin structures and literature, run the design and filter pipelines for each target, and collect the top candidates. When the designs are ready, prepare and send the order to the synthesis lab and write up the results.",
     "how's the design campaign going?", "send the top 211 to the lab and summarize what the agents found"],
    ["subagent: survey published structures for toxin MaT1"] + rep([
        "subagent: run the binder design pipeline for toxin {i}",
        "subagent: filter designs {i} by stability and docking score",
        "shell: python scripts/collect.py --toxin {i} >> candidates.csv",
        "shell: pMSA: fold-check candidates {i} against the known antigen structures"], 60) +
    ["subagent: rank all candidate designs and select the top 211",
     "shell: curl -X POST https://lab-api.example.com/orders --data @order.json",
     "subagent: write the campaign summary and per-toxin results"],
    "Design campaign complete: 300+ agents ran over 64 hours, 211 candidate binders designed across the 5 major toxins and ordered for lab testing; per-toxin hit reports and the order confirmation are in the report directory.",
    {"user_messages": 3, "agent_steps_per_user_message": 400, "agent_working_time": "about 2.7 days", "subagents_launched": 310, "other_ai_agents_run_from_shell": "none"})
FRONTIER["Shumer: manager loop, multi-week multi-agent build"] = S(
    "Build the Veritas compliance platform",
    ["Here is the spec for the Veritas compliance platform (attached). Use the manager loop: you are the manager — maintain the plan and task queue, spawn an implementer agent for each task, review its work, update the plan, repeat. Don't stop until every milestone in the spec is done and the full test suite passes. Check in only when a milestone lands.",
     "milestone 1 looks good, keep running the loop",
     "keep going", "where are we against the spec?"],
    ["manager: split the spec into 40 milestone tasks"] + rep([
        "subagent: implement task {i} (module, tests, docs)",
        "subagent: review task {i}'s diff against the spec",
        "shell: pnpm test --filter module-{i}",
        "manager: update the plan and task queue"], 200),
    "All 40 milestones implemented and verified. 214 implementer runs, full test suite green, the platform matches the spec; remaining polish items are logged in the plan for the next loop.",
    {"user_messages": 4, "agent_steps_per_user_message": 500, "agent_working_time": "about 3 weeks", "subagents_launched": 420, "other_ai_agents_run_from_shell": "none"})
FRONTIER["tsrs: port the TypeScript compiler to Rust"] = S(
    "Port the TypeScript compiler to Rust",
    ["Port the TypeScript compiler (tsc) to Rust, keeping behavior identical. Work through the checker, binder, and emitter module by module; run the upstream conformance test suite after each module and fix divergences. Keep a running conformance report until we pass 100% of the tests.",
     "conformance is at what percent now? keep going",
     "the emitter pass looks good, continue with the checker",
     "keep going until conformance is green"],
    ["shell: clone microsoft/TypeScript and set up the Rust workspace"] + rep([
        "shell: cargo build && cargo test --module {i}",
        "subagent: port module {i} (parser: expressions)",
        "shell: python scripts/conformance.py --module {i} > reports/{i}.txt",
        "subagent: fix the conformance divergences in module {i}"], 300),
    "Port complete: full tsc ported to Rust, conformance suite 100% green across all 1,800 tests. Binary is 4x faster on our benchmarks; the port took 6 weeks of continuous agent work.",
    {"user_messages": 4, "agent_steps_per_user_message": 900, "agent_working_time": "about 6 weeks", "subagents_launched": 350, "other_ai_agents_run_from_shell": "none"})
FRONTIER["Lauren Tan: 30-agent loop shipping ~1000 PRs/month"] = S(
    "Run the maintenance fleet: 30 agents shipping PRs around the clock",
    ["Set up the maintenance fleet: 30 coding agents, each assigned a slice of the backlog (dependency upgrades, flaky test fixes, small features). Each agent works in its own worktree, opens a PR, and a reviewer agent gates merges. Keep the fleet running overnight and requeue anything that fails CI.",
     "overnight report?", "requeue the failures and keep the fleet running"],
    ["shell: fleet up --agents 30 --worktrees"] + rep([
        "shell: fleet status --agent {i}",
        "subagent: review PR from agent {i}",
        "shell: gh pr merge --auto", "shell: fleet requeue --failed"], 80),
    "Fleet ran 11 days: 380 PRs opened, 355 merged after review, 25 requeued and completed on retry. Backlog slice is clear; flaky-test count is down 60%.",
    {"user_messages": 2, "agent_steps_per_user_message": 450, "agent_working_time": "about 11 days", "subagents_launched": 400, "other_ai_agents_run_from_shell": ["codex", "claude"]})