.option norvc
.option norelax
#ifndef I1_STREAM_WORDS
#define I1_STREAM_WORDS 1024
#endif
#ifndef I1_STREAM_DST
#define I1_STREAM_DST 0x80234000
#endif
.section .text.start
.globl _start
_start:
    la t0, handler
    csrw mtvec, t0
    li t0, 0x40080000          # TOR end 100200000, full 2GiB DDR + low MMIO
    csrw pmpaddr0, t0
    li t0, 15
    csrw pmpcfg0, t0
    li t0, 7
    csrw mcounteren, t0
    li t0, 0x80220010
    li t1, 0x200000cf
    sd t1, 0(t0)               # Identity 1GiB S leaf, A/D set
    li t0, 0x8020f000
    ld t1, 0(t0)               # Host selects 0=Bare, 1=Sv39; otherwise identical CPU/image/bus
    beqz t1, 1f
    li t0, 0x8000000000080220
    csrw satp, t0
    sfence.vma
1:  li s0, 0x80230000
    li s1, I1_STREAM_DST
    li s2, I1_STREAM_WORDS
    mv t0, s0
    mv t1, s2
    li t2, 0x123400000000
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
    rdcycle s4
3:  ld t3, 0(t0)
    add t2, t2, t3
    addi t0, t0, 8
    addi t1, t1, -1
    bnez t1, 3b
    rdcycle t4
    sub t4, t4, s4
    sd t4, 0(s3)
    sd t2, 24(s3)
    mv t0, s1
    mv t1, s2
    li t2, 0xabc00000
    rdcycle s4
4:  sd t2, 0(t0)
    addi t0, t0, 8
    addi t2, t2, 1
    addi t1, t1, -1
    bnez t1, 4b
    rdcycle t4
    sub t4, t4, s4
    sd t4, 8(s3)
    mv t0, s0
    mv t1, s1
    mv t2, s2
    rdcycle s4
5:  ld t3, 0(t0)
    sd t3, 0(t1)
    addi t0, t0, 8
    addi t1, t1, 8
    addi t2, t2, -1
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
