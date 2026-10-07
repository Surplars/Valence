.option norvc
.option norelax
.section .text.start,"ax"
.globl _start
_start:
    la sp, __app_stack_top
    addi sp, sp, -16
    sd ra, 0(sp)
    la gp, __global_pointer$
    la t0, __bss_start
    la t1, __bss_end
1:  bgeu t0, t1, 2f
    sb zero, 0(t0)
    addi t0, t0, 1
    j 1b
2:  call main
    ld ra, 0(sp)
    addi sp, sp, 16
    ret
