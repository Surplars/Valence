# FPGA-first issue and fetch storage candidate

## Scope and acceptance contract

Base: published `ea5406ea15d2d0797ce2c5ef7a4951827c55145e`.
The candidate keeps two-wide rename/issue/commit, 16 ROB entries, 48 integer
physical registers, two LSU entries, and the complete configured ISA. It does
not alter FPU, cache, external memory, MAC, or JTAG behavior. Physical area,
timing, power, and board behavior require a subsequent combined FPGA run.

The two independent opt-in switches are `bankedIssuePayload` and
`bankedFetchHints`. Their defaults remain false. Neither switch changes a
pipeline boundary, minimum latency, capacity, throughput limit, or externally
observable backpressure contract.

### Immutable issue fields

Only allocation writes immutable issue context. The baseline stores the context
in a register array and selects it for execution. The proposed topology splits
large fields into separate asynchronous-read memories. Two parity banks accept
the existing contiguous two-wide allocation, including odd/even pairs and ROB
wrap. Each parity bank has one physical write port. A hardware assertion checks
that simultaneously accepted writes do not collide in a parity bank.

Full generation tags, physical source/destination IDs, class/control bits, and
live/ready/cancellation metadata stay in local registers. Scheduling and stale
completion checks must not acquire a new memory read dependency. A selected
execution consumer reads only the fields it needs by ROB index. The memory
interface must not expose an array of every entry, which would create one read
port for each scheduler slot.

Planned field partition (bits per entry):

- PC: 64
- Original instruction: 32
- Expanded instruction: 32
- Predicted successor target: 64; its valid bit remains metadata
- Immediate: 64
- Fetch fault `tval`: 64

Allocation takes the same priority as the original final register assignments.
Reads observe old data before an allocation edge and new data after that edge.
No write-through bypass is added. RAM contents are not reset. Existing live,
owner, and pending guards determine whether payload is usable; a no-owner
one-hot selection still returns an all-zero entry. Precise original instruction
and fault `tval`, generation-token comparisons, staged branch redirects, and
load-owner checks remain mandatory.

### Accepted-successor fetch hints

The 32-entry baseline has 162 payload bits per entry: full PC, full instruction,
full successor, alignment, and nonsequential qualification. The two training
writers have arbitrary addresses. They cannot be partitioned by address parity.

The proposed topology has one single-writer memory bank per training lane and a
small per-index last-writer owner table. Both writes proceed independently;
higher-numbered lane wins when both address the same index. Validity resets and
invalidation wins over simultaneous training. Invalidation need not clear the
RAM or owner table. A lookup uses the full PC and instruction, never a shortened
tag or hash as architectural authorization. Read/write collision behavior is
the existing pre-edge-old/post-edge-new behavior.

The registered instruction reservoir retains the same two-packet capacity,
one-cycle minimum latency, prefix credits, partial-packet compaction, compressed
instruction lengths, direct-jump handling, pause semantics, and flush priority.

## Primary design reference

NaxRiscv was inspected at commit
`9f452d50560d02fb391bc8039f5453c54e0911af`:

- `src/main/scala/naxriscv/misc/RobPlugin.scala`: `storage` creates field-specific
  memories, derives banking from actual write/read widths, and reads context by
  ROB ID.
- `src/main/scala/naxriscv/execute/ExecutionUnitBase.scala`: execution fetch
  carries ROB ID, then obtains only requested micro-op/context fields before
  its register-file stages.

This is a local architectural comparison, not a claim of NaxRiscv equivalence
or a port of its scheduler.

## Evidence status

The unchanged release frontend passed its independent randomized/directed GSIM
oracle for 32,185 cycles with a fresh injected packet corruption rejected.
It exercised steady-state two-wide supply, partial joins, redirect/validation,
faults, backpressure, reset, signed jump boundaries, and hint qualification.
Its legacy random training primarily uses lane 0; explicit arbitrary two-writer
and collision coverage is required before the RAM candidate can pass.

Core baseline, candidate implementation, expanded independent tests, per-field
RAM port census, and same-binary hardware-cycle comparison are in progress.
No LUT, timing, or IPC improvement is claimed by this document.

### Focused implementation checkpoint
+
+The candidate is implemented with the defaults still off. The explicit RAM
+readers are registered in `IntegerBackend.readIssue`; the resulting module has
+per-field reader lists, not an all-entry array output. Zero-owner execution
+selection still returns zero. The hint RAM gates only its narrow owner index
+while invalid; invalid payload remains unspecified as in the original table,
+and full-tag hit qualification is gated by validity. No 162-bit validity mux is
+inserted on the hint data output.
+
+Frozen focused evidence:
+
+- `fpga-next-cpu-unit-r2`: issue RAM unit and six paired fetch variants passed.
+  The batch then stopped on a backend elaboration scope error, so its overall
+  status remains `FAIL`; it is not a complete acceptance receipt.
+- `fpga-next-cpu-unit-r3`: the read was moved outside the conditional Chisel
+  scope, and the affected backend-only pair passed. Its explicit status is
+  `PASS_UNIT_PARTIAL` because unrelated leaf tests were not repeated.
+- All three leaf RTL sources (`BankedIssuePayload`, `OwnerBankedFetchHints`, and
+  `RegisteredFetchPacket`) are byte-identical between those two receipts.
+
+The issue RAM unit checked 16,000 cycles, 109,790 valid reads, 22,601 writes,
+7,981 dual writes, 546 wrap pairs, 26,727 read/write collisions and 18,210
+disabled reads. Both corrupted-payload and illegal-parity-write controls were
+rejected. All field accesses retain full-width values, including high PC/target
+and fault-address bits.
+
+Fetch register/RAM pairs matched all event and coverage counters in two-wide
+compressed, two-wide uncompressed and four-wide compressed configurations.
+Directed cases cover same-parity different-index writers, exact-index lane-1
+priority, full-PC aliases, mismatched instruction tags, both lookup ports,
+read-during-write old data, invalidation with replacement, and unreset RAM after
+reset. Reset cancellation is now deliberately populated rather than relying on
+random reset timing. Packet-payload and hint-successor corruption controls were
+rejected separately.
+
+Backend register/RAM pairs matched 22,318 cycles, 26,881 allocations, 25,704
+issues, 23,805 commits, 10,390 dual-issue cycles, 992 redirects and 15 precise
+fetch-fault cases. The test includes allocation reuse, stale delayed load
+responses, rollback, held commits and full 64-bit fault tval. The poisoned tval
+control was rejected on each model.
+
+Optimized FIR (not mapped FPGA area) for that standalone backend shows the issue
+queue's register declarations changing from 7,376 to 1,904 bits. Besides moving
+payload to RAM, field separation lets unused packed metadata disappear. Expanded
+system-instruction storage is unused in this non-system fixture and disappears;
+it must be checked separately in the complete RV64GC/system configuration.
+
+The remaining RAM geometry in this fixture is:
+
+| Field | Banks | Width | Depth per bank | Async readers per bank | Writers per bank |
+| --- | ---: | ---: | ---: | --- | ---: |
+| PC | 2 | 64 | 8 | 7 / 6 | 1 |
+| Original instruction | 2 | 32 | 8 | 3 / 3 | 1 |
+| Predicted next PC | 2 | 64 | 8 | 2 / 2 | 1 |
+| Immediate | 2 | 64 | 8 | 3 / 3 | 1 |
+| Fetch tval | 2 | 64 | 8 | 2 / 2 | 1 |
+
+Read latency is zero and write latency one. Multiple asynchronous readers may
+require physical RAM replication; neither the declared-bit change nor the
+logical memory count is a LUT, FF, BRAM, timing or power result.
+
+The initial 12-bin bare-core baseline used the timing profile's historical
+load-issue-forwarding default (off). The final storage comparison explicitly
+enables forwarding on both sides to match the selected FPGA reference, and adds
+the hint-alias and serial load/ALU/address bins. Do not compare the two matrices
+as a storage speedup. Full-core, virtual-context and routed FPGA qualification
+remain separate gates.

### Four-way core qualification
+
+`build/gsim/fpga-next-cpu-core-r2/receipt.json` is `PASS_CORE`. It compares the
+register baseline, issue RAM only, hint RAM only, and both RAM options, with
+load-issue forwarding explicitly enabled in every variant. All 15 workload rows
+match exactly, including cycles, retirement, issue/rename histograms, redirects,
+occupancy, memory activity and the new full-token load timing distributions.
+Each variant retires 9,318 independently NEMU-checked instructions in that matrix.
+Each also passes the 13-program pipeline recovery check and rejects injected
+architectural register corruption. This is the qualification gate for the two
+storage flags at bare-core level; full system/VM/FP integration remains separate.
+
+The passive timing observer reports real LSU start, accepted result and matching
+full-token retirement events. It also measures the external synthetic RAM
+request/reply pair and initiation gaps. In the serial 128-link load/ALU/address
+workload, synthetic RAM latency 1 produces LSU-start-to-result 3 cycles and a
+6-cycle start interval; synthetic latency 12 produces 14 and 17 cycles. These
+values are identical in all four variants and are not SoC cache/TLB latencies.
+The matrix has no deliberately applied external reply backpressure; recovery
+and other behavioral tests separately check holding/owner rules.
+
+An additional replay on the architect's hash-verified exact board reference uses
+the existing independent-line guest, with no RTL rebuild. It passes the separate
+`fpga-next-independent-lines-reference` receipt: 3,072 line reads take 114,346
+host retirement-bounded cycles, demand owner peak is two, 99,496 cycles have two
+owners, and 89,329 have two acquire/fill phases. The backing-memory mutation is
+rejected. The ordinary eight-way unrolled stream instead puts eight words in one
+line, explaining why its MSHR occupancy alone cannot diagnose a general CPU
+concurrency limit. This replay is a frozen-reference observation, not a storage
+candidate throughput claim.
