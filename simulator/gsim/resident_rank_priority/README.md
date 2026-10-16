# Resident rank priority

The production selector now reuses `firstIsResident` for resident-versus-fresh priority. The constructor-only `rankResidentPriority=false` retains the previous age-comparison equations for exact A/B qualification; no profile/OooParams field, state, queue capacity, read port, or pipeline cycle is added. Existing resident payload reuse remains gated by its original configuration.

For an eligible live resident, the unmodified first circular rank names it exactly when it precedes every fresh candidate. Empty pools, invalid/ineligible residents, holes, wraparound, and the sole-resident case follow directly. Issued residents cannot be reused. Full-token validity, selected-valid, and final launch authority are unchanged.

The predecoded head mask must match the binary head. This is an existing production invariant, not a new assumption: IntegerBackend initializes head to zero and advances it only by accepted commit count. RegisteredRobHeadMask initializes all ones and captures the next boundary on that same edge, holds on zero commits, wraps with the same ROB width, and asserts agreement every cycle. Recovery removes tails rather than changing head. OooParams requires a power-of-two ROB; production resident reuse is bounded to ROB16/PRF48.

## 2026-10-16 component evidence

- Shared Scala test compile passed; no full regression or Vivado run.
- ResidentLateExclusionGsim: 1,157,664 independent ordered-walk checks, comparing both head modes, old exclusion topology, exact previous priority equations, and the new equations. Stale/full-token, empty and issued cases covered; injected mismatch and illegal-issued negatives rejected.
- RegisteredHeadSelectionGsim: 65,536 masks, 4,101 wraps, II=1. Both resident variants are attached to the actual RegisteredRobHeadMask and checked on every cycle. Original independent host checks remain intact.
- Yosys SAT proves the explicit packed-output equality for arbitrary input bits; only headMask is derived from the arbitrary binary head. Simulation verification layers are disabled for conversion, but the output miter remains. Inverting the objective and independently flipping one candidate output bit both cause proof failure.
- Actual production selector, identical ports/head mode, Yosys `synth_xilinx -family xcup -flatten -noiopad -noclkbuf`: LUT 387 → 398, CARRY4 2 → 0, longest mapped-cell path 22 → 18. With matched `-nowidelut`: LUT 301 → 287, CARRY4 2 → 0, path 12 → 7. FF count is zero in both variants. The earlier xcu proxy gave identical counts.

This is a logic-topology improvement with a mapping-sensitive resource tradeoff, not a demonstrated area or Fmax improvement. Mapped-cell path length is not physical delay. No current routed timing, board result, or whole-CPU throughput speedup is claimed. The historical 223453b privilege/bare-mode path is a different revision and is not fixed or requalified by these component measurements.

## Reproduction

After sourcing scripts/cloud/env.sh, compile IonSoC.test once. Elaborate these mains using `mill -i IonSoC.test.runMain`:

- ooo.ResidentLateExclusionGsimMain OUTPUT/selector
- ooo.RegisteredHeadSelectionGsimMain OUTPUT/head
- ooo.ResidentPriorityAreaMain OUTPUT/old false
- ooo.ResidentPriorityAreaMain OUTPUT/new true

Generate the two FIR files with the pinned/repaired GSIM, compile their matching C++ drivers with ASan/UBSan, and run normal and negative modes. Export the selector FIR using firtool `--disable-all-randomization --strip-debug-info --disable-layers=Verification --verilog`. Convert with sv2v. Prove `io_equivalent=1` after `hierarchy -top ResidentLateExclusionGsim; proc; flatten; opt` using Yosys SAT. For mapping, convert both emitted production SV modules (CircularIssueSelector and ResidentMemoryPreparationSelector), then use the identical commands above, followed by `stat; ltp -noff`.

qualification.json records source and artifact hashes. The corrected end-to-end replay, raw artifacts and exact recovery-environment shell commands are in build/gsim/resident-rank-priority-r2. It reuses hash-identical elaborated inputs from r1 and reruns the focused GSIM, negative controls, explicit SAT and both xcup mappings successfully. The initial r1 verification-layer include failure is preserved in its checks.log. Registered-head integration is checked by GSIM and source invariants, not sequential SAT. Generated models are not committed.

### Portable source runner

`run.py` is the source-controlled end-to-end entry point. It never downloads tools. Supply installed GSIM, Yosys/ABC, sv2v, Clang 19+ and firtool executables; the surrounding environment must already provide their dependencies. Output must be a new directory. Without `--reuse-inputs`, Mill elaborates the four existing emitters above; `--mill` overrides its executable.

```
python3 simulator/gsim/resident_rank_priority/run.py \
  --gsim /path/to/gsim --yosys /path/to/yosys --sv2v /path/to/sv2v \
  --cxx /path/to/clang++-19 --firtool /path/to/firtool \
  --output build/gsim/resident-rank-priority-new
```

Optional `--reuse-inputs PRIOR_OUTPUT` requires its receipt.json to bind all nine current component/caller/test source hashes and all six reused FIR/SV file hashes. The runner checks inputs again after execution, records tool/runner hashes and exact commands, and writes PASS or FAIL receipts including output hashes. An output-directory conflict is rejected without altering that directory. A corrupted-input negative test verifies rejection before any simulation command.

The bounded recovery replay used the following command after sourcing scripts/cloud/env.sh and the restored prescreen env.sh (paths are invocation inputs, not baked into the runner):

```
python3 simulator/gsim/resident_rank_priority/run.py \
  --gsim ../recovery-gsim-r1/source/build/gsim/gsim \
  --yosys "$(command -v yosys)" --sv2v "$(command -v sv2v)" \
  --cxx "$GSIM_CXX" \
  --firtool simulator/build/cloud-env/cache/llvm-firtool/1.135.0/bin/firtool \
  --output build/gsim/resident-rank-priority-r4 \
  --reuse-inputs build/gsim/resident-rank-priority-r2
```

The initial portable r3 failed at C++ link because canonicalizing the clang++ symlink changed its invocation name to clang. The corrected runner preserves invocation names; its failure receipt is retained. No hardware or oracle change was made for this runner fix.
