.PHONY: install dev test lint fmt type run api-dev web-install web-dev web-build clean

# tests/ is not written yet; wildcard keeps lint/fmt working either way.
SOURCES := src $(wildcard tests)

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check $(SOURCES)

fmt:
	ruff format $(SOURCES)

type:
	mypy src/dripcut

run:
	dripcut up

api-dev:
	DRIPCUT_API_RELOAD=1 python -m dripcut.api

web-install:
	cd web && npm install

web-dev:
	cd web && npm run dev

web-build:
	cd web && npm run build

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache .mypy_cache
	rm -rf web/dist
	find . -name __pycache__ -type d -exec rm -rf {} +
