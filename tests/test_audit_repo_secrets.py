import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

class TestAuditRepoSecrets(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary directory mimicking the Git repository
        self.repo_root = Path(tempfile.mkdtemp(prefix="secrets-audit-test-"))

        # Point to the actual workstation audit script under test (tests/../scripts/workstation/audit-repo-secrets.sh)
        self.script_src = Path(__file__).resolve().parent.parent / "scripts" / "workstation" / "audit-repo-secrets.sh"

        self.script_dst = self.repo_root / "scripts" / "workstation" / "audit-repo-secrets.sh"
        self.script_dst.parent.mkdir(parents=True, exist_ok=True)

        # Copy the script to the isolated temporary repository
        shutil.copy2(self.script_src, self.script_dst)
        self.script_dst.chmod(0o755)

        # Initialize Git in our temporary test directory
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True)

        # Create .gitattributes to satisfy the line normalization check by default
        self.write_file(".gitattributes", "* text=auto eol=lf\n", stage=True)

        # Commit a baseline dummy file to establish HEAD state
        self.write_file("dummy.txt", "baseline state\n", stage=True)
        subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=self.repo_root, check=True, stdout=subprocess.DEVNULL)

    def tearDown(self):
        # Clean up temporary test repository
        shutil.rmtree(self.repo_root)

    def write_file(self, relative_path: str, content: str, stage: bool = False) -> Path:
        full_path = self.repo_root / relative_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        if stage:
            subprocess.run(["git", "add", relative_path], cwd=self.repo_root, check=True, stdout=subprocess.DEVNULL)
        return full_path

    def run_audit(self) -> subprocess.CompletedProcess:
        # Runs the script under test in the temporary repository
        return subprocess.run(
            ["bash", str(self.script_dst)],
            cwd=self.repo_root,
            capture_output=True,
            text=True
        )

    def test_clean_repository_passes_successfully(self):
        # A pristine repository with no secrets and a present .gitattributes should pass with 0 exit code
        result = self.run_audit()
        self.assertEqual(result.returncode, 0)
        self.assertIn("SUCCESS! Your repository is 100% clean", result.stdout)

    def test_actively_tracked_sensitive_file_fails_audit(self):
        # Stage and track a sensitive file (.env)
        self.write_file("configs/prod.env", "API_KEY=sensitive-production-token-12345\n", stage=True)

        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("CRITICAL WARNING: Git is actively tracking sensitive files!", result.stdout)
        self.assertIn("prod.env", result.stdout)

    def test_unignored_sensitive_file_on_disk_fails_audit(self):
        # Create a sensitive file on disk (.tfvars), but do NOT list it in .gitignore
        self.write_file("infrastructure/secret.tfvars", "db_password = \"secure_pass\"\n", stage=False)

        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("WARNING: Found existing secret files NOT covered by .gitignore:", result.stdout)
        self.assertIn("secret.tfvars", result.stdout)

    def test_ignored_sensitive_file_passes_audit(self):
        # Create .gitignore containing .env pattern
        self.write_file(".gitignore", "*.env\n", stage=True)
        # Create a sensitive .env file on disk (not staged/tracked)
        self.write_file("local.env", "DB_CONN=localhost\n", stage=False)

        result = self.run_audit()
        self.assertEqual(result.returncode, 0)
        self.assertIn("Safe! All existing local secret files", result.stdout)

    def test_high_entropy_plaintext_scan_triggers_warning_but_passes_build(self):
        # Create a source file containing a suspicious plaintext credential assignment matching the pattern
        # The file extension must match one of the audited extensions: tf, sh, yaml, yml, env, json
        suspicious_code = (
            "#!/usr/bin/env bash\n"
            "api_token=\"pat-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6\"\n"
        )
        self.write_file("scripts/worker.sh", suspicious_code, stage=True)

        result = self.run_audit()
        # Advisory checks do not cause hard failure of the script, so exit code must remain 0
        self.assertEqual(result.returncode, 0)
        self.assertIn("POTENTIAL PLAIN-TEXT SECRET LEAKS DETECTED:", result.stdout)
        self.assertIn("worker.sh", result.stdout)

    def test_missing_gitattributes_warns_but_passes_build(self):
        # Delete .gitattributes
        gitattributes_path = self.repo_root / ".gitattributes"
        if gitattributes_path.exists():
            subprocess.run(["git", "rm", ".gitattributes"], cwd=self.repo_root, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(["git", "commit", "-m", "chore: remove gitattributes"], cwd=self.repo_root, check=True, stdout=subprocess.DEVNULL)

        result = self.run_audit()
        self.assertEqual(result.returncode, 0)
        self.assertIn("Missing .gitattributes! Highly recommended", result.stdout)

if __name__ == "__main__":
    unittest.main()
