import os
import shutil
import functools
import unittest

def get_missing_binaries(binaries):
    """Returns a list of any specified binaries that are not on the system PATH."""
    return [binary for binary in binaries if not shutil.which(binary)]

def enforce_test_toolchain(hard_requirements, soft_requirements=None):
    """
    Enforces asymmetric CI/CD vs. Local gating at the Class level.

    - In CI Mode (CI=true): Audits BOTH always and sometimes required lists.
      If ANY binary is missing, it reports all missing tools and hard-fails.
    - In Local Mode: Audits ONLY the always_required list. If any are missing,
      it skips the entire class.
    """
    is_ci = os.environ.get("CI") == "true"
    soft_requirements = soft_requirements or []

    missing_hard = get_missing_binaries(hard_requirements)
    missing_soft = get_missing_binaries(soft_requirements)

    if is_ci:
        all_missing = missing_hard + missing_soft
        if all_missing:
            raise RuntimeError(
                f"❌ CI BUILD FAILURE: Missing required system binaries: {', '.join(all_missing)}"
            )
    else:
        if missing_hard:
            raise unittest.SkipTest(
                f"⚠️ Skipped class: Missing hard requirements: {', '.join(missing_hard)}"
            )

def require_binaries(*binaries):
    """
    Decorator for individual test cases that require specific system binaries.

    - In CI mode: Bypassed (assumes enforce_test_toolchain already guaranteed presence).
    - In Local mode: Skips the individual test if any of the specified binaries are missing.
    """
    def decorator(test_func):
        @functools.wraps(test_func)
        def wrapper(*args, **kwargs):
            is_ci = os.environ.get("CI") == "true"
            if not is_ci:
                missing = get_missing_binaries(binaries)
                if missing:
                    raise unittest.SkipTest(
                        f"⚠️ Skipped: Missing binaries needed for this test: {', '.join(missing)}"
                    )
            return test_func(*args, **kwargs)
        return wrapper
    return decorator
