    .section .text.start,"ax"
    .globl _start
_start:
    la sp, _stack_top
    la t0, _data_load
    la t1, _data_start
    la t2, _data_end
1:  bgeu t1, t2, 2f
    ld t3, 0(t0)
    sd t3, 0(t1)
    addi t0, t0, 8
    addi t1, t1, 8
    j 1b
2:  la t1, _bss_start
    la t2, _bss_end
3:  bgeu t1, t2, 4f
    sb zero, 0(t1)
    addi t1, t1, 1
    j 3b
4:  call main
    la t0, coremark_validation_errors
    lw a0, 0(t0)
    la t0, coremark_elapsed_ticks
    ld a1, 0(t0)
    ebreak
5:  j 5b
