"""Score the synthetic frontier sessions in frontier.py with the production questions.

The top of the complexity scale is anchored on frontier AI usage (autonomous
multi-agent campaigns). Any harness implementation, or any change to the
questions or the state format, should keep these anchors at the top:
complexity >= 5.0 and leverage >= 4.5.

Usage: TYPESAFE_API_KEY=... python3 validation/check_frontier.py [--model jev-1.13.0]
Exits 1 if an anchor falls below the thresholds.
"""

import argparse
import importlib.machinery
import importlib.util
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def main():
    sc = load("sc", HERE.parent / "session-complexity")
    fr = load("frontier", HERE / "frontier.py")
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=sc.DEFAULT_MODEL)
    ap.add_argument("--min-complexity", type=float, default=5.0)
    ap.add_argument("--min-leverage", type=float, default=4.5)
    args = ap.parse_args()
    key = os.environ.get("TYPESAFE_API_KEY") or sys.exit("error: set TYPESAFE_API_KEY")
    jev = sc.Jev(key, args.model)
    failed = False
    for name, state in fr.FRONTIER.items():
        a = jev.ask(state, sc.QUESTIONS)["answers"]
        cx, lev = a["complexity"]["score"], a["leverage"]["score"]
        ok = cx >= args.min_complexity and lev >= args.min_leverage
        failed |= not ok
        print(f"{'ok  ' if ok else 'FAIL'} complexity={cx:.2f} leverage={lev:.2f} origin={a['origin']['choice']:<17} {name}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
