# R6 publication, LSU and fetch candidate

Candidate for review: the supplementary actual backend reserve observation has been checked. This document and the R6 input checker do not authorize implementation or claim timing closure.

## Source and scope

The eight changed production leaves, all under `src/main/scala/core/ooo`, are:
- IntegerBackend.scala
- PendingVirtualStoreProof.scala
- ParallelLoadStoreUnit.scala
- LoadStoreUnit.scala
- InstructionLineCache.scala
- InstructionTileLinkBridge.scala
- InstructionTranslationAdapter.scala
- RegisteredFetchPacket.scala

The batch combines flush-independent intrinsic prepared-load admission with the original final grant, response-state-only tagged LSU handling, and accepted fetch payload/address selection. Generic LSU behavior remains the default. Parameters remain the complete ordered 73-option contract, 177 core fields and 94 profile fields: 100 MHz, issue width 2, ROB16, PRF48 and LSU4. No reset candidate is included.

The independently compiled input closure has 3207 files. This is a compiled-source identity, **not the complete published repository identity**. The published R5 baseline also has five R5 adapter files absent from that build input snapshot. Preserve those five existing files and their old pins; apply this batch as a delta to the published tree. Add these four R6 review files separately. Do not replace the repository with the compiled-input directory. The R6 checker verifies every frozen input byte and clearly reports subset scope; it does not qualify arbitrary added code or invoke an old R5 launcher.

## Results and limitations

The combined real Parallel component passed its positive and 12 reached/rejected controls, including canonical handoff, flush with error/pagefault/cancel, and candidate/strict admission differences. One newly generated whole-CPU model passed seven positives and eight controls. All positive stdout/TSV files matched the preceding exact73 baseline byte-for-byte. COPY inclusive cycle counts are Bare179571 and Sv39191618. Held causal observation remained capture780, next-cycle accept781, owner14:49 to15:50.

The actual backend prepared-younger-load/head-system-reserve conjunction was not reached by those existing guests. Its supplementary directed observation is reported separately below. Stronger held rollback/reuse remains incomplete. No raw-media PHY claim follows from GSIM. The new native emission has 304 files; nine SV files differ, including one generic-LSU local wire rename. SV text size is not LUT area. Routed timing, utilization and board operation are unqualified.

## Reproduction entry points

Use the pinned project Scala/Chisel plugin, firtool, GSIM and C++ sanitizer toolchain. Compile the batch once. A fresh checkout may use the existing Mill entry; an audited direct launcher may use the exact same flags and complete new application classes. Do not mix old application classes into the classpath.

```sh
mill -i IonSoC.compile
mill -i IonSoC.test.compile
mill -i IonSoC.test.runMain ooo.TimingReady73ConfigMain
mill -i IonSoC.test.runMain ooo.LoadPreparedCandidateConfigMain
mill -i IonSoC.test.runMain ooo.ResponseStateOnlyConfigMain
mill -i IonSoC.test.runMain ooo.FlushLoadPublishGsimMain "$COMPONENT"
"$GSIM" --threads=1 --dir="$COMPONENT" "$COMPONENT/FlushLoadPublishGsim.fir"
"$CXX" -std=c++20 -O1 -g -fsanitize=address,undefined -fno-sanitize-recover=all \
  -I"$COMPONENT" "$COMPONENT"/FlushLoadPublishGsim[0-9]*.cpp \
  simulator/gsim/harness/flush_load_publish.cpp -ldl -o "$COMPONENT/run"
"$COMPONENT/run"
```

The independently qualified component inputs also include `ResponseStateOnlyGsimMain` (actual tagged parent versus frozen reference), generic `LoadReadyProtocolGsimMain OUTPUT 1`, both `LoadPreparedCandidateGsimMain` modes, and the fetch component fixtures delivered with this batch. Keep the host negative-control flags and exact reached/reject anchors from their receipts. The combined Parallel control commands are:

```sh
"$COMPONENT/run" --invalid-handle # require nonzero and exact reached/reject
"$COMPONENT/run" --wrong-domain # require nonzero and exact reached/reject
"$COMPONENT/run" --unsolicited # require nonzero and exact reached/reject
"$COMPONENT/run" --duplicate # require nonzero and exact reached/reject
"$COMPONENT/run" --held-response-payload # require nonzero and exact reached/reject
"$COMPONENT/run" --oracle-token # require nonzero and exact reached/reject
"$COMPONENT/run" --oracle-data # require nonzero and exact reached/reject
"$COMPONENT/run" --oracle-publish-valid # require nonzero and exact reached/reject
"$COMPONENT/run" --oracle-publish-destination # require nonzero and exact reached/reject
"$COMPONENT/run" --oracle-publish-duplicate # require nonzero and exact reached/reject
"$COMPONENT/run" --inconsistent-admission # require nonzero and exact reached/reject
"$COMPONENT/run" --oracle-mirror # require nonzero and exact reached/reject
```

Generate one fresh `ooo.R6Exact73CpuMain MODEL` with the ordered `on_options` from `fpga/next/timing-ready73-profile.json`. Run GSIM once, compile every translation unit once (at most four jobs), and link all four hosts against that object inventory. Regenerate held semantic bindings from its FIR/header. Preserve DDR first-read32, beat-gap1, credits8, multi-ID service and original host compiler flags.

These are exact runtime arguments with relocatable placeholders. `$INPUTS` is the pinned host/guest handoff, `$BIN` holds linked NEMU/PMP/held hosts, `$MODEL/run` is the COPY host, and `$NEMU_SO` is the pinned reference interpreter. Activate the pinned toolchain first. Run each case in its own fresh output directory; verify stdout/TSV and designated nonzero rejection markers. Required inputs and generated model are delivered separately, not committed binaries.

```sh
# copy-bare
"$MODEL/run" "$INPUTS/copy/guest/guest.bin" 0 2 65536 2
# copy-sv39
"$MODEL/run" "$INPUTS/copy/guest/guest.bin" 1 2 65536 2
# copy-negative-read
"$MODEL/run" "$INPUTS/copy/guest/guest.bin" 1 2 4096 1 --inject-read
# copy-negative-memory
"$MODEL/run" "$INPUTS/copy/guest/guest.bin" 1 2 4096 1 --inject-memory
# copy-negative-trap
"$MODEL/run" "$INPUTS/copy/guest/guest.bin" 1 2 4096 1 --inject-trap
# nemu-hot
"$BIN/nemu-run" "$INPUTS/nemu/hot.bin" "$NEMU_SO" 0x802000c4 hot
# nemu-compressed
"$BIN/nemu-run" "$INPUTS/nemu/compressed.bin" "$NEMU_SO" 0x80200036 compressed
# nemu-negative-pc
"$BIN/nemu-run" "$INPUTS/nemu/compressed.bin" "$NEMU_SO" 0x80200036 compressed --inject-nemu-pc
# nemu-negative-gpr
"$BIN/nemu-run" "$INPUTS/nemu/compressed.bin" "$NEMU_SO" 0x80200036 compressed --inject-nemu-gpr
# nemu-negative-memory
"$BIN/nemu-run" "$INPUTS/nemu/compressed.bin" "$NEMU_SO" 0x80200036 compressed --inject-nemu-memory
# pmp-short
"$BIN/pmp-run" "$INPUTS/pmp/short/guest.bin" short
# pmp-word
"$BIN/pmp-run" "$INPUTS/pmp/word/guest.bin" word
# held-positive
"$BIN/held-run" "$INPUTS/held/guest.bin" "$INPUTS/held/input.txt"
# held-value
"$BIN/held-run" "$INPUTS/held/guest.bin" "$INPUTS/held/input.txt" value
# held-owner
"$BIN/held-run" "$INPUTS/held/guest.bin" "$INPUTS/held/input.txt" owner
```

## Supplementary actual backend witness

A subsequent directed legal Sv39 guest, linked against the same 37 objects, reached CSR reserve with a retained complete intrinsic proof at cycle823: candidate1, strict0, start0, other three flush causes0, no bound rising edge or credit consumption. It retired correctly and completed mailbox/trap/drain checks in1714 cycles. Two host-validator mutations reached and rejected at the same cycle; these are not DUT gate mutations. Supplemental receipt SHA256: `0a8f18c59930dce63f926ca647eb2fd71fb145bea4215b941991325180f0501d`. This supplements the original qualification without rewriting its historical coverage statement. At that witness olderSystem is also1; this does not prove reserveSystem is the sole necessary blocker. No simultaneous bound-store/early-credit/forwarded/posted ownership is claimed. The supplement and native receipt are independently pinned without overwriting the original qualification.

## Independent R6 evidence entry

```sh
python3 -B fpga/next/check_timing_r6.py --source "$SOURCE" --native "$NATIVE" --evidence "$EVIDENCE"
python3 -B fpga/next/test_timing_r6_entry.py --candidate-root "$CANDIDATE"
```

Compact pins bind immutable source, compile, CPU qualification, native and comparison receipts. Evidence is separate; generated RTL, compiler outputs, logs and model objects do not enter Git. The exact qualification binds the observed model inventory; consumers need not distribute those objects. This checker never launches synthesis. A future R6 physical entry must use its own candidate/staging identity, require this bound evidence and the reviewed supplement, preserve original MAC/JTAG/clock gates, and call the reviewed Tcl in documented order. It must not borrow R5 qualification or rewrite an old session seal.

## Reproduce the supplementary backend witness

The four added test leaves are `simulator/gsim/backend_system_reserve.py`,
`simulator/gsim/harness/backend_system_reserve.cpp`, and
`simulator/gsim/payloads/backend_system_reserve.{S,ld}`. They were added after
production compilation and do not change the 3207-file compiled-input identity.
The public runner was separately replayed against the same 37 objects, including
both host-validator negatives. It checks the model receipt, object/FIR/header
hashes, exact original service snapshot and flags, then derives read-only bindings
from unique final FIR connections. It never recompiles the CPU model.

```sh
python3 -B simulator/gsim/backend_system_reserve.py \
  --model "$MODEL" --model-receipt "$MODEL_RECEIPT" --output "$FRESH_CHECK" --check-only
python3 -B simulator/gsim/backend_system_reserve.py \
  --model "$MODEL" --model-receipt "$MODEL_RECEIPT" --output "$FRESH_RUN" \
  --cxx "$CXX" --cross-prefix "$RISCV_PREFIX"
```

Use the repository's default original host snapshot or supply `--host-root` to an
identical pinned copy. The toolchain must be activated first. Missing, duplicate,
conditional or unsupported binding shapes fail closed. Public replay receipt
SHA256: `f3fa8bba2359636897b4d3e97217e9d4be670fd4e6ec3e8c8ff783d644b3f18b`.
Six binding negative controls also rejected; this is host/binding coverage, not
additional CPU source-mutation coverage.
