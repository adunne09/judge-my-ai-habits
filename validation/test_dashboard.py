"""Check the dashboard's TL;DR wording by running its number helpers in Node."""
import json
import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "needs node")
class TokenTotalWordsTests(unittest.TestCase):
    def words(self, recent, before, total, period="30 days"):
        html = (ROOT / "dashboard.html").read_text(encoding="utf-8")
        helpers = html[html.index("// ---------- numbers & words ----------"):html.index("// ---------- scoping ----------")]
        script = helpers + f"\nprocess.stdout.write(totalWords(rel({recent}, {before}), {total}, {json.dumps(period)}));"
        return subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout

    def test_up(self):
        self.assertEqual(self.words(2.6e9, 1e9, 1664516795), ", up to 1.66B tokens in the last 30 days")
        self.assertEqual(self.words(1.3e6, 1e6, 12_400_000), ", up to 12.4M tokens in the last 30 days")

    def test_down(self):
        self.assertEqual(self.words(4e5, 1e6, 412_000, "14 days"), ", down to 412K tokens in the last 14 days")
        self.assertEqual(self.words(8e5, 1e6, 950), ", down to 950 tokens in the last 30 days")

    def test_flat(self):
        self.assertEqual(self.words(1.05e6, 1e6, 3_000_000), ", steady at 3M tokens in the last 30 days")


if __name__ == "__main__":
    unittest.main()
