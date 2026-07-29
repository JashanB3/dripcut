.PHONY: install dev test lint fmt type run clean

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

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache .mypy_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
