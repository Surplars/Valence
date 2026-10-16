/* Each variant first proves a target read under effective S privilege,
 * then revokes SUM, MXR or PMP permission and requires a precise trap.
 * No stack or host writes to the running DUT. */
.option norvc
.section .text.start,"ax",@progbits
.globl _start
_start:
    la t0, PERM_HANDLER
    csrw mtvec, t0
    li t0, -1
    csrw pmpaddr0, t0
    csrw pmpaddr1, t0
    li t0, 31
    csrw pmpcfg0, t0
    li s0, 0x40000000
    li s1, 0x1111222233334444
    li t0, 0x8000000000080300
    csrw satp, t0
    sfence.vma x0, x0
#if CASE == 0
    li t0, 0x60800 /* SUM=1 */
#elif CASE == 1
    li t0, 0xa0800 /* MXR=1 */
#else
    li t0, 0x20800
#endif
    csrw mstatus, t0
    mv t2, s0
    li t3, 32
    li t4, 4096
1:  ld t5, 0(t2)
    add t2, t2, t4
    addi t3, t3, -1
    bnez t3, 1b
    fence rw, rw
.globl PERM_PROBE
PERM_PROBE:
    ld a0, 0(s0)
    bne a0, s1, PERM_FAIL
    li t0, 0x20000
    csrc mstatus, t0
#if CASE == 2
    li t0, 0x20100000 /* 8-byte NAPOT data region at PA 0x80400000 */
    csrw pmpaddr0, t0
    li t0, 0x1f18     /* entry0 deny; entry1 all-address allow */
    csrw pmpcfg0, t0
#endif
    li t0, 0x20800 /* SUM=MXR=0, effective privilege S */
    csrw mstatus, t0
.globl PERM_FAULT
PERM_FAULT:
    ld a0, 0(s0)
    j PERM_FAIL
.balign 4
.globl PERM_HANDLER
PERM_HANDLER:
    csrr t0, mcause
#if CASE == 2
    li t1, 5
#else
    li t1, 13
#endif
    bne t0, t1, PERM_FAIL
    csrr t0, mtval
    bne t0, s0, PERM_FAIL
    csrr t0, mepc
    la t1, PERM_FAULT
    bne t0, t1, PERM_FAIL
    li t0, 0x20000
    csrc mstatus, t0
    li t0, 0x80600000
    li t1, 0x56414c5045524d00 + CASE
    sd t1, 0(t0)
    fence rw, rw
    fence.i
    fence rw, rw
.globl PERM_DONE
PERM_DONE:
    nop
    j PERM_DONE
.balign 4
.globl PERM_FAIL
PERM_FAIL:
    j PERM_FAIL
