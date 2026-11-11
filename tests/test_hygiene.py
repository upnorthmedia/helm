"""scripts/check-hygiene.sh, run inside a temporary git repository.

The strings that should trip the guard are built from pieces, so this file
does not trip it when the guard scans the real repository.
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-hygiene.sh"

HOME_PATH = "/" + "Users/someone/project"
LINUX_HOME = "/" + "home/someone/project"
PERSONAL_EMAIL = "someone" + "@" + "example.org"
AUTHOR_EMAIL = "118795184+upnorthmedia" + "@" + "users.noreply.github.com"
TOKEN = "gh" + "p_" + "A" * 36


@unittest.skipIf(shutil.which("bash") is None or shutil.which("git") is None, "needs bash and git")
class HygieneGuardTest(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "scripts").mkdir()
        shutil.copy(SCRIPT, self.repo / "scripts" / "check-hygiene.sh")
        (self.repo / ".github").mkdir()
        shutil.copy(ROOT / ".github" / "hygiene-deny.txt", self.repo / ".github" / "hygiene-deny.txt")

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        subprocess.run(["git", "-C", str(self.repo), "add", rel], check=True)

    def run_guard(self, *args):
        return subprocess.run(
            ["bash", "scripts/check-hygiene.sh", *args], cwd=self.repo, capture_output=True, text=True, timeout=60
        )

    def test_a_clean_tree_passes(self):
        self.write("README.md", "# Demo\n\nNothing private here.\n")
        proc = self.run_guard()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("tracked files clean", proc.stdout)

    def test_home_directory_paths_fail_with_file_and_line(self):
        self.write("docs/a.md", f"line one\nsee {HOME_PATH}\n")
        self.write("docs/b.md", f"{LINUX_HOME}\n")
        proc = self.run_guard()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("docs/a.md:2: home directory path", proc.stdout)
        self.assertIn("docs/b.md:1: home directory path", proc.stdout)

    def test_only_the_noreply_author_and_ssh_remotes_are_allowed_emails(self):
        self.write("ok.md", f"Author: {AUTHOR_EMAIL}\nclone git@github.com:someone/helm.git\n")
        self.assertEqual(self.run_guard().returncode, 0)
        self.write("bad.md", f"mail {PERSONAL_EMAIL}\n")
        proc = self.run_guard()
        self.assertEqual(proc.returncode, 1)
        self.assertIn(f"bad.md:1: email address {PERSONAL_EMAIL}", proc.stdout)
        self.assertNotIn("ok.md", proc.stdout)

    def test_the_committed_deny_list_applies_and_is_not_scanned_itself(self):
        self.write(".github/hygiene-deny.txt", (self.repo / ".github" / "hygiene-deny.txt").read_text() + TOKEN + "\n")
        self.assertEqual(self.run_guard().returncode, 0)
        self.write("config.txt", f"token={TOKEN}\n")
        proc = self.run_guard()
        self.assertEqual(proc.returncode, 1)
        self.assertIn("config.txt:1: matches deny pattern in .github/hygiene-deny.txt", proc.stdout)
        self.assertNotIn(TOKEN, proc.stdout)  # the hit is named, not echoed

    def test_a_private_deny_list_adds_patterns_without_being_committed(self):
        self.write("notes.md", "shipped with the Bluebird crew\n")
        self.assertEqual(self.run_guard().returncode, 0)
        private = self.repo.parent / f"{self.repo.name}-private-deny.txt"
        private.write_text("# names that cannot be published\n\nBluebird\n")
        self.addCleanup(private.unlink)
        proc = self.run_guard("--deny", str(private))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("notes.md:1: matches deny pattern in", proc.stdout)

    def test_a_relative_deny_path_is_read_from_the_callers_directory(self):
        self.write("docs/notes.md", "shipped with the Bluebird crew\n")
        (self.repo / "docs" / "private-deny.txt").write_text("Bluebird\n")  # untracked
        proc = subprocess.run(
            ["bash", "../scripts/check-hygiene.sh", "--deny", "private-deny.txt"],
            cwd=self.repo / "docs", capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("docs/notes.md:1: matches deny pattern in", proc.stdout)

    def test_an_invalid_deny_pattern_is_an_error_not_a_clean_pass(self):
        self.write("README.md", "# Demo\n")
        private = self.repo.parent / f"{self.repo.name}-bad-deny.txt"
        private.write_text("unclosed(group\n")
        self.addCleanup(private.unlink)
        proc = self.run_guard("--deny", str(private))
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("invalid pattern", proc.stderr)
        self.assertNotIn("clean", proc.stdout)

    def test_untracked_files_are_not_scanned(self):
        self.write("README.md", "# Demo\n")
        (self.repo / "scratch.txt").write_text(f"{HOME_PATH}\n")
        self.assertEqual(self.run_guard().returncode, 0)


if __name__ == "__main__":
    unittest.main()
