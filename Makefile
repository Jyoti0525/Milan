# Convenience wrapper around the engine CLI.
#
# The CLI is the real interface. This file exists so that "make eval" works
# for anyone who expects it; nothing in the project depends on make being
# installed, because it is not present on a default Windows install.

ENGINE := engine
SEED ?= 42
DIFFICULTY ?= realistic
ORDERS ?= 100

.PHONY: install generate recon eval reproduce test lint typecheck check clean

install:
	cd $(ENGINE) && uv sync

generate:
	cd $(ENGINE) && uv run milan generate --seed $(SEED) --difficulty $(DIFFICULTY) --orders $(ORDERS)

recon:
	cd $(ENGINE) && uv run milan recon --seed $(SEED) --difficulty $(DIFFICULTY)

eval:
	cd $(ENGINE) && uv run milan eval --seed $(SEED) --difficulty $(DIFFICULTY)

reproduce:
	cd $(ENGINE) && uv run milan reproduce --seed $(SEED) --difficulty $(DIFFICULTY)

test:
	cd $(ENGINE) && uv run pytest

lint:
	cd $(ENGINE) && uv run ruff check . && uv run ruff format --check .

typecheck:
	cd $(ENGINE) && uv run mypy

check: lint typecheck test

clean:
	rm -rf data/runs
