"""Exercise real release archives and the temporary runner without network or keys."""
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="judge distribution ")
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        self.assets = self.root / "artifacts"
        self.home = self.root / "home with spaces"
        self.home.mkdir()
        self.scratch = self.root / "temporary downloads"
        self.scratch.mkdir()
        self.env = dict(os.environ, HOME=str(self.home),
                        XDG_DATA_HOME=str(self.home / "share"),
                        TMPDIR=str(self.scratch),
                        JMAIH_DOWNLOAD_BASE_URL=self.assets.as_uri(),
                        JMAIH_VERSION="latest")
        self.env.pop("TYPESAFE_API_KEY", None)
        self.build()

    def build(self, version="v0.2.0"):
        subprocess.run(["bash", str(ROOT / "scripts/build.sh"), version, str(self.assets)],
                       check=True, capture_output=True, text=True)

    def run_tool(self, *args, code=0):
        # stdin matches curl | bash; the runner must not read a key from stdin.
        result = subprocess.run(["bash", "-s", "--", *args], input=(self.assets / "run.sh").read_text(),
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(list(self.scratch.iterdir()), [], "Runner left downloaded code behind")
        self.assertFalse((self.home / ".local/bin").exists())
        self.assertFalse((self.home / "share/judge-my-ai-habits/app").exists())
        return result

    def update_archive_checksum(self):
        archive = self.assets / "judge-my-ai-habits.tar.gz"
        (self.assets / "SHA256SUMS").write_text(
            hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")

    def test_reproducible_allowlisted_package(self):
        first = {p.name: p.read_bytes() for p in self.assets.iterdir()}
        self.build()
        self.assertEqual(first, {p.name: p.read_bytes() for p in self.assets.iterdir()})
        with tarfile.open(self.assets / "judge-my-ai-habits.tar.gz") as tar:
            self.assertEqual(set(tar.getnames()), {
                "judge-my-ai-habits/judge-my-ai-habits",
                "judge-my-ai-habits/dashboard.html", "judge-my-ai-habits/VERSION"})

    def test_piped_run_renders_bundled_dashboard_and_preserves_results(self):
        result = self.run_tool("--help")
        self.assertIn("score", result.stdout)
        db = self.home / "analytics.sqlite"
        subprocess.run([sys.executable, "-c",
                        "import runpy,pathlib,sys; s=runpy.run_path(sys.argv[1]); "
                        "s['connect'](pathlib.Path(sys.argv[2])).close()",
                        str(ROOT / "judge-my-ai-habits"), str(db)], env=self.env, check=True, capture_output=True)
        original = db.read_bytes()
        self.run_tool("dashboard", "--db", str(db))
        html = (db.parent / "dashboard.html").read_text()
        self.assertIn("<html", html)
        self.assertNotIn("__JMAIH_DATA__", html)
        self.run_tool("report", "--db", str(db))
        self.assertEqual(db.read_bytes(), original)
        self.assertTrue((db.parent / "dashboard.html").exists())

    def test_failed_checksum_cleans_up_without_running(self):
        archive = self.assets / "judge-my-ai-habits.tar.gz"
        archive.write_bytes(archive.read_bytes() + b"corrupt")
        result = self.run_tool("--help", code=1)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_application_error_exit_code_is_preserved(self):
        result = self.run_tool("--not-a-real-option", code=2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_pinned_version_must_match(self):
        self.env["JMAIH_VERSION"] = "v0.3.0"
        result = self.run_tool("--help", code=1)
        self.assertIn("archive contains v0.2.0", result.stderr)
        self.env["JMAIH_VERSION"] = "v0.2.0"
        self.run_tool("--help")

    def test_unexpected_archive_member_is_not_extracted(self):
        archive = self.assets / "judge-my-ai-habits.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            member = tarfile.TarInfo("../../unexpected")
            member.size = 4
            tar.addfile(member, io.BytesIO(b"oops"))
        self.update_archive_checksum()
        self.run_tool("--help", code=1)
        self.assertFalse((self.root / "unexpected").exists())

    def test_default_run_executes_and_inherits_environment(self):
        # A tiny packaged program proves no-argument execution without scoring
        # real sessions or calling the API. Its result must outlive the runner.
        program = b'''import json, os, pathlib, sys
pathlib.Path(os.environ["HOME"], "result.json").write_text(json.dumps({
    "args": sys.argv[1:], "context": os.environ["JMAIH_TEST_CONTEXT"]}))
'''
        with tarfile.open(self.assets / "judge-my-ai-habits.tar.gz", "w:gz") as tar:
            for name, data in (("judge-my-ai-habits", program),
                               ("dashboard.html", b"template"), ("VERSION", b"v0.2.0\n")):
                member = tarfile.TarInfo("judge-my-ai-habits/" + name)
                member.size = len(data)
                tar.addfile(member, io.BytesIO(data))
        self.update_archive_checksum()
        self.env["JMAIH_TEST_CONTEXT"] = "inherited"
        self.run_tool()
        result = json.loads((self.home / "result.json").read_text())
        self.assertEqual(result, {"args": [], "context": "inherited"})

    def test_build_refuses_stale_installer_in_output(self):
        (self.assets / "install.sh").write_text("old installer")
        result = subprocess.run(["bash", str(ROOT / "scripts/build.sh"), "v0.2.0", str(self.assets)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("choose a new output directory", result.stderr)


if __name__ == "__main__":
    unittest.main()
