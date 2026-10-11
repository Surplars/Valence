# Joint-ON CPU resource qualification

Production source and its already-compiled Scala classes remain at 3969476cad0775f5b6de405502a4e6822f566311. The four fixture Scala files compile separately against that immutable runtime. No OFF Board rebuild is planned. Only original singleton COPY cases 19 and 21 execute, with unchanged guest and host.cpp, original AXI timing, buffer/row/fault/CSR/SP/GP checks, and all original owner/translation/frontier/LRU observers.

The only C++ host adapter change is explicit ON queue token index reconstruction as slot i with ROB64 geometry. It preserves raw tag64 and independently compares the live row tag to the ledger tag. No CPU host reads loadBeat/loadLanes. The existing store-address observer already requires memoryLive, memory, store and addressKnown, so its full64-bit store VA read is unchanged. No historical adapter is modified.

Current pins.json binds all fixture/host sources, complete original parser inputs, original guest/model certificate, frozen native source/runtime, tools, strict full joint-ON expected profile, and actual focused qualification. Failed tiny r1 is retained: a renamed main lost its special C++ implicit return. Current tiny positive and independent nonzero index, fulltag-bit63 and class-mutation controls use a real main. No DUT issue was involved.

## Commands and gates

Run from the recovery root, one granted heavy slot:

1. `python3 memory-state-reuse-cpu-20261011-r1/run.py fixture --slot-granted`
2. `python3 memory-state-reuse-cpu-20261011-r1/run.py elab --slot-granted`
3. `python3 memory-state-reuse-cpu-20261011-r1/run.py generate --slot-granted`
4. `python3 memory-state-reuse-cpu-20261011-r1/run.py abi`
5. `python3 memory-state-reuse-cpu-20261011-r1/run.py compile --slot-granted`
6. `python3 memory-state-reuse-cpu-20261011-r1/run.py host --slot-granted`
7. `python3 memory-state-reuse-cpu-20261011-r1/run.py smoke --slot-granted`
8. `python3 memory-state-reuse-cpu-20261011-r1/run.py case --case 19 --slot-granted`
9. Persist and restore-verify the case19 evidence before authorized raw reclamation; then run case21 with the same command and `--case 21`.

The smoke step uses unchanged official rv64gc_smoke.S, sample_app.ld and rv64gc_board.cpp. It runs the original short positive plus actual mismatch negative on the new joint-ON object once. CPU cases require this gate, tiny controls, actual-header syntax, generation, compile and host receipts bound to the same pins and artifact chain.

Exact qualification requires all 18 positive/negative original raw sidecars, exact original stdout, the full parsed primary result, and the original parser/input identities. With these byte identities, the historical parsed certificate may be reused without restoring obsolete gigabytes. `--force-full-parse` runs every original validator anyway. Any raw mismatch automatically invokes the original full validators and stops the equality gate for explanation. Historical boundary-join uncertainty remains explicitly UNKNOWN.

The old case19 raw source paths are no longer assumed readable. The verified successor is same-set-prefetch-admission-observer-20261011-r1/case19-on-r1, with terminal receipt SHA256 322a57467b57bc489b72c447b973d309c69b4dadc8b5d325ee2a8257622d2bbe. Pins records exact per-member hashes and current aliases. Missing case21 raw may be compared by its original pinned artifact digest; content access requires a verified local alias or a separately authorized archived member.

## Measured budget

The original same-profile Board files were FIR39,474,131B + CPP76,520,497B + object33,680,672B + header1,842,930B. Its linked host was28,381,032B. Reserve200MiB for the new model plus host, with an additional approximately30MiB for the short smoke executable. The former model Clang took467.09s and peaked7,514,424KiB. New Clang timeout is1800s; Java fixture/emission and GSIM have explicit bounds.

The original case19 positive raw totaled952,559,595B including the derived lifetime file; its trap negative used about11.7MiB. Reserve1.1GiB per case and require1.8GiB available before a positive run. Case19 and21 formerly took284.70s and303.70s with roughly720-736MiB peak host memory. Each runtime now has1800s bound. Keep700MiB free throughout, bounded stdout, and process-tree resource receipts. Board stage admission requires1100MiB free, so stage output growth may require reclaiming already-durable duplicates before the next stage.

No full54 sweep, extra policy treatment, Vivado, synthesis, timing, or FPGA result is implied by these gates.
