# PMP assertion owner lifetime

This focused regression protects the existing assertion-lifetime repair. It does
not alter production sources, configure a default experiment, or run a CPU.

## Fast production-wiring contract

From the repository root:

```sh
mill -i IonSoC.test.testOnly ooo.PmpLifetimeSpec
```

The five pure Scala/elaboration tests inspect actual emitted
`FloatingPointMemoryPipeline` and `SvPageTableWalker` modules. The FP tests use the
static production A1 profile and the existing decoded-natural experimental
profile. Walkers cover all supported depths (3, 4 and 5) in both modes.

The tests expand expression graphs rather than count assertion text:

- The FP checker's reset is exactly `reset || !preparedValid`.
- Each walker checker's reset is exactly `reset || state != issue`. It cannot
  depend on request readiness, permission denial or handshake completion.
- Original natural-alignment and shared-eight-byte-beat predicates, clock and
  local reset enables match independent explicit expression contracts.
- The decoded bridge keeps all three original invariants for each of 16 active
  regions under the original reset, including while transaction owners are idle.
- The raw fixture does not sanitize address/size or gate permission outputs.
- Five owner-reset mutations (reset-only, constant disable, ready, denied and
  conditional connection) are rejected.

This is production owner **wiring and predicate** verification, not behavioral
execution of an entire FP pipeline or page-table walker. The restricted CHIRRTL
inspection deliberately fails on graph/format changes that need review.

## Optional tiny four-state controls

`PmpLifetimeContract` instantiates the real production PMP helper three times,
with raw payload inputs and held FP/walker owner inputs. It deliberately permits
invalid or unknown transactions that normal caller alignment would conceal.
The owner inputs represent a lifetime; they do not simulate readiness or a full
caller state machine. The production-wiring contract above is a separate gate.

Emit fresh fixtures to two new directories:

```sh
mill -i IonSoC.test.runMain ooo.PmpLifetimeContractMain /absolute/new-natural
mill -i IonSoC.test.runMain ooo.PmpLifetimeContractMain /absolute/new-decoded decoded
```

The existing, explicitly bounded Yosys four-state control path is retained only
for this stateless fixture. It is opt-in and is not a new general simulator
backend or part of any default Make target. GSIM remains the standard hardware
simulator. Two-state execution cannot establish the active-X result.

Supply existing installed tools explicitly. No discovery, installation, CPU
model, zero initialization or whole-design clock lowering is performed:

```sh
python3 simulator/qualification/pmp_lifetime/qualify_fixture.py \
  --natural-fir /absolute/new-natural/PmpLifetimeContract.fir \
  --decoded-fir /absolute/new-decoded/PmpLifetimeContract.fir \
  --firtool /installed/bin/firtool --sv2v /installed/bin/sv2v \
  --yosys /installed/bin/yosys --yosys-share /installed/share/yosys \
  --out /absolute/new-results --lock /absolute/RECOVERY_HEAVY.lock
```

The qualified tool versions are firtool 1.135.0, sv2v 0.0.13 and Yosys 0.52
(git fee39a3284c90249e1d9684cf6944ffbbcbb8f90)
(the exact binaries are hashed in each `INPUT_PINS.json`). A changed toolchain is
a new qualification lineage; successful parsing is not an equivalence claim.

The maintained `cases.json` has 20 cases:

- Ten positives: idle unknown, idle illegal, reset with live illegal inputs,
  each of three held owners allowed and denied, and decoded idle valid regions
  with unknown address/size.
- Ten negatives: each owner's active misalignment, oversize and unknown input,
  plus an idle malformed decoded region.

Each case has nine input samples, including reset and four clock rises. The
independent checker inspects original assertion A/EN/TRG immediately before the
edge, verifies the known natural/decoded predicates against arithmetic laws,
binds every observed input and reset/clock step to the declared case, and
requires the exact failing enabled original site in strict diagnostics.
Negative runs must exit 1; a crash, timeout or arbitrary nonzero exit does not
count. Active-X cases require an enabled unknown predicate, not just fail text.

Only unsupported diagnostic `else $error(...)` actions are removed. Original
assertions remain, passive observers preserve the original graph, and only
`$check` cells receive selective clock-check lowering. Unsupported assertion
shape/domain, non-stateless hardware, site topology or output reuse fails.
The runner holds the supplied exclusive lock, retains command/stdout/stderr
receipts, and enforces 512 MiB workspace / 1 GiB temporary-space floors, a 2 GiB
per-process RSS ceiling and a 120-second per-stage limit.

`RESULT.json`, tool/input hashes, original/adapted SV, raw/observed assertion
graphs, model, witnesses, strict logs and observed VCDs are generated outside
source control. Keep the source/class compile binding alongside them. This
fixture result is not a full CPU, ISA, FP, VM, DDR, board or timing qualification.
