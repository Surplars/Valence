# Real instruction execution only. No request injection, latency override or RTL probe.
.option norvc
.option norelax
.section .text.start
.globl _start, warmup_load, replay_div, replay_older, replay_younger
.globl branch_div, branch_taken, wrong0, wrong1, wrong2, wrong3
.globl branch_target, survivor0, survivor1, survivor2, survivor3, signature_store, replay_done
_start:
    li s0, 0x80400000
    # The board releases ROM execution before DDR calibration. Wait on a real
    # known-RAM response before starting the measured ordering scenarios.
warmup_load:
    ld zero, 0(s0)
    fence iorw, iorw
    li t0, 0x180c00000
    li t1, 3
.balign 64
replay_div:
    divu t2, t0, t1
    # Already-ready predecessors remain while the dependent address is checked.
    # ON must retire a real older prefix here; OFF must preserve its global hold.
    .rept 8
    addi zero, zero, 0
    .endr
replay_older:
    ld a0, 0(t2)
replay_younger:
    ld a1, 0(s0)
    fence iorw, iorw
    li s1, 0x80401000
    li s2, 0x2aaaaaaa
    li t0, 0x7fffffff
.balign 64
branch_div:
    divuw a2, t0, t1
branch_taken:
    beq a2, s2, branch_target
wrong0:
    ld a3, 0(s1)
wrong1:
    ld a4, 64(s1)
wrong2:
    ld a5, 128(s1)
wrong3:
    ld a6, 192(s1)
    addi a7, zero, 99
    addi zero, zero, 0
branch_target:
    fence iorw, iorw
    # Reuse every canceled physical owner only after its old generation drains.
    # Additional harmless instructions force ROB index reuse as well.
    .rept 20
    addi zero, zero, 0
    .endr
survivor0:
    ld a3, 0(s1)
survivor1:
    ld a4, 64(s1)
survivor2:
    ld a5, 128(s1)
survivor3:
    ld a6, 192(s1)
    li s3, 0x80600000
signature_store:
    sd a0, 0(s3)
    fence iorw, iorw
    fence.i
replay_done:
    j replay_done
    # Bounded harmless fall-through fetch guard; never architecturally retired.
    .rept 16
    addi zero, zero, 0
    .endr
