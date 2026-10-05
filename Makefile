# chainlens development tasks.
#
# PYTHONPATH is deliberately emptied for every target.
#
# Rationale: a contributor's shell may have unrelated site-packages on
# PYTHONPATH — e.g. a sourced ROS 2 workspace, a conda env, another project's
# install tree. pytest auto-loads every `pytest11` entry point it can see, so
# those packages' plugins get loaded too and can break collection outright
# (ROS 2's `launch_testing` does exactly this). Clearing PYTHONPATH makes local
# runs behave identically to CI, where the environment is already clean.
#
# See CONTRIBUTING.md ("A clean PYTHONPATH").

export PYTHONPATH :=

.DEFAULT_GOAL := help

.PHONY: help sync lint format typecheck test test-cov check build clean

help:  ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

sync:  ## Install all dependency groups
	uv sync --all-groups

lint:  ## Lint and check formatting (no writes)
	uv run ruff check .
	uv run ruff format --check .

format:  ## Auto-fix lint and format in place
	uv run ruff check --fix .
	uv run ruff format .

typecheck:  ## Typecheck src and tests
	uv run mypy src tests

test:  ## Run the test suite with the network blocked
	uv run pytest --block-network

test-cov:  ## Run tests with coverage, enforcing the CI floor
	uv run pytest --block-network --cov --cov-report=term-missing --cov-fail-under=90

check: lint typecheck test-cov  ## Everything CI gates on

build:  ## Build wheel and sdist
	uv build

clean:  ## Remove build and tool caches
	rm -rf build dist site .pytest_cache .mypy_cache .ruff_cache .hypothesis htmlcov
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
