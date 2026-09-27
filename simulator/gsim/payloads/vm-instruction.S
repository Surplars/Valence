    .section .text.start, "ax"
    .globl _start
_start:
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 31
    csrw pmpcfg0, t0
    la t0, trap_handler
    csrw mtvec, t0
    li t0, 0x8000000000080010
    csrw satp, t0
    sfence.vma x0, x0
    li t0, 0x40000100
    csrw mepc, t0
    li t0, 1 << 11
    csrw mstatus, t0
    mret
    j .

    .org 0x80
trap_handler:
    csrr a1, mcause
    csrr a2, mtval
    csrr a3, mepc
trap_loop:
    j trap_loop

    .org 0x100
supervisor_start:
    li t1, 0x40002000
    addi sp, t1, 0x100
    c.li s0, 7
    c.addi s0, 1
    c.addiw s0, -1
    c.slli s0, 1
    c.srli s0, 1
    c.srai s0, 1
    c.andi s0, 3
    li t0, 3
    bne s0, t0, compressed_fail
    c.li s1, 1
    c.sub s0, s1
    c.xor s0, s1
    c.or s0, s1
    c.and s0, s1
    c.subw s0, s1
    c.addw s0, s1
    c.add s0, s1
    c.mv s0, s1
    bne s0, s1, compressed_fail
    c.addi4spn s0, sp, 16
    c.sd s1, 0(s0)
    c.ld s1, 0(s0)
    c.sw s1, 8(s0)
    c.lw s1, 8(s0)
    c.sdsp s1, 8(sp)
    c.ldsp s1, 8(sp)
    c.swsp s1, 16(sp)
    c.lwsp s1, 16(sp)
    li t0, 1
    bne s1, t0, compressed_fail
    c.beqz s1, compressed_fail
    c.bnez s1, 1f
    j compressed_fail
1:  c.j 2f
    j compressed_fail
2:  la t2, 3f
    c.jalr t2
4:  c.lui s0, 1
    li t0, 4096
    bne s0, t0, compressed_fail
    c.addi16sp sp, 16
    c.addi16sp sp, -16
    c.nop
    ld a0, 0(t1)
    li t0, 0x40000ffc
    jr t0
    j .
3:  la t0, 4b
    bne ra, t0, compressed_fail
    c.jr ra
compressed_fail:
    ebreak
    j .

    .org 0xffc
page_end:
#ifdef CROSS_PAGE
    c.nop
#endif
    .option push
    .option norvc
    addi a0, a0, 1
    .option pop
