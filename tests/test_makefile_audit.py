import os
import shutil
import subprocess
import tempfile
import unittest
from builtins import FileNotFoundError
from pathlib import Path
from tests.support import enforce_test_toolchain

class TestMakefileAudit(unittest.TestCase):

    HARD_REQUIREMENTS = ["make"]

    @classmethod
    def setUpClass(cls):
        enforce_test_toolchain(cls.HARD_REQUIREMENTS)


    def setUp(self):
        # 1. Create a temporary directory for isolated testing
        self.test_dir = Path(tempfile.mkdtemp(prefix="makefile-audit-test-"))

        # 2. Locate the Makefile in the repository root
        current_file = Path(__file__).resolve()

        self.makefile_src = None
        for parent in current_file.parents:
            candidate = parent / "Makefile"
            if candidate.exists():
                self.makefile_src = candidate
                break

        if not self.makefile_src:
            raise FileNotFoundError("Could not locate the project Makefile to test.")

        # Copy the actual Makefile to our temporary directory
        shutil.copy2(self.makefile_src, self.test_dir / "Makefile")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def write_test_makefile(self, required_tools="", optional_tools=""):
        test_makefile_content = f"""
# Disable profile evaluations during unit testing
USE_PROFILES := false
include Makefile

# Override variables for testing
REQUIRED_TOOLS := {required_tools}
OPTIONAL_TOOLS := {optional_tools}

test-require-success:
    $(call require_tools,sh)

test-require-fail:
	$(call require_tools,nonexistentbinaryxyz)

test-audit-clean:
	$(call audit_tools,sh,bash)

test-audit-fail-required:
	$(call audit_tools,nonexistentrequired,bash)

test-audit-fail-optional:
	$(call audit_tools,sh,nonexistentoptional)
"""
        (self.test_dir / "Makefile.test").write_text(test_makefile_content, encoding="utf-8")

    def test_require_tools_success(self):
        self.write_test_makefile()
        result = subprocess.run(
            ["make", "-f", "Makefile.test", "test-require-success"],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)

    def test_require_tools_failure(self):
        self.write_test_makefile()
        result = subprocess.run(
            ["make", "-f", "Makefile.test", "test-require-fail"],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("❌ ERROR: Required tool(s) missing for target 'test-require-fail':", result.stdout)
        self.assertIn("- nonexistentbinaryxyz", result.stdout)
        self.assertIn("🛑 Please install the missing tool(s) and try again.", result.stdout)

    def test_audit_tools_clean(self):
        self.write_test_makefile()
        result = subprocess.run(
            ["make", "-f", "Makefile.test", "test-audit-clean"],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("✅ sh is required and present.", result.stdout)
        self.assertIn("✅ bash is present.", result.stdout)

    def test_audit_tools_fail_required(self):
        self.write_test_makefile()
        result = subprocess.run(
            ["make", "-f", "Makefile.test", "test-audit-fail-required"],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("❌ nonexistentrequired is required and missing.", result.stdout)
        self.assertIn("✅ bash is present.", result.stdout)
        self.assertIn("🛑 Please install the required missing tool(s) and try again.", result.stdout)

    def test_audit_tools_fail_optional(self):
        self.write_test_makefile()
        result = subprocess.run(
            ["make", "-f", "Makefile.test", "test-audit-fail-optional"],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0) # Optional missing shouldn't fail
        self.assertIn("✅ sh is required and present.", result.stdout)
        self.assertIn("⚠️ nonexistentoptional is missing.", result.stdout)
        self.assertNotIn("🛑 Please install the required missing tool(s) and try again.", result.stdout)

if __name__ == "__main__":
    unittest.main()
