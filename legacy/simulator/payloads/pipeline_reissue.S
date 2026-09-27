.section .text.init
.option rvc
.globl _start

_start:
    li   t0, 0x10010000
    li   s0, 0x30
    li   s1, 0

    # Regression for a RustSBI bring-up failure where a held ID-stage
    # instruction was issued into ALU twice while redirect/stall control
    # changed around a compressed ALU/branch loop.
loop:
    c.addi s0, -16
    c.addi s1, 16
    beqz s0, check
    j    loop

check:
    li   t1, 0x30
    bne  s1, t1, fail

pass:
    li   t1, 'R'
    sb   t1, 0(t0)
    li   t1, 'P'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 0
pass_spin:
    j    pass_spin

fail:
    li   t1, 'R'
    sb   t1, 0(t0)
    li   t1, 'F'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
fail_spin:
    j    fail_spin
