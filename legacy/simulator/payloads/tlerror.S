.section .text.init
.globl _start

_start:
    la   t0, trap_handler
    csrw mtvec, t0

    li   t0, 0x10010000
    li   t1, 'E'
    sb   t1, 0(t0)

    # Use a truly unmapped address so the crossbar local error responder must
    # return a denied TileLink response and raise load access fault.
    li   t0, 0x90000000
    ld   t1, 0(t0)

fail_no_trap:
    li   t0, 0x10010000
    li   t1, 'N'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
    j    fail_no_trap

.balign 4
trap_handler:
    csrr t0, mcause
    li   t1, 5
    bne  t0, t1, fail_bad_trap

    csrr t0, mtval
    li   t1, 0x90000000
    bne  t0, t1, fail_bad_trap

    li   t0, 0x10010000
    li   t1, 'P'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 0
pass_spin:
    j    pass_spin

fail_bad_trap:
    li   t0, 0x10010000
    li   t1, 'F'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
fail_spin:
    j    fail_spin
