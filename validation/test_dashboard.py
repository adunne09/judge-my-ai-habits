"""Check the dashboard's TL;DR wording by running its number helpers in Node."""
import json
import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "needs node")
class TokenSentenceTests(unittest.TestCase):
    def js(self, expr):
        html = (ROOT / "dashboard.html").read_text(encoding="utf-8")
        helpers = html[html.index("// ---------- numbers & words ----------"):html.index("// ---------- scoping ----------")]
        script = helpers + f"\nprocess.stdout.write(JSON.stringify({expr}));"
        return json.loads(subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout)

    def sentence(self, recent, before, total):
        return self.js(f"tokenSentence(rel({json.dumps(recent)}, {json.dumps(before)}), {json.dumps(total)})")

    def test_up(self):
        self.assertEqual(self.sentence(2.6e9, 1e9, 1664516795),
                         " Token use ran at <b>2.6× its earlier rate</b>, <b>1.66B tokens</b> in total.")
        self.assertEqual(self.sentence(12e9, 1e9, 3e9),
                         " Token use ran at <b>12× its earlier rate</b>, <b>3B tokens</b> in total.")
        self.assertEqual(self.sentence(1.57e6, 1e6, 12_400_000),
                         " Token use ran <b>57% above its earlier rate</b>, <b>12.4M tokens</b> in total.")

    def test_down(self):
        self.assertEqual(self.sentence(8e5, 1e6, 950),
                         " Token use ran <b>20% below its earlier rate</b>, <b>950 tokens</b> in total.")
        for ratio, words in ((0.5, "about half"), (0.35, "about a third"), (0.2, "about a quarter"), (0.1, "a fraction")):
            self.assertEqual(self.sentence(ratio * 1e6, 1e6, 412_000),
                             f" Token use ran at <b>{words} of its earlier rate</b>, <b>412K tokens</b> in total.")

    def test_steady(self):
        self.assertEqual(self.sentence(1.05e6, 1e6, 3_000_000),
                         " Token use held <b>about steady</b>, <b>3M tokens</b> in total.")
        self.assertEqual(self.sentence(1, 1, 1), " Token use held <b>about steady</b>, <b>1 token</b> in total.")

    def test_no_comparison_or_no_tokens(self):
        self.assertEqual(self.sentence(5e5, None, 500_000),
                         " You used <b>500K tokens</b>; there's no earlier token count to compare.")
        self.assertEqual(self.sentence(0, 1e6, 0), " No tokens were recorded.")
        self.assertEqual(self.sentence(None, 1e6, None), "")

    def test_total_is_bold(self):
        self.assertEqual(self.js("tokTotal(1664516795)"), "<b>1.66B tokens</b>")


if __name__ == "__main__":
    unittest.main()
