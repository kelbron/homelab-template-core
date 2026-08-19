import os
import shutil
import subprocess
import tempfile
import unittest
from builtins import FileNotFoundError
from pathlib import Path
from tests.support import enforce_test_toolchain
class TestMakefileClean(unittest.TestCase):

    HARD_REQUIREMENTS = ["make"]

    @classmethod
    def setUpClass(cls):
        enforce_test_toolchain(cls.HARD_REQUIREMENTS)


    def setUp(self):
        # 1. Create a temporary directory for isolated testing
        self.test_dir = Path(tempfile.mkdtemp(prefix="makefile-clean-test-"))

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

    def write_test_harness(self, test_path):
        # We append a test-only target that calls our internal Makefile functions directly
        test_content = f"""
# Disable profile evaluations during unit testing
USE_PROFILES := false

include Makefile

test-secure-tmp-macro:
	@echo "RESULT: $(if $(call is_secure_tmp_safe,{test_path}),SAFE,UNSAFE)"
"""
        (self.test_dir / "Makefile.test").write_text(test_content, encoding="utf-8")


    # =========================================================================
    # 🔎 DIRECT NATIVE MAKE-LEVEL MACRO TESTS
    # =========================================================================

    def test_makefile_secure_tmp_safe_macro_directly(self):
        """Verify that the Makefile's is_secure_tmp_safe macro evaluates correctly."""
        safe_cases = ["/tmp/k3s-lab-1000", "/tmp/test-folder", "/tmp/a"]
        unsafe_cases = ["/", "", "/tmp", "/tmp/", "/tmp//", "/home/sysop", "relative-folder", "../outside"]

        for path in safe_cases:
            self.write_test_harness(path)
            result = subprocess.run(
                ["make", "-f", "Makefile.test", "test-secure-tmp-macro"],
                cwd=self.test_dir,
                capture_output=True,
                text=True
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("RESULT: SAFE", result.stdout, f"Expected path '{path}' to evaluate as SAFE, but got: {result.stdout}")

        for path in unsafe_cases:
            self.write_test_harness(path)
            result = subprocess.run(
                ["make", "-f", "Makefile.test", "test-secure-tmp-macro"],
                cwd=self.test_dir,
                capture_output=True,
                text=True
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("RESULT: UNSAFE", result.stdout, f"Expected path '{path}' to evaluate as UNSAFE, but got: {result.stdout}")

    # =========================================================================
    # 💥 OPERATIONAL CLEAN TARGET INTEGRATION TESTS (Using overrides)
    # =========================================================================

    def test_live_secure_tmp_safe_deletion(self):
        """Test that running 'make clean' with a valid SECURE_TMP_DIR under /tmp deletes it physically."""
        secure_tmp = tempfile.mkdtemp(prefix="k3s-lab-test-safe-")
        try:
            dummy_file = Path(secure_tmp) / "kustomize-argocd.yaml"
            dummy_file.write_text("apiVersion: v1", encoding="utf-8")

            result = subprocess.run(
                ["make", "clean", f"SECURE_TMP_DIR={secure_tmp}"],
                cwd=self.test_dir,
                capture_output=True,
                text=True
            )
            self.assertEqual(result.returncode, 0, f"Make clean failed: {result.stderr}")
            self.assertIn("✅ Purged secure temp directory:", result.stdout)
            self.assertFalse(os.path.exists(secure_tmp))
        finally:
            if os.path.exists(secure_tmp):
                shutil.rmtree(secure_tmp)

    def test_live_secure_tmp_unsafe_skipped(self):
        """Test that running 'make clean' with an unsafe SECURE_TMP_DIR is safely skipped without crashing."""
        unsafe_paths = ["/", "/tmp", "/tmp/", "/var/tmp", "build", "../escape"]
        for path in unsafe_paths:
            result = subprocess.run(
                ["make", "clean", f"SECURE_TMP_DIR={path}", "BUILD_DIR=dummy-nonexistent", "USE_PROFILES=false"],
                cwd=self.test_dir,
                capture_output=True,
                text=True
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("⚠️ Skipped SECURE_TMP_DIR purge:", result.stdout)

    def test_live_clean_cache_extension(self):
        """Test that running 'make clean' with an override to clean-cache calls both definitions"""
        build_dir = "test-build-relative-folder-xyz"
        target_path = self.test_dir / build_dir
        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "rendered.yaml").write_text("dummy", encoding="utf-8")

        # 🔗 Dynamically provision a mock k3s.mk to hook into the double-colon target
        # This isolates testing to the modular CLEAN mechanism itself!
        mk_content = f"""
clean_modules::
	@rm -rf "$(BUILD_DIR)";
	echo "✅ Purged local build directory: $(BUILD_DIR)";
"""
        (self.test_dir / "k3s.mk").write_text(mk_content, encoding="utf-8")

        result = subprocess.run(
            ["make", "clean", "SECURE_TMP_DIR=dummy-secure-nonexistent", f"BUILD_DIR={build_dir}"],
            cwd=self.test_dir,
            capture_output=True,
            text=True
        )
        self.assertEqual(result.returncode, 0, f"Make clean failed: {result.stderr}")
        self.assertIn("⚠️ Skipped SECURE_TMP_DIR purge:", result.stdout)
        self.assertIn(f"✅ Purged local build directory: {build_dir}", result.stdout)
        self.assertIn("✅ Clean complete.", result.stdout)
        self.assertFalse(target_path.exists())

if __name__ == "__main__":
    unittest.main()
