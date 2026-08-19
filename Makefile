# Homelab Cluster Operations Makefile
# Fulfills Technical Debt #4: Centralize Global Configuration

# =============================================================================
# UNIVERSAL COMPILER VARIABLES (Evaluated Immediately)
# =============================================================================

# Establish a secure, user-owned temporary directory (CWE-377 Compliance) and a non-secure build directory
UID := $(shell id -u)
# Dynamic workspace hashing for isolation (macOS and Linux compliant)
WORKSPACE_HASH := $(shell (printf '%s' "$(CURDIR)" | sha256sum 2>/dev/null || printf '%s' "$(CURDIR)" | shasum -a 256 2>/dev/null || echo "default") | cut -c1-8)
SECURE_TMP_DIR := /tmp/ops-$(WORKSPACE_HASH)-$(UID)
# Ensure the secure directory exists with strict permissions (drwx------) before evaluating paths
_prep_secure_tmp := $(shell mkdir -p $(SECURE_TMP_DIR) && chmod 700 $(SECURE_TMP_DIR))

# =============================================================================
# DEFAULT WORKSPACE PARAMETERS (Fallback Defaults)
# =============================================================================
REQUIRED_TOOLS ?= shellcheck git
OPTIONAL_TOOLS ?= python3

FORCE ?= false			## [Optional] Bypass safety checks and run-once safety locks. Choices: [true, false]. Default: false
CI ?= false 			## [Optional] CI/CD Mode. Bypasses local file-sourcing. Choices: [true, false]. Default: false

# =============================================================================
# LOCAL HELPER FUNCTIONS
# =============================================================================
# Track tool presence status in-memory (TOOL_PRESENT_name = true/false)
# If a tool has not been evaluated yet, its state is undefined.

# 🔎 Private helper that checks command presence and populates the status map
define check_tool
$(if $(filter undefined,$(origin TOOL_PRESENT_$(1))),\
    $(if $(shell command -v $(1) 2>/dev/null),\
        $(eval TOOL_PRESENT_$(1) := true),\
        $(eval TOOL_PRESENT_$(1) := false)\
    )\
)
endef

# 🔎 Private helper to audit tools and populate missing lists dynamically
# Usage: $(call find_missing_tools,<SUFFIX>,<tools_list>)
define find_missing_tools
$(eval MISSING_$(1) := )\
$(foreach tool,$(2),\
    $(call check_tool,$(tool))\
    $(if $(filter false,$(TOOL_PRESENT_$(tool))),$(eval MISSING_$(1) += $(tool)))\
)
endef

# 🛡️ Hard Verification: Audits tools and halts execution with exit code 1 on any failure
define require_tools
$(call find_missing_tools,REQUIRED,$(1))\
$(if $(MISSING_REQUIRED),\
    @echo "❌ ERROR: Required tool(s) missing for target '$@':";\
    $(foreach bin,$(MISSING_REQUIRED),echo "   - $(bin)";)\
    echo "🛑 Please install the missing tool(s) and try again." && exit 1;\
)
endef

# ⚠️ Soft Verification: Audits tools and prints diagnostic warnings
# halts execution with exit code 1 for missing required files only
define audit_tools
$(call find_missing_tools,REQUIRED,$(1))\
$(call find_missing_tools,OPTIONAL,$(2))\
$(foreach tool,$(1),\
    $(if $(filter true,$(TOOL_PRESENT_$(tool))),\
		@echo "✅ $(tool) is required and present.";,\
		@echo "❌ $(tool) is required and missing.";\
	)
)
$(foreach tool,$(2),\
    $(if $(filter true,$(TOOL_PRESENT_$(tool))),\
		@echo "✅ $(tool) is present.";,\
		@echo "⚠️ $(tool) is missing.";\
	)
)
$(if $(MISSING_REQUIRED),\
    @echo "🛑 Please install the required missing tool(s) and try again." && exit 1;\
)
endef

# 🛡️ Safe Script Runner: Ensures executability, and runs the script safely
# Usage: $(call run_script,<script_path>, [optional arguments])
define run_script
@test -x $(1) || (echo "🛡️ Fixing stripped execution bit on '$(1)'..." && chmod +x $(1)); \
$(1) $(2)
endef

# =============================================================================
# WHITESPACE SANITIZER (Sanitizes trailing spaces from comments in advance)
# =============================================================================
# We use eager evaluation (:=) to strip trailing whitespace immediately on startup
FORCE        := $(strip $(FORCE))
CI           := $(strip $(CI))

# =============================================================================
# DYNAMIC MODULAR EXTENSIONS LOADER
# =============================================================================
# Locates and includes all '.mk' extension files in the repository root.
# Uses -include (hyphenated) to prevent Make from crashing on a fresh checkout
# if no extension files have been fetched or authored yet.
-include $(wildcard *.mk)

# Sentinel file indicating onboarding compliance
SETUP_SENTINEL := .setup_done

.PHONY: setup setup-githooks check-workstation-tools guard-setup test help \
		clean clean_core clean_modules _is_secure_tmp_safe _is_build_dir_safe

.DEFAULT_GOAL := help

help: ## Display this help message with target descriptions
	@echo "=========================================================================="
	@echo " Homelab Cluster Operations Toolchain"
	@echo "=========================================================================="
	@echo "Usage: make <target>"
	@echo ""
	@echo "Variables:"
	@grep -h -E '^[a-zA-Z0-9_-]+ \?=.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = " \\?=.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Targets:"
	@grep -h -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ==============================================================================
# 🛠️ WORKSPACE ONBOARDING TARGETS
# ==============================================================================

setup: check-workstation-tools setup-githooks ## Bootstrap local WSL workspace and prepare development plane
	@touch $(SETUP_SENTINEL)
	@echo "=========================================================================="
	@echo "🎉 SUCCESS: Workspace is configured!"
	@echo "=========================================================================="

setup-githooks: ## Activate local Git hooks and map core.hooksPath
	@echo "⚓ Activating local workstation Git hooks..."
	$(call require_tools,git)
	@chmod +x githooks/pre-commit githooks/commit-msg 2>/dev/null || true
	@chmod +x githooks/pre-commit.d/* githooks/commit-msg.d/* 2>/dev/null || true
	@chmod +x scripts/workstation/*.sh 2>/dev/null || true
	@git config core.hooksPath githooks
	@echo "✅ Git hooks successfully mapped to 'githooks/' and marked executable!"

check-workstation-tools: ## Validate if required binaries are present on disk without hard fail
	@echo "🔎 Auditing workstation binary toolchain..."
	$(call audit_tools,$(REQUIRED_TOOLS),$(OPTIONAL_TOOLS))

# Quietly guard critical targets. Supports FORCE=true to allow pipeline/CI bypasses.
# This must be the first dependency in any target chain that requires a fully initialized workstation.
guard-setup:
ifeq ($(FORCE),true)
	@echo "⚠️ FORCE=true specified. Bypassing workspace setup validation checks!"
else ifeq ($(CI),true)
	@echo "🟢 CI/CD environment detected. Bypassing workstation setup check."
else ifeq ($(wildcard $(SETUP_SENTINEL)),)
	@echo "=========================================================================="
	@echo "🛑 REJECTED: Your workspace has not been initialized yet!"
	@echo "👉 To unblock this target and configure your workstation linter gates,"
	@echo "   you must run the onboarding target first:"
	@echo "   "
	@echo "   make setup"
	@echo "=========================================================================="
	@exit 1
endif

# ==============================================================================
# ⚙️ DETAILED OPERATIONAL TARGETS
# ==============================================================================

test: guard-setup ## Run the complete workstation test suite
	@echo "=== Running Workstation Test Suite ==="
	$(call require_tools,python3)
	python3 -m unittest discover -v -s tests -p "test_*.py"
	@echo "✅ All unit tests passed successfully!"

# ==============================================================================
# 🧹 CLEANUP CONTROLS
# ==============================================================================

# 🛡️ Pure GNU Make-level path safety checkers (No subshell spawn overhead, completely decoupled)
is_secure_tmp_safe = $(and $(1),$(filter /tmp/%,$(1)),$(filter-out /tmp /tmp/,$(subst //,/,$(subst //,/,$(strip $(1))))))

clean_core: # Remove decrypted environment caches
	@echo "🧹 Wiping workspace build artifacts and secure caches..."

	# Only purge SECURE_TMP_DIR if it is strictly a safe /tmp subdirectory
	$(if $(call is_secure_tmp_safe,$(SECURE_TMP_DIR)),\
		@rm -rf "$(SECURE_TMP_DIR)" && echo "✅ Purged secure temp directory: $(SECURE_TMP_DIR)",\
		@echo "⚠️ Skipped SECURE_TMP_DIR purge: Path is empty, unsafe, or outside /tmp/"\
	)

clean_modules::
	@echo "🧹 Cleaning child modules"

clean: clean_core clean_modules ## Remove temporary build files and decrypted environment caches
	@echo "✅ Clean complete."
