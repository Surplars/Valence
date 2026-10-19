# Same 8KiB buffers/checksum as privilege_throughput.S, but eight-way
# unrolled instruction scheduling. Not a new cache/owner or benchmark score.
.option norvc
.option norelax
.section .text.start
.globl _start
_start:
    la t0, handler
    csrw mtvec, t0
    li t0, 0x40080000
    csrw pmpaddr0, t0
    li t0, 15
    csrw pmpcfg0, t0
    li t0, 7
    csrw mcounteren, t0
    li t0, 0x80220010
    li t1, 0x200000cf
    sd t1, 0(t0)
    li t0, 0x8020f000
    ld t1, 0(t0)
    beqz t1, 1f
    li t0, 0x8000000000080220
    csrw satp, t0
    sfence.vma
1:  li s0, 0x80230000
    li s1, 0x80234000
    li s2, 1024
    mv t0, s0
    mv t1, s2
#ifdef I1_DENSE_MUTATION
    li t2, 0x123400000001
#else
    li t2, 0x123400000000
#endif
2:  sd t2, 0(t0)
    addi t0, t0, 8
    addi t2, t2, 1
    addi t1, t1, -1
    bnez t1, 2b
    la t0, supervisor
    csrw mepc, t0
    li t0, 0x800
    csrw mstatus, t0
    mret
supervisor:
    li s3, 0x80210000
    mv t0, s0
    mv t1, s2
    li t2, 0
#ifndef I1_DENSE_WRITE_ONLY
    rdcycle s4
3:
    .set off, 0
    .irp reg, t3,t4,t5,t6,a1,a2,a3,a4
    ld \reg, off(t0)
    .set off, off+8
    .endr
    .irp reg, t3,t4,t5,t6,a1,a2,a3,a4
    add t2, t2, \reg
    .endr
    addi t0, t0, 64
    addi t1, t1, -8
    bnez t1, 3b
    rdcycle t4
    sub t4, t4, s4
#else
    li t4, 0
    li t2, 0x48d0000007fe00    # Independent host's sum of 1024 source words
#endif
    sd t4, 0(s3)
    sd t2, 24(s3)
    mv t0, s1
    mv t1, s2
    li t2, 0xabc00000
    rdcycle s4
4:
    .set off, 0
    .rept 8
    sd t2, off(t0)
    addi t2, t2, 1
    .set off, off+8
    .endr
    addi t0, t0, 64
    addi t1, t1, -8
    bnez t1, 4b
    rdcycle t4
    sub t4, t4, s4
    sd t4, 8(s3)
#ifdef I1_DENSE_WRITE_ONLY
    # Outside the timer: verify the WRITE payload BEFORE COPY can overwrite it.
    mv t0, s1
    mv t1, s2
    li t2, 0xabc00000
6:  ld t3, 0(t0)
    bne t3, t2, fail
    addi t0, t0, 8
    addi t2, t2, 1
    addi t1, t1, -1
    bnez t1, 6b
#endif
    mv t0, s0
    mv t1, s1
    mv t2, s2
    rdcycle s4
5:
    .set off, 0
    .irp reg, t3,t4,t5,t6,a1,a2,a3,a4
    ld \reg, off(t0)
    .set off, off+8
    .endr
    .set off, 0
    .irp reg, t3,t4,t5,t6,a1,a2,a3,a4
    sd \reg, off(t1)
    .set off, off+8
    .endr
    addi t0, t0, 64
    addi t1, t1, 64
    addi t2, t2, -8
    bnez t2, 5b
    rdcycle t4
    sub t4, t4, s4
    sd t4, 16(s3)
    ecall
handler:
    csrr t0, mcause
    li t1, 9
    bne t0, t1, fail
    li a0, 0
    ebreak
fail:
    li a0, 1
    ebreak
