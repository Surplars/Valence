    .section .text.init,"ax",@progbits
    .globl _start
    .option norelax
_start:
    la gp, __global_pointer$
    la sp, __stack_top
    la t0, i1_trap
    csrw mtvec, t0
    csrci mstatus, 8
    la t0, __bss_start
    la t1, __bss_end
1:  bgeu t0, t1, 2f
    sd zero, 0(t0)
    addi t0, t0, 8
    j 1b
2:  fence.i
    call main
3:  j 3b

    .balign 16
    .globl i1_trap
i1_trap:
    li t0, 0x8fff0000
    csrr t1, mepc
    sd t1, 112(t0)
    csrr t1, mcause
    sd t1, 120(t0)
    csrr t1, mtval
    sd t1, 128(t0)
    li t1, 4
    sw t1, 68(t0)
    fence rw, rw
    li t1, 0x80000000
    sw t1, 64(t0)
4:  j 4b
