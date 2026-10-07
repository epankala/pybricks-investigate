PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
STAMP := $(VENV)/.installed
TOOL := $(BIN)/pybricks-investigate

# Hub program for run/compile, e.g. make run PROGRAM=hub/mine.py
PROGRAM ?= hub/example.py
# Hub Bluetooth name (default: first Pybricks hub found), e.g. make scan HUB="Pybricks Hub"
HUB ?=
# Extra tool options, e.g. make run ARGS="--debug -t"
ARGS ?=
HUB_ARGS := $(if $(HUB),--hub-name '$(HUB)') $(ARGS)
IMAGE := build/$(basename $(notdir $(PROGRAM))).bin

# `make sync` mirrors this directory to $(REMOTE):$(REMOTE_DIR)/pybricks-investigate/.
# The remote .venv and build output are machine-local and left untouched.
REMOTE ?= 192.168.50.178
REMOTE_DIR ?= work/lego/pybricks_projects
RSYNC_EXCLUDES := --exclude=/.venv/ --exclude=/build/ --exclude=__pycache__/ \
	--exclude=.pytest_cache/ --exclude=.ruff_cache/ --exclude=*.egg-info/
RSYNC := rsync -az --delete $(RSYNC_EXCLUDES) ./ $(REMOTE):$(REMOTE_DIR)/$(notdir $(CURDIR))/

.DEFAULT_GOAL := help

.PHONY: help install scan watch run compile stop test lint format check sync sync-dry clean distclean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

$(BIN)/python:
	$(PYTHON) -m venv $(VENV)

$(STAMP): pyproject.toml | $(BIN)/python
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e '.[dev]'
	touch $@

install: $(STAMP) ## Create the venv and install the tool (editable) with dev tools

scan: $(STAMP) ## Report the hub and the devices on its ports
	$(TOOL) scan $(HUB_ARGS)

watch: $(STAMP) ## Scan, then keep reporting plug/unplug and value changes (Ctrl-C stops)
	$(TOOL) scan --watch $(HUB_ARGS)

run: $(STAMP) ## Upload and run PROGRAM, printing its output until it ends (Ctrl-C stops)
	$(TOOL) run $(HUB_ARGS) $(PROGRAM)

$(IMAGE): $(PROGRAM) $(STAMP)
	$(TOOL) compile $(PROGRAM) -o $@

compile: $(IMAGE) ## Compile PROGRAM into build/<name>.bin locally (no hub needed)

stop: $(STAMP) ## Stop the program running on the hub
	$(TOOL) stop $(HUB_ARGS)

test: $(STAMP) ## Run unit tests (incl. simulated scan program)
	$(BIN)/pytest

lint: $(STAMP) ## Lint and check formatting
	$(BIN)/ruff check src hub tests
	$(BIN)/ruff format --check src hub tests

format: $(STAMP) ## Auto-format and fix lint issues
	$(BIN)/ruff format src hub tests
	$(BIN)/ruff check --fix src hub tests

check: lint test compile ## Run all checks

sync: ## Mirror the project (incl. .git) to REMOTE:REMOTE_DIR/pybricks-investigate (deletes stale remote files)
	$(RSYNC) --itemize-changes

sync-dry: ## Show what `make sync` would change, without changing anything
	$(RSYNC) --itemize-changes --dry-run

clean: ## Remove build artifacts and caches
	rm -rf build dist .pytest_cache .ruff_cache src/*.egg-info
	find . -path ./$(VENV) -prune -o -name __pycache__ -type d -exec rm -rf {} +

distclean: clean ## Also remove the virtualenv
	rm -rf $(VENV)
