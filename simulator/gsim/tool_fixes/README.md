# Reconstructed GSIM emitter fixes

This patch is a new reconstruction against OpenXiangShan/gsim commit
`93b8cd23edd3228807c4f2a08c19c3936a463cb2`. It is not a byte-identical recovery
of the lost tool or its former eight-fixture/47-command certificate.

## Scope

- Preserve top-level input declared widths through used-bit reduction.
- Return Vec outputs as const references to physically padded arrays, including
  static const storage for constant-folded outputs.
- Accept Vec inputs by const reference, comparing/copying only logical lanes and
  applying successor activation once after any change. Padding is untouched.
- Initialize the half-open state byte interval `[_var_start, _var_end)` using
  `offsetof` and a standard-layout guard; preserve cycles, logging controls,
  activation, and the end sentinel. Random writes use byte-offset `memcpy`.
  The existing final zeroing behavior remains, including under `RANDOMIZE_INIT`.
  Generated masking references use `this->` to avoid local-name collisions.

## Apply and verify

Create a separate checkout at the exact pinned revision. Do not replace the
ordinary pinned tool or bypass its clean-source check.

1. Verify its HEAD is the revision above and its tracked source is clean.
2. Run `git apply --check /path/to/input-vector-init.patch`, then `git apply`.
3. Build with `make -j2 CXX=/path/to/clang++-19 build-gsim`.
4. Run `python3 test_fixes.py --gsim /path/to/checkout/build/gsim/gsim
   --cxx /path/to/clang++-19 --output /path/to/new-output-directory`.
5. In that checkout, run the small upstream emitter suite with
   `ASAN_OPTIONS=detect_leaks=0 make -j2 CXX=/path/to/clang++-19 TIME= fir-tests FIR_TEST_TIMEOUT=60`.

Clang 19 or newer is required. The focused runner uses ASan and UBSan. Its
fallback ASAN_OPTIONS disables leak checking because LeakSanitizer cannot run
under ptrace in the recovery executor; set ASAN_OPTIONS explicitly to override.
The output directory must be fresh, preventing stale generated translation units.
No full hardware, Linux, Vivado, or Verilator simulation is part of this check.

## Validation record

`reconstruction-validation.json` records the original reconstruction test result
and candidate binary hash. It is evidence of that tested build, not a promise
that future builds produce identical bytes. Six focused normal/random executions
passed, plus seven upstream FIR emissions and six corresponding runtime harnesses.
The Vec fixtures cover unsigned 1D/2D, signed 9-bit lanes, and 129-bit lanes.
The pristine negative control produced a narrowed 3-bit declaration and failed
byte-zero initialization. Source patch and test fixtures are the retained artifacts;
upstream source, generated models and binaries are intentionally not included here.
