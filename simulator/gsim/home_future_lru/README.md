# Future Home reservation and STORE-PF LRU experiment

The explicit 54-option profile adds `--future-home-way-reservation` and the
existing `--store-prefetch-lru-victim` to the retained default52 vector. Generic
defaults remain false. Eager-prefix selection remains off. Default52, MAC T1,
USER2, the original independent oracles, and the repaired entry checks remain
in place. This source change does not change an existing physical task's pin.

The Home can reserve the future directory slot of an already captured dirty C
release. The existing full-PA release veto remains; ordinary free ways retain
priority. Grant/E is eligible only after the accepted last C beat retires the
old owned responsibility. A late old ReleaseAck retires only that old release
responsibility and must not clear the new owner.
The `futurePaired` alias assertion alone is not a responsibility proof: that
comes from the independent accepted A/C/E/ACK ledger, first-C exclusion of an
active directory, and directed fast-return/late-ACK checks.

The measured original-law inclusive totals are 184,438 cycles in Sv39 and
172,283 in Bare (64 KiB COPY twice, 100 MHz). Against retained default52,
191,618/194,153 becomes 184,438/172,283 (Sv39/Bare), or +3.8929%/+12.6942%
inclusive throughput. Relative to future-only, Sv39 is
unchanged and Bare saves 17,026 cycles; Bare eliminates 670 excess source read
bursts while retaining the write counts. The second whole-burst service law is
separate: Sv39 is 175,977 ROI + 8,240 cleanup = 184,217, unchanged by LRU. No
second-law Bare result is claimed. Both original-law cases retain all 105
result fields, the original read/memory/trap negative anchors, and independent
victim-policy/history mutation failures. Two short physical M-mode NEMU cases
and their three controls passed on the same 37 DUT objects.

The matched native comparisons contain 239 modules: future reservation changes
only Home; enabling LRU then changes only the private cache. They add no declared
state or ports. The Home adds nine-bit directory comparisons, an ordinary-way
priority mux, and Grant-mask logic. Those combinational costs are not mapped
area or timing results. No STA, mapped resource, MAC/DMA pressure, or board
execution result is claimed.

## Source and evidence identity

`source-bridge.json` records each current-to-b1bb source substitution and exact
production/Scala closure hashes. All production and Scala fixtures are the
actually tested bytes. The exporter change reapplies the tested flag plumbing
to the repaired b1bb entry. The strict host bridge is copied exactly and reuses
the existing independent policy oracle and complete result contract.

The default-OFF correspondence is bounded: original Home CHIRRTL matches after
two verified queue-module-name substitutions and removal of three proven unused
false `futurePaired` lines. Four comparator mutations were rejected. Raw native
identity is false. No new-source default52 CPU run or full-board OFF run is
claimed. Old qualification receipts remain unchanged and identify their old
source; hash projection is only an explicit source-identity bridge.

`evidence.json` contains minimal result fields, relative host-source hashes, and
hashes/Library references for private complete evidence. The initial memory
negative failure remains in that evidence; the repaired strict host reaches the
original final-memory mismatch anchor. Models, compiler/header inventories,
full receipts, logs, and historical reports are external to this source change.

## Recheck without compiling or running hardware

From the repository root:

```
python3 fpga/next/board_final.py --output build/default52-check
python3 fpga/next/board_home_future_lru.py --output build/future-lru-check
python3 fpga/next/test_board_entry_contract.py
python3 simulator/gsim/home_future_lru/run_saved.py
```

Both board commands are preflights unless `--emit` is explicitly supplied; they
create no output. The experimental entry's `--emit` uses the native exporter
and inherited staging checks, never synthesis or implementation.

Restore both private archives listed in `evidence.json` into one directory.
Their common `home-future-lru-r1` directory can be anywhere:

```
python3 simulator/gsim/home_future_lru/run_saved.py --evidence RESTORED/home-future-lru-r1
```

This verifies the saved actual constructor/configuration, model and strict host
hashes, recaptures the original independent results, and checks the original
negative anchors. To deliberately rerun only the two original-law cases and
five controls using the saved compatible-host executable, add `--rerun --output
NEW_DIRECTORY --activation QUALIFIED_ACTIVATE_SH`. The activation script must
match the qualified private receipt, and ASan uses the original `detect_leaks=0`.
Restoring files alone does not establish a compatible runtime environment. This
is a saved-binary/object identity check and explicit replay, not a fresh-build
runner. It does not rebuild or relink a DUT. That portable replay command
was source-reviewed here; the saved original execution is the qualification.
