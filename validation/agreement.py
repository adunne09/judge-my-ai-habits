"""Compare hand labels with the scores in a results database.

Label a sample of sessions yourself *before* looking at their scores, on the
complexity scale (0 minutes … 6 team-months; halves are fine) or the leverage
scale (0 … 5). Then:

    python3 validation/agreement.py --labels labels.json [--field leverage] [--db PATH]

labels.json maps session_id -> label, e.g. {"ses_abc": 2, "ses_def": 3.5}.
Prints Spearman rank correlation, mean absolute error, and the biggest
disagreements, which are the sessions worth reading to improve the state.
"""

import argparse
import json
import math
import pathlib
import sqlite3
import sys


def ranks(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r, i = [0.0] * len(xs), 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2
        i = j + 1
    return r


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va, vb = sum((x - ma) ** 2 for x in ra), sum((y - mb) ** 2 for y in rb)
    return cov / math.sqrt(va * vb) if va and vb else float("nan")


def main():
    home = pathlib.Path.home() / ".local" / "share"
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--field", choices=["complexity", "leverage"], default="complexity")
    ap.add_argument("--db", default=str(home / "judge-my-ai-habits" / "analytics.sqlite"))
    args = ap.parse_args()
    labels = json.load(open(args.labels))
    db = sqlite3.connect(pathlib.Path(args.db).expanduser())
    rows = []
    for sid, gold in labels.items():
        r = db.execute(f"SELECT {args.field}, title FROM sessions WHERE session_id = ? AND status = 'scored'", (sid,)).fetchone()
        if r is None:
            print(f"warning: {sid} not scored in {args.db}", file=sys.stderr)
            continue
        rows.append((sid, float(gold), r[0], r[1] or ""))
    if len(rows) < 3:
        sys.exit("error: need at least 3 labeled, scored sessions")
    gold, pred = [r[1] for r in rows], [r[2] for r in rows]
    print(f"n={len(rows)}  spearman={spearman(gold, pred):.3f}  mae={sum(abs(g - p) for g, p in zip(gold, pred)) / len(rows):.2f}")
    print("\nbiggest disagreements (label vs score):")
    for sid, g, p, title in sorted(rows, key=lambda r: -abs(r[1] - r[2]))[:8]:
        print(f"  {g:4.1f} vs {p:4.2f}  {sid}  {title[:60]}")


if __name__ == "__main__":
    main()
