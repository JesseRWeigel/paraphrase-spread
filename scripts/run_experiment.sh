#!/usr/bin/env bash
# Run the whole measurement, in an order chosen so an interruption still leaves a usable result.
#
# Every phase is resumable: the runner reads what is already on disk and asks the model only for
# what is missing, so re-running this after a crash costs only the missing calls. The GPU on this
# machine is shared with other work, so that property matters more than speed.
#
# Models are run one at a time and unloaded afterwards, because two of these plus whatever else
# holds the card does not fit in 32 GB, and a server that is swapping models between requests is
# slower than one that is not.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

WORKERS="${WORKERS:-3}"
PRIMARY="${PRIMARY:-qwen3:8b}"
SECOND="${SECOND:-qwen3.5:9b}"
THIRD="${THIRD:-gemma4:e4b}"

run() { echo; echo "### $*"; "$@"; }

# 1. The primary task on the primary model, which is the headline result.
run python3 -m pspread.cli run --task mult --model "$PRIMARY" --workers "$WORKERS"

# 2. How much determinism temperature 0 actually buys, measured rather than assumed.
run python3 -m pspread.cli repeat --task mult --model "$PRIMARY" --sample 200
run python3 -m pspread.cli run --task mult --model "$PRIMARY" --workers "$WORKERS" --unload

# 3. The second task on the same model, to check the spread is not an arithmetic quirk.
run python3 -m pspread.cli run --task entail --model "$PRIMARY" --workers "$WORKERS" --unload

# 4. Two more models on the primary task, to check it is not one model's quirk either.
run python3 -m pspread.cli run --task mult --model "$SECOND" --workers "$WORKERS" --unload
run python3 -m pspread.cli run --task mult --model "$THIRD" --workers "$WORKERS" --unload

run python3 -m pspread.cli analyze
run python3 scripts/build_docs.py
