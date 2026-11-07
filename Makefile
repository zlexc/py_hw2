UV ?= uv

.PHONY: install run lint format-check test check build

install:
	$(UV) sync --locked

run:
	$(UV) run --locked database

lint:
	$(UV) run --locked ruff check .

format-check:
	$(UV) run --locked ruff format --check .

test:
	$(UV) run --locked python -m unittest discover -s tests -v

check: lint format-check test

build:
	$(UV) build
