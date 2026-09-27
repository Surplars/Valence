    .section .text.start, "ax"
    .globl _start
_start:
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 31
    csrw pmpcfg0, t0
    la t0, trap_handler
    csrw mtvec, t0
    # A page-table write is allowed to remain dirty in the physical L1. The
    # subsequent walk must obtain it through the coherent home.
    li t0, 0x80012010
    li t2, 0x200050c7
    sd t2, 0(t0)
    li t0, 0x8000000000080010
    csrw satp, t0
    sfence.vma x0, x0
    li t0, (1 << 17) | (1 << 11)
    csrw mstatus, t0
    li t1, 0x40002000
    ld a0, 0(t1)
    sd a0, 8(t1)
    ld a4, 8(t1)
    addi t4, t1, 8
    amoadd.d a6, zero, (t4)
    sd a0, 8(t1)
    # PBMT=NC alias of the same physical page must see the dirty cacheable store.
    li t3, 0x40004000
    ld a5, 8(t3)
    li t5, 128
1:  ld t6, 8(t1)
    addi t6, t6, 1
    sd t6, 8(t1)
    addi t5, t5, -1
    bnez t5, 1b
    li t2, 0x40003000
    ld a3, 0(t2)
fail_loop:
    j fail_loop
trap_handler:
    csrr a1, mcause
    csrr a2, mtval
trap_loop:
    j trap_loop
