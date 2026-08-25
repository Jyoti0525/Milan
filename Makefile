# Convenience wrapper around the engine CLI.
#
# The CLI is the real interface. This file exists so that "make eval" works
# for anyone who expects it; nothing in the project depends on make being
# installed, because it is not present on a default Windows install.

ENGINE := engine
WEB := web
SEED ?= 42
DIFFICULTY ?= realistic
ORDERS ?= 100

.PHONY: install generate recon eval sweep reproduce serve web web-install web-test test lint typecheck check check-web clean

install:
	cd $(ENGINE) && uv sync

generate:
	cd $(ENGINE) && uv run milan generate --seed $(SEED) --difficulty $(DIFFICULTY) --orders $(ORDERS)

recon:
	cd $(ENGINE) && uv run milan recon --seed $(SEED) --difficulty $(DIFFICULTY)

eval:
	cd $(ENGINE) && uv run milan eval --seed $(SEED) --difficulty $(DIFFICULTY)

sweep:
	cd $(ENGINE) && uv run milan sweep --seeds 20 --difficulty adversarial

reproduce:
	cd $(ENGINE) && uv run milan reproduce --seed $(SEED) --difficulty $(DIFFICULTY)

# The two halves of the exception queue. Run them in separate terminals.
serve:
	cd $(ENGINE) && uv run milan serve

web-install:
	cd $(WEB) && npm install

web:
	cd $(WEB) && npm run dev

web-test:
	cd $(WEB) && npx vitest run && npx tsc --noEmit && npm run lint

test:
	cd $(ENGINE) && uv run pytest

lint:
	cd $(ENGINE) && uv run ruff check . && uv run ruff format --check .

typecheck:
	cd $(ENGINE) && uv run mypy

check: lint typecheck test

check-web: web-test

clean:
	rm -rf data/runs
