import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

class TestAuditShellcheck(unittest.TestCase):
    def setUp(self):
        # Isolated temporary Git repository for safe testing
        self.repo_root = Path(tempfile.mkdtemp(prefix="shellcheck-test-"))
        
        # Point to the actual workstation audit script
        self.script_src = Path(__file__).resolve().parent.parent / "scripts" / "workstation" / "audit-shellcheck.sh"
        self.script_dst = self.repo_root / "scripts" / "workstation" / "audit-shellcheck.sh"
        self.script_dst.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy to the test workspace
        shutil.copy2(self.script_src, self.script_dst)
        self.script_dst.chmod(0o755)
        
        # Create a mock bin directory to handle shellcheck-less test environments
        self.bin_dir = self.repo_root / "mock_bin"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.mock_shellcheck = self.bin_dir / "shellcheck"
        
        # A mock shellcheck binary that catches bad array syntax
        self.mock_shellcheck.write_text("""#!/usr/bin/env bash
target_content=""
if [ $# -gt 0 ] && [ -f "$1" ]; then
    target_content=$(cat "$1")
else
    target_content=$(cat -)
fi

if echo "$target_content" | grep -q "echo \\$MY_ARRAY"; then
    echo "Double quote array expansion warning (SC2128)" >&2
    exit 1
fi
exit 0
""", encoding="utf-8")
        self.mock_shellcheck.chmod(0o755)
        
        # Init Git
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo_root, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_root, check=True)
        
        # Commit a baseline file to establish HEAD
        dummy = self.repo_root / "dummy.txt"
        dummy.write_text("baseline", encoding="utf-8")
        subprocess.run(["git", "add", "dummy.txt"], cwd=self.repo_root, check=True)
        subprocess.run(["git", "commit", "-m", "first commit"], cwd=self.repo_root, check=True, stdout=subprocess.DEVNULL)

    def tearDown(self):
        shutil.rmtree(self.repo_root)

    def write_file(self, path_relative_to_root: str, content: str, stage: bool = False) -> Path:
        full_path = self.repo_root / path_relative_to_root
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        if stage:
            subprocess.run(["git", "add", path_relative_to_root], cwd=self.repo_root, check=True, stdout=subprocess.DEVNULL)
        return full_path

    def run_audit(self) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["PATH"] = f"{self.bin_dir}:{env['PATH']}"
        return subprocess.run(
            ["bash", str(self.script_dst)],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            env=env
        )

    def test_audit_passes_with_no_changes(self):
        result = self.run_audit()
        self.assertEqual(result.returncode, 0)
        self.assertIn("ShellCheck audit completed successfully", result.stdout)

    def test_audit_catches_errors_in_working_version_of_staged_files(self):
        bad_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "MY_ARRAY=('a' 'b')\n"
            "echo $MY_ARRAY\n"
        )
        self.write_file("scripts/test-error.sh", bad_script, stage=True)
        
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ShellCheck failed on", result.stdout)

    def test_audit_ignores_unstaged_files_with_errors(self):
        bad_script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "MY_ARRAY=('a' 'b')\n"
            "echo $MY_ARRAY\n"
        )
        # Write but DO NOT stage
        self.write_file("scripts/test-error.sh", bad_script, stage=False)
        
        result = self.run_audit()
        self.assertEqual(result.returncode, 0)
        self.assertIn("ShellCheck audit completed successfully", result.stdout)

if __name__ == "__main__":
    unittest.main()
