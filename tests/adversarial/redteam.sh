#!/usr/bin/env bash
# The red team, in one command (ADR 0194).
#
#   tests/adversarial/redteam.sh          every attack, including the slow ones
#   tests/adversarial/redteam.sh -x       stop at the first control that failed
#
# Equivalent to `pytest -m adversarial`, which is the marker every test under
# tests/adversarial/ carries — applied by that directory's conftest rather than
# by hand, so a new module cannot forget it and quietly run less than the suite.
#
# Exit status is pytest's: 0 means every attack was refused AND every mutation
# showed its control to be load-bearing. A green run here is not "no attacks
# were tried"; each module asserts its own exploit is still viable before
# asserting the defence.
set -euo pipefail

cd "$(dirname "$0")/../.."
# `$PYTHON` for a venv that is not on PATH; `python3` because a POSIX box that
# has no `python` at all is the ordinary case now, and a red team that cannot
# be started is not a red team.
exec "${PYTHON:-$(command -v python || command -v python3)}" \
    -m pytest -m adversarial -q -p no:warnings "$@"
