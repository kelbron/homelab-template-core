# tests/test_audit_workspace_boundaries.py
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

class TestAuditWorkspaceBoundaries(unittest.TestCase):
    def setUp(self):
        # Create isolated temporary directory for Git mocking
        self.test_dir = Path(tempfile.mkdtemp(prefix="git-hook-test-"))

        # Initialize a mock Git repository
        subprocess.run(["git", "init", "-b", "main"], cwd=self.test_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test Bot"], cwd=self.test_dir, check=True)
        subprocess.run(["git", "config", "user.email", "bot@test.org"], cwd=self.test_dir, check=True)

        # Copy the script to test
        self.script_src = Path(__file__).resolve().parents[1] / "scripts" / "workstation" / "audit-workspace-boundaries.sh"
        self.script_dst = self.test_dir / "scripts" / "workstation" / "audit-workspace-boundaries.sh"
        self.script_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.script_src, self.script_dst)
        self.script_dst.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def stage_file(self, relative_path: str, content: str = "dummy-content") -> None:
        """Helper to create and git-stage a file inside the isolated sandbox."""
        file_path = self.test_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", relative_path], cwd=self.test_dir, check=True, capture_output=True)

    def run_audit(self) -> subprocess.CompletedProcess:
        """Executes the audit script within our isolated git sandbox."""
        return subprocess.run(
            ["sh", "scripts/workstation/audit-workspace-boundaries.sh"],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )

    # =========================================================================
    # 🔎 HOOK AUDIT TEST CASES
    # =========================================================================

    def test_empty_stage_passes(self):
        """Pre-commit Hook should succeed immediately if no files are staged."""
        result = self.run_audit()
        self.assertEqual(result.returncode, 0)
        self.assertIn("No staged files to audit.", result.stdout)

    def test_standard_code_staged_passes(self):
        """Standard source files and ignored formats should bypass validations cleanly."""
        self.stage_file("src/main.py", "print('hello')")
        result = self.run_audit()
        self.assertEqual(result.returncode, 0)
        self.assertIn("All staged files comply with repository boundary standards.", result.stdout)

    def test_github_workflows_bypass_manifest_rules_passes(self):
        """GitHub actions workflow manifests (.github/workflows/*) are explicitly allowed and bypassed."""
        self.stage_file(".github/workflows/ci.yml", "name: CI")
        result = self.run_audit()
        self.assertEqual(result.returncode, 0)

    def test_root_manifest_leak_fails(self):
        """Staging a compiled manifest directly inside the repository root must trigger a loud failure."""
        self.stage_file("kustomize-argocd.yml", "apiVersion: argoproj.io/v1alpha1")
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: Manifest file leaked in repository root", result.stdout)

    def test_flat_manifest_file_inside_manifests_fails(self):
        """Staging a flat manifest directly in manifests/ root (violating ADR 002) must be blocked."""
        self.stage_file("manifests/leaked-manifest.yaml", "kind: ConfigMap")
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: Prohibited flat-file manifest detected", result.stdout)

    def test_flat_manifest_file_inside_base_or_apps_fails(self):
        """Staging a flat manifest inside manifests/base/ or manifests/apps/ (violating ADR 002) must be blocked."""
        self.stage_file("manifests/base/leaked-infra.yaml", "kind: Service")
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: Prohibited flat-file manifest inside base/", result.stdout)

        # Try apps folder flat leak
        subprocess.run(["git", "rm", "-f", "manifests/base/leaked-infra.yml"], cwd=self.test_dir, capture_output=True)
        self.stage_file("manifests/apps/leaked-app.yml", "kind: Deployment")
        result = self.run_audit()
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: Prohibited flat-file manifest inside apps/", result.stdout)

    def test_encapsulated_manifest_subfolder_passes(self):
        """Staging structured manifests inside subfolders (conforming to ADR 002) must succeed cleanly."""
        self.stage_file("manifests/apps/vaultwarden/vaultwarden.yaml", "kind: Deployment")
        self.stage_file("manifests/base/cert-manager/cert-manager-values.yaml", "image: cert-manager")
        result = self.run_audit()
        self.assertEqual(result.returncode, 0)
        self.assertIn("All staged files comply with repository boundary standards.", result.stdout)

if __name__ == "__main__":
    unittest.main()
