# Full-CPU page-sweep fixture (existing models only)

This fixture links a small host against **existing** `BoardSocGsim*.o` files. It never elaborates, compiles, synthesizes, or modifies the DUT. Keep guest, host binaries, and logs outside this source directory. GNU RISC-V tools, the matching model compiler/runtime, and the repository's existing `simulator/gsim/combined_board_bandwidth/host` libraries are required.

## Run

All environment-specific inputs are explicit. `--repo-root` defaults to the repository containing this script; the model is always selected with `--model`. Flags are a JSON array or a receipt containing `host_flags`. `reference-host-flags.json` records the flags of the qualified 50cb CPU/fabric profile; it is not a promise that arbitrary model objects are compatible.

```
python3 run.py guests --cross-prefix riscv64-unknown-elf- --output /tmp/sweep-guests
python3 run.py link --repo-root /path/to/repo --model /path/to/existing-model --cxx clang++-19 --host-flags reference-host-flags.json --guests /tmp/sweep-guests --output /tmp/sweep-host
python3 run.py run --guests /tmp/sweep-guests --binary-dir /tmp/sweep-host --expect-l2 64 --output /tmp/sweep-results
```

For the matched old D16 model, link to a separate output directory and run with `--expect-l2 0`. Use the **same generated guest directory** for both arms. Compare `rows[*].result` cycles, PC hash, retired/load/store counts and `pass.checksum` between result files. `run` verifies independent expected memory counts, warm PTW/L2/cache/DDR counts, and three negative controls per arm. It covers only READ16/17/32, not COPY or a full production diagnostic matrix.

`guests` assembles the positive guest and a bad-stride negative, generates ROI symbol headers from the resulting ELF, and requires matching marker positions. `link` verifies guest hashes, binds against the supplied model's actual generated header, rejects shadow headers, and records all reused object hashes. No generated header or large binary is shipped. The D-service state field must exist in the selected model; its source-verified encoding is idle=0, walking=1, replying=2, probe1=3, probe0=4. Observed transitions into 1 count PTW entries; 3→2 counts an L2 hit. An incompatible observation schema must be requalified rather than silently remapped.

## Measured reference and scope

The matched reference uses old 50cb0c5d4b17318904d6cf818ad23829821d5d93 full-CPU/fabric objects versus I8/D16 with a 64-entry D-side L2. Both run actual S-mode Sv39 with ordinary 4KiB data leaves. Source addresses are `n * 4160` bytes, one eight-byte word per page, matching production `selected_word(n,1)=n*512+n*8` and avoiding pure-4KiB cache-set alias. The source pattern matches the production diagnostic; one warmup pass precedes 128 timed passes.

| READ pages | Old cycles | L2 cycles | Old→L2 warm PTW | L2 hits | Old→L2 DDR AR |
|---:|---:|---:|---:|---:|---:|
| 16 | 12052 | 12052 | 0→0 | 0 | 0→0 |
| 17 | 131716 | 28934 | 2176→0 | 2176 | 2176→0 |
| 32 | 247300 | 53894 | 4096→0 | 4096 | 4096→0 |

All six warm ROIs have zero cache read/write miss events. Useful eight-byte/load throughput, **model-cycle conversion at 100MHz**, is 129.646532→129.646532, 12.604059→57.377350, and 12.636474→57.984191 MiB/s. These are not full-page transfer rates or board measurements. Each repeated baseline walk here causes one DDR read, not three: the retained upper-PTE cache avoids repeated upper-level requests.

Cold boot/control plus one-pass warmup time-to-ROI is 2663→2693, 2770→2802, and 4380→4440 cycles. Both arms have respectively 16/17/32 cold D-walk entries, 47/49/79 cold DDR AR, and 17/18/33 cold cache read misses. This cold region excludes host-seeded initialization and is not a separately timed cold-only production kernel. Detailed reference counters and source hashes are in `reference-results.json`.

The guest is controlled scalar **assembly**, assembled in the reference with GCC14.2.0+19. It is not production `mmu_diagnostic.c` or the user's GCC13.2 binary. Loop scheduling and initialization differ, so the fixture isolates the capacity cliff rather than predicting exact production C or board throughput.

Correctness checks retain the full-token ownership/data scoreboard, expected checksum store, architectural load/store counts, drained physical/DDR owners, and S-mode ECALL. Both arms reject inverted read-data expectations, incorrect total-load counts, and a 4168-byte bad-stride guest with unchanged load counts but incorrect data selection. The packaged entry point was syntax-checked and rebuilt both guest variants byte-identically to the executed reference; no DUT or performance rerun was performed during packaging.
