# Optional context-prefetch CPU observer harness

These are portable source copies of the three audited fixed M/Bare hosts, not a default-on policy and not a general OS speculative-authorization proof. The cache README covers the smaller affected-component suite. The experiment's result report records both traffic reductions and performance regressions.

## Source and generated-model binding

`cpu/{common,dependent,independent}.cpp` retain the original guest/service/ISA oracle. Their only migration change is the include path for `shared/benchmark_oracle.h`. Main provenance and transport headers are byte-identical to the qualified versions. Existing repository harness headers `gsim_model_storage.h`, `isa_model.h`, and `muldiv_model.h` are dependencies, not replaced or forked.

The observer intentionally reads private generated members. **A matching member name or width is not sufficient ABI qualification.** The copied `prefetch_audit_frame.h` uses `_T_60` for the actual `(prefetchWrite | demandWrite)` bank-write enable. This is the reviewed last-stale generated epoch, not a promise that a different GSIM version or RTL edit retains `_T_60` semantics. Requalify all 188 observations, current/NEXT phase, array read/write order, full-owner tokens and the 105 business aliases before using a newly generated model.

Recorded generated model SHA-256:

- `ContextFetchPrefetchBenchmarkGsim0.cpp`: `627d7f17e457e7d9e3d198624efb269b201602f84c6f09513b9c838fa3f015fb`
- `ContextFetchPrefetchBenchmarkGsim.h`: `39acb93a1464d6aab487d35289736dcd9f38a73a03063c6d9a40f11bd58a3a59`

Use the project's supported GSIM flow and qualified initialization-byte-span fix; Verilator is not supported. CPU emitter is `soc.core.ooo.ContextFetchPrefetchBenchmarkGsimMain`, top `ContextFetchPrefetchBenchmarkGsim`. Generated files and objects belong in a fresh build directory, not in this tracked source directory. Compile the whole object once, then reuse it across hosts. Never reuse a receipt for a different source/tool epoch.

## Host build recipe

After actual generated-model API/phase qualification, set `REPO` to the checkout, `MODEL` to its generated model directory, `OBJECT` to the matching one-time compiled model object, `OUT` to a fresh output directory, and `CXX` to the qualified Clang. These are commands, not a claim that arbitrary compilers/models were validated:

```sh
H="$REPO/simulator/gsim/harness/context_fetch_prefetch"
mkdir "$OUT"
for host in common dependent independent; do
  "$CXX" -std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all \
    -I"$H/cpu" -I"$H/aliases" -I"$MODEL" -I"$REPO/simulator/gsim/harness" \
    -c "$H/cpu/$host.cpp" -o "$OUT/$host.o" || exit
  "$CXX" -fsanitize=address,undefined "$OUT/$host.o" "$OBJECT" -ldl -o "$OUT/$host" || exit
done
```

Each host accepts `ELF SYMBOLS MODE CYCLE_BUDGET`; use `common` with `smoke 100000`, `performance 3000000`, or `validation 3000000`; use dependent/independent with `dependent-load 10000` / `independent-load 10000`. Positive acceptance requires the original business PASS, `CPU_PREFETCH_AUDIT_PASS`, exit 0, empty stderr and no sanitizer failure. Keep the original memory service and backing-data oracle. Limit execution resources separately (the recorded run used 2 CPUs, sampled 4 GiB RSS and bounded wall time); these bare recipe commands do not implement that guard. Do not count a path-migration smoke as a new performance sample.

## Guest inputs and reproducibility limits

`payloads/pinned-inputs.json` records exact ELF/symbol hashes used in the historical matched comparison. `payloads/dependent` and `payloads/independent` contain the original assembly/linker scripts. Common start/smoke code, linker script, CoreMark port and native CRC checker are in `payloads/common`.

CoreMark algorithm sources are external: <https://github.com/eembc/coremark.git>, revision `1f483d5b8316753a742cbf5590caf5bd0a4e4777`. Verify **all six source hashes** in `pinned-inputs.json` before building. No algorithm source is silently substituted. Respect its upstream license. The recipe uses one iteration/2000-byte data and is **not an official CoreMark score**.

Set `RISCV` to the RISC-V GCC/binutils prefix (for example `riscv64-unknown-elf-`), `COREMARK` to that verified source checkout and `GUEST_OUT` to a new directory. The original common build flags were:

```sh
COMMON="$H/payloads/common"
FLAGS='-O2 -march=rv64im_zicsr -mabi=lp64 -mcmodel=medany -mno-relax -msmall-data-limit=0 -ffreestanding -fno-builtin -fno-stack-protector -ffunction-sections -fdata-sections -nostdlib -nostartfiles -Wl,--gc-sections -Wl,--no-relax -Wl,--build-id=none'
mkdir "$GUEST_OUT"
"${RISCV}gcc" $FLAGS -T "$COMMON/link.ld" "$COMMON/start.S" "$COMMON/smoke_main.S" -o "$GUEST_OUT/smoke.elf"
for pair in performance:0 validation:13333; do
  mode=${pair%:*}; seed=${pair#*:}
  "${RISCV}gcc" $FLAGS -DBENCH_SEED="$seed" -I"$COMMON/port" -I"$COREMARK" \
    -T "$COMMON/link.ld" "$COMMON/start.S" "$COMMON/port/core_portme.c" \
    "$COREMARK/core_main.c" "$COREMARK/core_list_join.c" "$COREMARK/core_matrix.c" \
    "$COREMARK/core_state.c" "$COREMARK/core_util.c" -lgcc -o "$GUEST_OUT/$mode.elf" || exit
done
for mode in smoke performance validation; do
  "${RISCV}nm" -n "$GUEST_OUT/$mode.elf" > "$GUEST_OUT/$mode.symbols.txt" || exit
done
```

The supplied assembly/linker pairs also permit rebuilding the two load guests with RV64IM/Zicsr, LP64, no compressed instructions or relaxation, freestanding linking, and sorted `nm` symbols. **Exact toolchain identity and output hashes matter:** this postseal portable recipe has not independently rebuilt all five matching payloads. If hashes differ, do not relabel them as the matched historical inputs; identify the toolchain/source difference and requalify. Keep native CRC checking and the exact host architectural checks; reproducing only a terminal marker is insufficient.
