# Workspace-local cloud engineering environment

This setup is for the Debian 13 amd64 dot cloud computer. It keeps tools, downloaded
packages, caches and logs under the ignored `simulator/build/cloud-env/` directory.
It does not install system packages, alter network/security settings, invoke Vivado,
or install or invoke Verilator. The current two-issue design remains unchanged.

## Recreate and activate

The host supplies Python 3, curl, Git, Make, dpkg-deb, a bootstrap Java 21 runtime,
GCC/G++ 14.2, GMP/zlib headers and libraries, LLVM 19's shared library and its system
dependencies. The pinned Debian packages in `downloads.lock.json` supply Clang
19.1.7, sanitizer libraries, Flex 2.6.4, Bison 3.8.2, M4 1.4.19, and RISC-V GCC
14.2.0/binutils 2.44. The Mill launcher is 1.1.7, matching `.mill-version`.
Mill resolves Azul JDK 21.0.10; its archive is also SHA-256 locked and preloaded.

```bash
python3 scripts/cloud/bootstrap.py
source scripts/cloud/env.sh
make gsim-setup
make compile
make gsim-smoke
```

Only official Debian/Maven Central/Azul and upstream GitHub sources are used. Every
explicitly downloaded artifact is hash checked before use; NEMU's two layout
resources additionally match the repository's `reference-lock.json` hashes. Those
resource URLs use their upstream default branches, so a future upstream change
fails closed instead of accepting new contents. GSIM and NEMU Git revisions remain
controlled by the repository lock files. No upstream CPU/example submodules are
cloned by GSIM setup. NEMU's isolated build uses `git_commit=` to prevent upstream
Make from auto-committing in the parent checkout.

The activation script places all caches in the workspace and caps Java heap at
4 GiB, Java active processors and GSIM build jobs at 2. It adapts Java to the
executor-provided HTTP proxy and uses the executor's existing Java CA bundle.
It neither adds certificates nor disables TLS validation. Re-source it in each new
execution command because executor proxy endpoints are per-command settings.

## Baseline and focused verification

Do not run `make test`, `make regress`, full GSIM, long Linux simulation or Vivado
as part of this environment check. The repository's current workflow requires a
single compiled candidate followed by only short affected checks.

The deployment baseline is repository commit
`c54220afb7ee81d99913963042c2eeef35ca97a5`.
Current logs are in `simulator/build/cloud-env/logs/`; pinned tool and NEMU receipts
are in `build/gsim/toolchain-used.json` and `build/gsim/reference-used.json`.
The baseline compiler and GSIM smoke have passed, including ASan/UBSan.
The four instruction-permission models passed 216 original positive cases and
four exact independent mismatch rejections. Their source/artifact hashes and
per-variant logs are frozen in
`build/gsim/cloud-baseline-20261007/instruction-permission-receipt.json`.

The frozen baseline main/test sources and instruction-permission driver are in
`build/gsim/cloud-baseline-20261007/baseline-sources.tar`, with a SHA-256 sidecar.
Generated models are build outputs and are not committed.

Use existing Make targets or the inspected `simulator/gsim/run.py` helper for
focused models. Do not reuse a generated model across an RTL change; preserve
baseline models and rebuild the candidate under a fresh tag. Compiler/sanitizer
smoke does not prove RTL correctness. GSIM functional checks do not prove routed
FPGA timing, physical DDR capacity, board behavior or formal CoreMark performance.

To regenerate the adapter baseline in a new clean checkout, run
`python3 -B scripts/cloud/verify_instruction_baseline.py` after activation. It
refuses to overwrite its completed receipt. The board integration baseline uses
`python3 -B simulator/gsim/rv64gc_board.py --tag cloud-baseline-20261007 --profile staged-fetch-feedback`;
the runner requires a fresh tag and independently rejects a wrong ISA anchor.

The board baseline passed at 32,326 model cycles with 32 FPR context registers,
one S-mode ECALL, two compressed advances and 49 DDR reads, including its exact
wrong-anchor negative control. Receipt:
`build/gsim/rv64gc-board-cloud-baseline-20261007/receipt.json`.
This is a short hardware context check, not a Linux or physical-board result.
The environment summary and evidence hashes are in
`simulator/build/cloud-env/deployment-receipt.json`. NEMU was built but a CPU
NEMU differential workload was not run during this focused environment check.
