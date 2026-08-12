# Homelab Cluster Operations Makefile
# Fulfills Technical Debt #4: Centralize Global Configuration

# =============================================================================
# ⚙️ CONFIGURATION & EXTENSIONS
# =============================================================================

# Define universal binary requirements. Individual repositories can append 
# their own specific tools (e.g., REQUIRED_TOOLS += terraform or REQUIRED_TOOLS += mvnw).
REQUIRED_TOOLS ?= shellcheck git

PROFILE ?= local		## [Optional] Target environment profile. Maps to any 'inventory/<name>.env' file. Default: local
FORCE ?= false			## [Optional] Bypass safety checks and run-once safety locks. Choices: [true, false]. Default: false
CI ?= false 			## [Optional] CI/CD Mode. Bypasses local file-sourcing. Choices: [true, false]. Default: false
USE_PROFILES ?= false	## [Optional] Enable environment variable profile loading. Choices: [true, false]. Default: false

# =============================================================================
# 🧼 WHITESPACE SANITIZER (Sanitizes trailing spaces from comments in advance)
# =============================================================================
# We use eager evaluation (:=) to strip trailing whitespace immediately on startup
PROFILE      := $(strip $(PROFILE))
FORCE        := $(strip $(FORCE))
CI           := $(strip $(CI))
USE_PROFILES := $(strip $(USE_PROFILES))

ENV_FILE := inventory/$(PROFILE).env

# Define the temporary build artifact
CLEAN_ENV := /tmp/clean.env

# =============================================================================
# 🔐 ENVIRONMENT LOADER
# =============================================================================
ifeq ($(CI),true)
  # 🟢 CI/CD Mode: Bypass local file-sourcing entirely.
  $(info === CI/CD Mode: Inheriting environment variables from runner ===)
else ifeq ($(USE_PROFILES),true)
  # 💻 Profile Loading Enabled: Verify file existence before running sanitizer
  ifeq ($(wildcard $(ENV_FILE)),)
    $(warning ⚠️  WARNING: Profile configuration file not found at '$(ENV_FILE)'!)
    $(warning    -> To fix this, create the file or copy from a template.)
  else ifeq ($(wildcard ./scripts/workstation/sanitize-env.sh),)
    # 🟡 Sandbox/Missing Script Mode: Fallback gracefully
    $(info === Sandbox Mode: Profile file found, but sanitize-env.sh is missing. Skipping load ===)
  else
    # 💻 Local Workstation Mode: Clean, include, and export the selected profile file.
    $(info === Local Workstation Mode: Sanitizing and loading $(ENV_FILE) ===)
    $(info $(shell ./scripts/workstation/sanitize-env.sh $(ENV_FILE) $(CLEAN_ENV)))
    -include $(CLEAN_ENV)
    export
  endif
endif

# Sentinel file indicating onboarding compliance
SETUP_SENTINEL := .setup_done

.DEFAULT_GOAL := help

.PHONY: setup setup-githooks check-workstation-tools guard-setup test help

help: ## Display this help message with target descriptions
	@echo "=========================================================================="
	@echo " Homelab Cluster Operations Toolchain"
	@echo "=========================================================================="
	@echo "Usage: make <target> [VARIABLE=value] [PROFILE=]"
	@echo ""
	@echo "Variables:"
	@grep -h -E '^[a-zA-Z0-9_-]+ \?=.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = " \\?=.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Targets:"
	@grep -h -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# ==============================================================================
# 🛠️ WORKSPACE ONBOARDING TARGETS
# ==============================================================================

## 1. Master Onboarding Target: Runs all bootstrapping steps in sequence
setup: check-workstation-tools setup-githooks ## Bootstrap local WSL workspace and prepare development plane
	@touch $(SETUP_SENTINEL)
	@echo "=========================================================================="
	@echo "🎉 SUCCESS: Workspace is configured!"
	@echo "=========================================================================="

## 2. Activate Git Hooks
setup-githooks: ## Activate local Git hooks and map core.hooksPath
	@echo "⚓ Activating local workstation Git hooks..."
	@chmod +x githooks/pre-commit githooks/commit-msg 2>/dev/null || true
	@chmod +x githooks/pre-commit.d/* githooks/commit-msg.d/* 2>/dev/null || true
	@chmod +x scripts/workstation/*.sh 2>/dev/null || true
	@git config core.hooksPath githooks
	@echo "✅ Git hooks successfully mapped to 'githooks/' and marked executable!"

## 3. Passive Tooling Audit (Tells devs what they are missing before hooks fail)
check-workstation-tools: ## Validate if required binaries are present on disk
	@echo "🔎 Auditing workstation binary toolchain..."
	@failed=0; \
	for tool in $(REQUIRED_TOOLS); do \
		if ! command -v $$tool > /dev/null 2>&1; then \
			echo "⚠️  WARNING: '$$tool' is missing on this workstation."; \
		else \
			echo "✅ $$tool is present."; \
		fi; \
	done

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

# Test suite: Dynamically discover and execute all unit tests under tests/
test: guard-setup ## Run the complete workstation test suite
	@echo "=== Running Workstation Test Suite ==="
	python3 -m unittest discover -v -s tests -p "test_*.py"
	@echo "✅ All unit tests passed successfully!"

