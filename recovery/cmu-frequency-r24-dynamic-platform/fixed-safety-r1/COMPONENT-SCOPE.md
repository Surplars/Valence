# FixedClockSafetyGuard isolated Icarus regression

## Latest result

The source-bound archived `receipt.json` is PASS: 16 positive component scenarios and 4 expected-failing negative controls. Each VVP case finished in at most 0.011 seconds in this run. Every process is bounded to 30 seconds and reaped. The receipt records exact command lines, exit status, wall time, timeout status, log hashes, source/RTL hashes, test hashes, compiler/runtime hashes, and original compiler/runtime version output. No Mill or Verilator was invoked.

The test instantiates the actual emitted `FixedClockSafetyGuard` plus `CdcMailbox_40`, `CdcMailbox_41`, `CdcLevel`, and `CdcResetRelease` from platform-r2. The runner verifies the three owning Scala files and all five emitted SV files against `platform-r2-emission.json` before copying SV into `results/frozen-rtl`. It compiles that frozen copy with a snapshotted testbench, then verifies source and RTL hashes again after the simulations. The matching guard source SHA-256 is `9e05fd8cb26095fb5a4bfb1b157ca5ce5537d8aebeb7943f814cc54efbcd492e`; guard SV is `270d0119353b977a4dce5c70e975aefc8ef5bbd984384f09557ba5c5c7320c79`.

## Reproduce

From the repository root, with the original source-bound r2 emission available:

    python3 simulator/cdc/run_fixed_clock_safety.py --repo . --out out/cmu-frequency-r24/fixed-safety-recheck

Optional `--rtl` and `--emission` paths must refer to corresponding emitted artifacts. The runner deliberately refuses source or emitted-RTL drift rather than silently testing stale RTL. It expects the checkout's sibling `native-tools` installation and the pinned mailbox module names from this emission.

## Positive scenarios

1. `arm_exact`: epoch 0x1234 arm and disarm with exact receipt tag, enable and guarded fields.
2. `backpressure`: stop fixed clock with an accepted command, hold a second AON command for 12 stalled AON edges, retain the first receipt for 13 stalled AON edges, then drain all four receipts in order across two epochs.
3. `unsafe_arm`: unsafe initial arm returns guarded=false without fault; matching disarm releases its owner; a later safe epoch succeeds.
4. `arm_just_raised`: safe rises immediately before fixed arm consumption, but the prior fixed sample was unsafe; guarded remains false.
5. `arm_just_revoked`: safe falls immediately before fixed arm consumption despite its previous safe sample; guarded remains false.
6. `brief_revoke`: safe is low for exactly one fixed rising edge and zero AON rising edges; the source fault still reaches AON and remains sticky after safe recovery. A later AON-accepted command remains blocked at fixed consumption.
7. `disarm_then_change`: change safe after observed fixed disarm consumption while holding its AON receipt; no fault.
8. `disarm_at_change`: matching disarm and unsafe sample coincide at the same fixed consumption edge; no fault.
9. `wrong_epoch`: mismatched disarm returns an exact unguarded receipt and sticky fault; later fixed consumption is blocked.
10. `duplicate_active`: repeated arm epoch while owned fails closed.
11. `duplicate_retired`: replay of an already retired epoch fails closed.
12. `zero_epoch`: reserved epoch zero arm fails closed.
13. `reset_command`: cold reset while fixed is paused, with one accepted command owner and another input command backpressured; owners clear asynchronously and epoch 1 works again.
14. `reset_receipt`: cold reset a held receipt and active owner while fixed is paused; owners clear asynchronously and epoch 1 works again.
15. `reset_fault`: cold reset a sticky fault and later blocked request while fixed is paused; fault and ownership clear, then epoch 1 works again.
16. `pause_receipt`: stop fixed while an arm receipt is held at AON; receipt and owner remain stable; AON consumes once while fixed stays stopped; resume and disarm cleanly.

## Checkers and negative controls

The scoreboard records actual AON command handshakes and test-intended receipt fields. Fixed mailbox destination consumption must match accepted commands exactly, and AON receipt consumption must match both accepted and fixed-consumed counts. Held command and held receipt payloads must remain stable. A small source-side ownership/window model requires the sticky AON fault no later than the third AON sampling edge after source failure, allowing the actual two-flop CDC latency. Reset cancels outstanding expectations explicitly; ordinary successful drains require exact conservation. Fail-closed scenarios permit exactly one explicitly tested AON-accepted but fixed-blocked command, not arbitrary missing receipts.

Hierarchy is used to observe the fixed mailbox consumption boundary, verify asynchronously reset owner/toggle/token/synchronizer registers, and assert fixed owner state where no equivalent public output exists. No DUT signal is forced or modified.

All four negative controls run the same scenarios and ordinary checker paths as positive tests. They only corrupt observations presented to those checkers:

- `negative_tag`: XOR a receipt epoch bit. Actual result: ordinary `FAIL_TAG` assertion, exit 1.
- `negative_guarded`: invert receipt guarded. Actual result: ordinary `FAIL_WINDOW guarded` assertion, exit 1.
- `negative_drop_receipt`: hide observed receipt valid while allowing the real transfers. Actual result: ordinary final `FAIL_CONSERVATION`, with accepted=2, consumed=2, returned=0, exit 1.
- `negative_fault`: hide observed sticky fault during brief revocation. Actual result: ordinary `FAIL_WINDOW fault` at source-failure age 3, exit 1.

The runner requires each negative's named assertion, nonzero exit, and absence of PASS. A timeout, simulator crash, unrelated assertion, or unconditional failure cannot satisfy it.

## Scope and limitations

This is an isolated 16-bit guard/CDC component simulation with independent 34 ns AON and 10 ns fixed clocks and a phase offset. It is not a dynamic-platform end-to-end regression, physical MMCM validation, metastability proof, implementation/timing-closure result, or production-frequency whitelist qualification. Synthesis, physical bundled-data delay constraints, and broader integration are outside this test.

The earlier `results-icarus-string-rejected` and `results-icarus-case-string-rejected` directories preserve raw simulator failures from initial testbench draft attempts using Icarus-unsupported dynamic-string constructs. They were not DUT failures or accepted negative controls. The final bench uses packed command-line strings and numeric injection mode. `results-initial-green` and `results-expanded-green` retain earlier successful iterations; `results/` is the final source-bound run. No repository sources, index, HEAD, build outputs, remote, or user computer were modified by this work.

Archive note: original frozen emitted SV and binaries remain under the local out/cmu-frequency-r24/fixed-safety-r1 run directory, not in Git. Reproduction uses the source/RTL/tool hashes in this receipt; generated RTL and simulator binaries are intentionally not committed. The shared-repository runner rejects output-directory reuse.
