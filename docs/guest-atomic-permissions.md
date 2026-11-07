# Guest atomic permission boundaries

This focused GSIM entry supplements [guest atomics](guest-atomics.md) with the
previously deferred final-SPA PMP and A-disabled instruction-execution cases.
It changes no production RTL, configuration default or permission rule.

## Actual DUTs and cases

`make gsim-guest-atomic-permissions-test` freshly builds two same-clock fixtures:

- `GuestAtomicPmpGsim`: the actual H tile with atomics explicitly enabled.
- `GuestAtomicDisabledGsim`: the same production tile with atomics disabled.

Both use the real common fabric, ROM/RAM and existing atomic engine. Passive
observations expose the core's accepted virtual data requests and data-page-table
offers; they do not replace hardware, supply results or drive control. Shared
instruction-fetch walks are distinguished from data translation. Both profiles
disable interrupt sources/enables and DMA activity.

Each profile executes LR.W/D, SC.W/D without a preceding LR, and AMOADD.W/D, under
two legal request/response/commit-stall schedules. W uses the upper 32-bit beat
lane. Boot reads the real `misa`, requiring A to match the selected profile and H
to remain clear. A-disabled execution is not a runtime `misa.A` switch; the
implemented A selector is static.

## Final-SPA PMP denial

Guest code uses nonidentity VS Sv39 and G Sv39x4 translation. Both stages permit
the requested operation, with A/D set. A narrow unlocked NAPOT PMP entry covers
only the final physical target page and precedes a broad RWX entry covering the
tables, instruction page, HS handler and other RAM.

- LR uses execute-only PMP (`0x1c`): no read permission, expected load access
  fault cause 5.
- SC and AMOADD use read-only PMP (`0x19`): no write permission, expected
  store/AMO access fault cause 7. A missing SC reservation must not bypass this
  permission failure and merely return an SC-failed value.
- R=0/W=1 is not used: it is a reserved combination, and the implementation's
  WARL rule clears W when R is clear.

The fault is VS-origin and delegated to HS. Checks require exact SEPC, original
guest VA in STVAL, GVA/SPV/SPVP set, zero HTVAL/HTINST, and access-fault rather than
guest-page-fault provenance. The actual data translation and data-PTE observations
must occur before the trap. No target physical data offer is permitted.

SC/AMO targets remain readable, so an ordinary guest LD after return verifies the
unchanged target. The LR target is intentionally unreadable: that case explicitly
uses zero physical target offers, unchanged destination and accessible neighboring
RAM checks, not a target readback. Permissions are never weakened after failure.

## A-disabled illegal instructions

With ordinary permissive PMP, the same representative atomic encodings execute on
the A-disabled tile. They must produce cause 2 before any accepted virtual data
request or data-PTE offer. SEPC identifies the rejected instruction and STVAL is
its exact zero-extended encoding. GVA is clear, SPV/SPVP are set, HTVAL/HTINST are
zero, and the destination sentinel remains unchanged. Normal guest target LD
readback after the HS return verifies unchanged memory.

This is dynamic behavioral evidence for representative W/D atomic instruction
classes. It does not claim every reserved encoding or every possible opcode.

## Precise retirement and side effects

Each faulting instruction is followed by a younger poison store. The HS handler
reads the real trap CSRs, advances saved SEPC by eight and executes SRET, skipping
both rejected instruction and poison store. Neither may retire or offer physical
data traffic. The poison location is then read back unchanged, and a separate
intended resumed store/load checks that ordinary execution continues.

Complete expected retirement and physical transaction streams are computed before
the DUT starts. Every retired instruction/result/next-PC, physical offer, accepted
owner and response is checked. Forbidden traffic is rejected on `valid`, not only
on handshake. Data owners must drain at completion; any remaining fetch owners
are explicitly accounted, not claimed to be general quiescence.

Both profiles run `--wrong-cause` as an independent negative control. Exit 1 and
the exact final `FAIL independent atomic permission cause` are required; sanitizer
errors are not accepted. Entry unit tests mock execution and remain distinct from
the real GSIM evidence.

## Scope and specification

The pinned [A 2.1](https://docs.riscv.org/reference/isa/v20250508/unpriv/a-st-ext.html),
[machine PMP](https://docs.riscv.org/reference/isa/v20250508/priv/machine.html) and
[H trap](https://docs.riscv.org/reference/isa/v20250508/priv/hypervisor.html)
specifications define the permission and exception contracts.

All cases stay VS-origin and HS-delegated. No M-origin guest-fault review,
IRQ/fault-overlap experiment, independent clock, DMA/multicore qualification,
full PMP matrix, OS boot, complete A/H compliance or FPGA PPA claim is added.
The original H and atomic defaults remain off.
