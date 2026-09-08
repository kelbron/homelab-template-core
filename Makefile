# Homelab Cluster Operations Makefile
# Fulfills Technical Debt #4: Centralize Global Configuration

# =============================================================================
# UNIVERSAL COMPILER VARIABLES (Evaluated Immediately)
# =============================================================================

# Establish a secure, user-owned temporary directory (CWE-377 Compliance) and a non-secure build directory
UID := $(shell id -u)
# Dynamic workspace hashing for isolation (macOS and Linux compliant)
WORKSPACE_HASH := $(shell (printf '%s' "$(CURDIR)" | sha256sum 2>/dev/null || printf '%s' "$(CURDIR)" | shasum -a 256 2>/dev/null || echo "default") | cut -c1-8)
SECURE_TMP_DIR := /tmp/ops-$(UID)-$(WORKSPACE_HASH)
# Ensure the secure directory exists with strict permissions (drwx------) before evaluating paths
_prep_secure_tmp := $(shell mkdir -m 700 -p $(SECURE_TMP_DIR))

# =============================================================================
# DEFAULT WORKSPACE PARAMETERS (Fallback Defaults)
# =============================================================================
REQUIRED_TOOLS ?= shellcheck git python3
OPTIONAL_TOOLS =

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

# ensure that if python is installed that it has venv and pip
define audit_python
@if command -v python3 >/dev/null; then \
	if ! python3 -c "import venv" >/dev/null 2>&1; then \
		echo "❌ python3 is present, but the 'venv' module is missing."; \
		echo "👉 Please install it via your package manager (e.g., 'sudo apt install python3-venv') to enable testing."; \
		exit 1; \
	fi \
fi
endef

# 🛡️ Safe Script Runner: Ensures executability, and runs the script safely
# Usage: $(call run_script,<script_path>, [optional arguments])
define run_script
@test -x $(1) || (echo "🛡️ Fixing stripped execution bit on '$(1)'..." && chmod +x $(1)); \
$(1) $(2)
endef

# Print a pytest-style dynamic terminal-width separator line
# Usage: $(call print_separator,text to center)
define print_separator
	@sh -c '\
		msg=" $(strip $(1)) "; \
		cols=$${COLUMNS:-$$(stty size 2>/dev/null | cut -d" " -f2)}; \
		cols=$${cols:-80}; \
		len=$${#msg}; \
		if [ $$len -ge $$cols ]; then \
			printf "%s\n" "$$msg"; \
		else \
			pad=$$(( (cols - len) / 2 )); \
			rem=$$(( cols - len - pad )); \
			left=$$(printf "%*s" "$$pad" "" | tr " " "="); \
			right=$$(printf "%*s" "$$rem" "" | tr " " "="); \
			printf "%s%s%s\n" "$$left" "$$msg" "$$right"; \
		fi'
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
TEST_MODULE_TARGETS ?=
CLEAN_MODULE_TARGETS ?=

-include $(wildcard *.mk)

# Sentinel file indicating onboarding compliance
SETUP_SENTINEL := .setup_done

.PHONY: setup setup-githooks check-workstation-tools guard-setup help \
		test test_core test_modules \
		clean clean_core clean_modules

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
	@if [ ! -d ".venv" ]; then \
		echo "📦 Provisioning isolated Python Virtual Environment...";\
		python3 -m venv .venv; \
		.venv/bin/pip install -U pip setuptools > .venv/pip-bootstrap.log 2>&1 || { cat .venv/pip-bootstrap.log; exit 1; }; \
		.venv/bin/pip install -e . pytest ruff >> .venv/pip-bootstrap.log 2>&1 || { cat .venv/pip-bootstrap.log; exit 1; }; \
		echo "🎉 Virtual environment successfully initialized!"; \
	else \
		echo "✅ Virtual environment (.venv) already exists."; \
	fi
	@touch $(SETUP_SENTINEL)
	@echo "=========================================================================="
	@echo "🎉 SUCCESS: Workspace is configured!"
	@echo "=========================================================================="

setup-githooks: ## Activate local Git hooks and map core.hooksPath
ifeq ($(CI),true)
	@echo "🟢 CI/CD environment detected. Bypassing Git hooks registration."
else
	@echo "⚓ Activating local workstation Git hooks..."
	$(call require_tools,git)
	@chmod +x githooks/pre-commit githooks/commit-msg 2>/dev/null || true
	@chmod +x githooks/pre-commit.d/* githooks/commit-msg.d/* 2>/dev/null || true
	@chmod +x scripts/workstation/*.sh 2>/dev/null || true
	@git config core.hooksPath githooks
	@echo "✅ Git hooks successfully mapped to 'githooks/' and marked executable!"
endif

check-workstation-tools: ## Validate if required binaries are present on disk without hard fail
	@echo "🔎 Auditing workstation binary toolchain..."
	$(call audit_tools,$(REQUIRED_TOOLS),$(OPTIONAL_TOOLS))
	$(call audit_python)

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

test_core: guard-setup ## Run the complete workstation test suite
	@if [ ! -d ".venv" ]; then \
		echo "🛑 ERROR: Workspace is not initialized. Please run 'make setup' first."; \
		exit 1; \
	fi
	$(call require_tools,python3)
	$(call print_separator, Running Workstation Test Suite)
	@.venv/bin/pytest tests/
	@echo "✅ All Python unit tests passed successfully!"

test_modules: guard-setup
ifneq ($(strip $(TEST_MODULE_TARGETS)),)
	$(call print_separator,Running Module Test Suites)
	@$(MAKE) --no-print-directory $(TEST_MODULE_TARGETS)
endif

test: test_core test_modules
	$(call print_separator,✅ Testing complete)

# ==============================================================================
# 🧹 CLEANUP CONTROLS
# ==============================================================================

# 🛡️ Pure GNU Make-level path safety checkers (No subshell spawn overhead, completely decoupled)
is_secure_tmp_safe = $(and $(1),$(filter /tmp/%,$(1)),$(filter-out /tmp /tmp/,$(subst //,/,$(subst //,/,$(strip $(1))))))



clean_core: # Remove decrypted environment caches
	$(call print_separator, 🧹 Wiping workspace build artifacts and secure caches)
# 	Only purge SECURE_TMP_DIR if it is strictly a safe /tmp subdirectory
	@if [ -n "$(call is_secure_tmp_safe,$(SECURE_TMP_DIR))" ]; then \
		rm -rf "$(SECURE_TMP_DIR)" && echo "✅ Purged secure temp directory: $(SECURE_TMP_DIR)"; \
	else \
		echo "⚠️ Skipped SECURE_TMP_DIR purge: Path is empty or unsafe or outside /tmp/"; \
	fi


clean_modules:
ifneq ($(strip $(CLEAN_MODULE_TARGETS)),)
	$(call print_separator,🧹 Cleaning child modules)
	@$(MAKE) --no-print-directory $(CLEAN_MODULE_TARGETS)
endif

clean: clean_core clean_modules ## Remove temporary build files and decrypted environment caches
	$(call print_separator,✅ Clean complete)
