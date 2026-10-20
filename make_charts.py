"""Regenerate the SVG charts in charts/ from a sessions database (stdlib only).

Usage: python3 make_charts.py [--db PATH]  (default: the local results DB)
Writes charts/complexity.svg, charts/leverage.svg, charts/trend.svg.
"""

import argparse
import pathlib
import sqlite3
import sys

W, H = 800, 380
PAD_L, PAD_R, PAD_T, PAD_B = 56, 16, 34, 52
INK, MUTED, BAR, ACCENT, GREEN = "#24292f", "#6e7781", "#4b7bcc", "#d97706", "#3a8f6d"
FONT = "font-family='-apple-system,Segoe UI,Helvetica,Arial,sans-serif'"


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def svg_open():
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
            f'<rect width="{W}" height="{H}" fill="#ffffff"/>']


def text(x, y, s, size=12, fill=INK, anchor="middle", weight=None):
    w = f' font-weight="{weight}"' if weight else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" {FONT} font-size="{size}" fill="{fill}" text-anchor="{anchor}"{w}>{esc(s)}</text>'


def frame(title, subtitle):
    out = svg_open()
    out.append(text(12, 20, title, size=14, weight="600", anchor="start"))
    out.append(text(12, 38, subtitle, size=11, fill=MUTED, anchor="start"))
    return out


def bars(out, counts, edges, x0, x1, y0, y1, color=BAR, tick_fmt="{:g}"):
    """counts: bar heights; edges: bin edges, len(counts)+1 of them."""
    top = max(counts) or 1
    bw = (x1 - x0) / len(counts)
    for i, c in enumerate(counts):
        if not c:
            continue
        h = (y1 - y0) * c / top
        out.append(f'<rect x="{x0 + i * bw + 1:.1f}" y="{y1 - h:.1f}" width="{bw - 2:.1f}" height="{h:.1f}" fill="{color}"/>')
        out.append(text(x0 + (i + 0.5) * bw, y1 - h - 4, c, size=10, fill=MUTED))
    out.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{INK}" stroke-width="1"/>')
    step = max(1, round(len(edges) / 8))
    for i in range(0, len(edges), step):
        x = x0 + i * bw
        out.append(f'<line x1="{x:.1f}" y1="{y1}" x2="{x:.1f}" y2="{y1 + 4}" stroke="{INK}"/>')
        out.append(text(x, y1 + 18, tick_fmt.format(edges[i]), size=11, fill=INK))
    if (len(edges) - 1) % step:  # right edge label
        out.append(text(x1, y1 + 18, tick_fmt.format(edges[-1]), size=11, fill=INK))


def complexity_chart(rows):
    values = [r[0] for r in rows]
    counts = [0] * 24
    for v in values:
        counts[min(23, int(v * 4))] += 1
    n = len(values)
    mean = sum(values) / n
    out = frame("Complexity of personal sessions", f"n={n} · mean={mean:.2f} · median={sorted(values)[n // 2]:.2f}")
    x0, x1, y0, y1 = PAD_L, W - PAD_R, PAD_T + 20, H - PAD_B + 4
    bars(out, counts, [i / 4 for i in range(25)], x0, x1, y0, y1)
    out.append(text(30, (y0 + y1) / 2, "sessions", size=11, fill=MUTED))
    for lv, name in enumerate(["minutes", "under an hour", "hours", "a day", "days", "weeks", "team-months"]):
        x = min(x0 + lv * (x1 - x0) / 6, W - 64)
        out.append(text(x, H - 10, name, size=10, fill=MUTED))
        out.append(f'<line x1="{x0 + lv * (x1 - x0) / 6:.1f}" y1="{y1}" x2="{x0 + lv * (x1 - x0) / 6:.1f}" y2="{y1 + 4}" stroke="{INK}"/>')
    return out, "</svg>"


def leverage_chart(rows):
    values = [r[0] for r in rows]
    counts = [0] * 10
    for v in values:
        counts[min(9, int(v * 2))] += 1
    out = frame("Leverage: how the work was delegated", f"n={len(values)} · mean={sum(values) / len(values):.2f}")
    x0, x1, y0, y1 = PAD_L, W - PAD_R, PAD_T + 20, H - PAD_B + 4
    bars(out, counts, [i / 2 for i in range(11)], x0, x1, y0, y1, color=GREEN)
    out.append(text(30, (y0 + y1) / 2, "sessions", size=11, fill=MUTED))
    for lv, name in enumerate(["knowledge", "lookups", "steered", "delegated", "multi-agent", "autonomous"]):
        x = min(x0 + lv * (x1 - x0) / 5, W - 64)
        out.append(text(x, H - 10, name, size=10, fill=MUTED))
        out.append(f'<line x1="{x0 + lv * (x1 - x0) / 5:.1f}" y1="{y1}" x2="{x0 + lv * (x1 - x0) / 5:.1f}" y2="{y1 + 4}" stroke="{INK}"/>')
    return out, "</svg>"


def trend_chart(rows):
    """rows: ordered (period, complexity); line of weekly means."""
    groups = {}
    for p, v in rows:
        groups.setdefault(p, []).append(v)
    periods = sorted(groups)
    stats = [(p, sum(xs) / len(xs), len(xs)) for p, xs in ((p, groups[p]) for p in periods)]
    means = [m for _, m, _ in stats]
    all_n = sum(n for _, _, n in stats)
    all_mean = sum(m * n for _, m, n in stats) / all_n
    out = frame("Mean complexity by week", f"n={all_n} · weighted mean={all_mean:.2f}")
    x0, x1, y0, y1 = PAD_L + 34, W - PAD_R - 34, PAD_T + 30, H - PAD_B + 10
    lo, hi = min(means), max(means)
    pad = 0.15 * ((hi - lo) or 0.2)
    lo, hi = lo - pad, hi + pad
    px = lambda i: x0 + i * (x1 - x0) / max(1, len(means) - 1)
    py = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)
    for v in (lo, (lo + hi) / 2, hi):
        out.append(f'<line x1="{x0}" y1="{py(v):.1f}" x2="{x1}" y2="{py(v):.1f}" stroke="#e1e4e8"/>')
        out.append(text(x0 - 24, py(v) + 4, f"{v:.2f}", size=10, fill=MUTED))
    pts = " ".join(f"{px(i):.1f},{py(m):.1f}" for i, (_, m, _) in enumerate(stats))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{ACCENT}" stroke-width="2.5"/>')
    step = max(1, len(stats) // 6)
    for i, (p, m, n_) in enumerate(stats):
        out.append(f'<circle cx="{px(i):.1f}" cy="{py(m):.1f}" r="3.5" fill="{ACCENT}"/>')
        out.append(text(px(i), y0 - 10, n_, size=9, fill=MUTED))
        if i % step == 0:
            out.append(text(px(i), y1 + 18, p, size=10, fill=MUTED))
    out.append(text(x0 - 44, PAD_T + 16, "n sessions above", size=9, fill=MUTED))
    return out, "</svg>"


def default_db():
    data = pathlib.Path.home() / ".local" / "share"
    new, legacy = data / "judge-my-ai-habits" / "sessions.sqlite", data / "opencode-session-complexity" / "sessions.sqlite"
    return str(legacy if legacy.exists() and not new.exists() else new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=default_db())
    args = ap.parse_args()
    db = sqlite3.connect(pathlib.Path(args.db).expanduser())
    outdir = pathlib.Path(__file__).parent / "charts"
    outdir.mkdir(exist_ok=True)
    cx = db.execute("SELECT complexity FROM human_sessions WHERE complexity IS NOT NULL ORDER BY created_ms").fetchall()
    lev = db.execute("SELECT leverage FROM human_sessions WHERE leverage IS NOT NULL ORDER BY created_ms").fetchall()
    tr = db.execute("SELECT week, complexity FROM human_sessions WHERE complexity IS NOT NULL ORDER BY created_ms").fetchall()
    for name, rows, fn in (("complexity", cx, complexity_chart), ("leverage", lev, leverage_chart), ("trend", tr, trend_chart)):
        if not rows:
            print(f"no data for {name}, skipped", file=sys.stderr)
            continue
        body, tail = fn(rows)
        (outdir / f"{name}.svg").write_text("\n".join(body + [tail]) + "\n")
        print(f"wrote charts/{name}.svg")


if __name__ == "__main__":
    main()