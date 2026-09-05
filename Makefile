# aef-core — the green bar, and the measurement re-runner (ADR 0196).
#
# `make measure` re-derives every published measurement table from its
# COMMITTED raw data and diffs it against the ADR that publishes it. It makes
# zero live model calls: every runner it drives has a `--verify` mode that
# reads committed JSON/JSONL or replays a cassette with `on_miss="fail"`.
#
# It is RED on this tree, deliberately. ADR 0196 lists which rows and why —
# the loudest being ADR 0184's seed, whose drift ADR 0191 discovered a night
# late and used to withdraw S1c's +2.
#
# `make measure-ci` is what CI runs: it fails when the drift set CHANGES, not
# when it merely exists.

PY ?= python
PYTEST ?= pytest

.PHONY: help measure measure-fast measure-ci measure-list lint format-check typecheck test green

help:
	@echo "make measure       re-derive every published table and diff it against its ADR"
	@echo "make measure-fast  the CI subset (no cassette replays)"
	@echo "make measure-ci    fail only when the drift set changes"
	@echo "make measure-list  the registry, and what is not re-derivable"
	@echo "make green         lint + format-check + typecheck + test"

measure:
	PYTHONPATH=$(CURDIR) $(PY) docs/research/measure.py

measure-fast:
	PYTHONPATH=$(CURDIR) $(PY) docs/research/measure.py --fast

measure-ci:
	PYTHONPATH=$(CURDIR) $(PY) docs/research/measure.py --fast --against-expectations

measure-list:
	PYTHONPATH=$(CURDIR) $(PY) docs/research/measure.py --list

lint:
	ruff check .

format-check:
	ruff format --check aef tests examples

typecheck:
	mypy aef examples

test:
	$(PYTEST) -q

green: lint format-check typecheck test
