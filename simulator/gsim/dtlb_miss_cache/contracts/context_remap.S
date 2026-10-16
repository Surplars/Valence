/* Native CPU integration fixture. No stack, no host-forced DUT signals.
 * Host supplies 32 4K mappings at VA 0x40000000 in roots 0x80300000/0x80310000.
 * Initial target sentinel A=0x1111222233334444; remap B and other root C differ.
 * Unrelated M-mode physical instruction fetch never depends on the D mapping.
 */
.option norvc
.section .text.start,"ax",@progbits
.globl _start
_start:
    la t0, CTX_FAIL
    csrw mtvec, t0
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 31
    csrw pmpcfg0, t0
    li s0, 0x40000000
    li s1, 0x1111222233334444
    li s2, 0x5555666677778888
    li s3, 0x123456789abcdef0
    li t0, 0x8000000000080300
    csrw satp, t0
    sfence.vma x0, x0
    li t0, 0x20800             /* MPRV=1, MPP=S, interrupts disabled */
    csrw mstatus, t0
    jal ra, warm32
.globl CTX_PROBE_A
CTX_PROBE_A:
    ld a0, 0(s0)
    bne a0, s1, CTX_FAIL
    li t0, 0x20000
    csrc mstatus, t0           /* PTE update is an M-mode physical store */
    li t0, 0x80303000
    li t1, 0x201200cf          /* 4K leaf PA=0x80480000, VRWXAD */
    sd t1, 0(t0)
    fence rw, rw
.globl CTX_SFENCE
CTX_SFENCE:
    sfence.vma x0, x0
    li t0, 0x20800
    csrw mstatus, t0
.globl CTX_AFTER_SFENCE
CTX_AFTER_SFENCE:
    ld a0, 0(s0)
    bne a0, s2, CTX_FAIL
    jal ra, warm32
.globl CTX_PROBE_B
CTX_PROBE_B:
    ld a0, 0(s0)
    bne a0, s2, CTX_FAIL
    li t0, 0x20000
    csrc mstatus, t0
    li t0, 0x8000100000080310  /* Sv39, ASID=1, distinct root 0x80310000 */
.globl CTX_SATP
CTX_SATP:
    csrw satp, t0
    /* Fresh ASID/root: do not add an SFENCE that could conceal context aliasing. */
    li t0, 0x20800
    csrw mstatus, t0
.globl CTX_AFTER_SATP
CTX_AFTER_SATP:
    ld a0, 0(s0)
    bne a0, s3, CTX_FAIL
    jal ra, warm32
.globl CTX_PROBE_C
CTX_PROBE_C:
    ld a0, 0(s0)
    bne a0, s3, CTX_FAIL
    li t0, 0x20000
    csrc mstatus, t0
    li t0, 0x80600000
    li t1, 0x56414c454e43454f
    sd t1, 0(t0)
    fence rw, rw
    fence.i                     /* Only final signature writeback, not PTE fixup. */
    fence rw, rw
.globl CTX_DONE
CTX_DONE:
    nop
    j CTX_DONE
warm32:
    mv t2, s0
    li t3, 32
    li t4, 4096
1:  ld t5, 0(t2)
    add t2, t2, t4
    addi t3, t3, -1
    bnez t3, 1b
    fence rw, rw
    ret
.balign 4
.globl CTX_FAIL
CTX_FAIL:
    j CTX_FAIL
