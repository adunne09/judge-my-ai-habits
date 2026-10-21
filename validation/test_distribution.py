"""Exercise real release archives and the piped installer without network or keys."""
import hashlib
import io
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
        self.env = dict(os.environ, HOME=str(self.home),
                        XDG_DATA_HOME=str(self.home / "share"),
                        JMAIH_INSTALL_DIR=str(self.home / "app"),
                        JMAIH_BIN_DIR=str(self.home / "bin"),
                        JMAIH_DOWNLOAD_BASE_URL=self.assets.as_uri(),
                        JMAIH_VERSION="latest")
        self.env.pop("TYPESAFE_API_KEY", None)
        self.command = self.home / "bin" / "judge-my-ai-habits"
        self.build()

    def build(self, version="v0.1.0"):
        subprocess.run(["bash", str(ROOT / "scripts/build.sh"), version, str(self.assets)],
                       check=True, capture_output=True, text=True)

    def install(self, succeeds=True):
        # stdin matches curl | bash; the installer must not read a key from stdin.
        result = subprocess.run(["bash"], input=(self.assets / "install.sh").read_text(),
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, succeeds, result.stdout + result.stderr)
        return result

    def test_reproducible_allowlisted_package(self):
        first = {p.name: p.read_bytes() for p in self.assets.iterdir()}
        self.build()
        self.assertEqual(first, {p.name: p.read_bytes() for p in self.assets.iterdir()})
        with tarfile.open(self.assets / "judge-my-ai-habits.tar.gz") as tar:
            self.assertEqual(set(tar.getnames()), {
                "judge-my-ai-habits/judge-my-ai-habits",
                "judge-my-ai-habits/dashboard.html", "judge-my-ai-habits/VERSION"})

    def test_piped_install_runs_and_renders_bundled_dashboard(self):
        self.install()
        result = subprocess.run([str(self.command), "--help"], env=self.env,
                                capture_output=True, text=True, check=True)
        self.assertIn("score", result.stdout)
        db = self.home / "analytics.sqlite"
        subprocess.run([sys.executable, "-c",
                        "import runpy,pathlib,sys; s=runpy.run_path(sys.argv[1]); "
                        "s['connect'](pathlib.Path(sys.argv[2])).close()",
                        str(self.command), str(db)], env=self.env, check=True, capture_output=True)
        subprocess.run([str(self.command), "dashboard", "--db", str(db)],
                       env=self.env, check=True, capture_output=True)
        html = (db.parent / "dashboard.html").read_text()
        self.assertIn("<html", html)
        self.assertNotIn("__JMAIH_DATA__", html)

    def test_upgrade_preserves_data_and_failed_checksum_keeps_command(self):
        self.install()
        original = self.command.resolve()
        data = self.home / "share" / "judge-my-ai-habits" / "analytics.sqlite"
        data.parent.mkdir(parents=True)
        data.write_bytes(b"existing user database")
        self.build("v0.2.0")
        self.install()
        upgraded = self.command.resolve()
        self.assertNotEqual(original, upgraded)
        self.assertEqual((upgraded.parent / "VERSION").read_text().strip(), "v0.2.0")
        self.assertEqual(data.read_bytes(), b"existing user database")
        archive = self.assets / "judge-my-ai-habits.tar.gz"
        archive.write_bytes(archive.read_bytes() + b"corrupt")
        result = self.install(succeeds=False)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertEqual(self.command.resolve(), upgraded)
        self.assertEqual(len(list((self.home / "app/releases").iterdir())), 2)

    def test_existing_unrelated_command_is_preserved(self):
        self.command.parent.mkdir()
        self.command.write_text("user-owned command")
        self.install(succeeds=False)
        self.assertEqual(self.command.read_text(), "user-owned command")
        self.assertEqual(list((self.home / "app/releases").iterdir()), [])

    def test_pinned_version_must_match(self):
        self.env["JMAIH_VERSION"] = "v0.2.0"
        result = self.install(succeeds=False)
        self.assertIn("archive contains v0.1.0", result.stderr)
        self.assertFalse(self.command.exists())

    def test_unexpected_archive_member_is_not_extracted(self):
        archive = self.assets / "judge-my-ai-habits.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            member = tarfile.TarInfo("../../unexpected")
            member.size = 4
            tar.addfile(member, io.BytesIO(b"oops"))
        (self.assets / "SHA256SUMS").write_text(
            hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")
        self.install(succeeds=False)
        self.assertFalse(self.command.exists())
        self.assertFalse((self.home / "app/unexpected").exists())


if __name__ == "__main__":
    unittest.main()
