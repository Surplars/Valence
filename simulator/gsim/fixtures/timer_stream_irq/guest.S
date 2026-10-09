.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, timer_stream_begin, timer_stream_end, timer_trap, timer_mret, timer_done, timer_fail
.equ DATA_BASE, 0x80220000
.equ SIGNATURE, 0x80240000
.equ STACK_TOP, 0x80242000
.equ TIMER_CMP, 0x02004000
.equ TIMER_TIME, 0x0200bff8
.equ WORDS, 8192
_start:
    csrw mie, zero
    csrci mstatus, 8
    li sp, STACK_TOP
    li t0, SIGNATURE
    sd zero, 0(t0)
    sd zero, 8(t0)
    sd zero, 16(t0)
    sd zero, 24(t0)
    la t0, timer_trap
    csrw mtvec, t0
    li t0, TIMER_TIME
    ld t1, 0(t0)
    li t2, 3000
    add t1, t1, t2
    li t0, TIMER_CMP
    sd t1, 0(t0)
    li t0, 128
    csrw mie, t0
    csrsi mstatus, 8
    li t0, DATA_BASE
    li t1, WORDS
    li t2, 0
    li t3, 0x6ac135ef892047bd
timer_stream_begin:
    xor t4, t2, t3
    sd t4, 0(t0)
    addi t0, t0, 8
    addi t2, t2, 1
    bltu t2, t1, timer_stream_begin
timer_stream_end:
    fence rw, rw
    li t0, SIGNATURE
    ld t1, 8(t0)
    li t2, 2
    bne t1, t2, timer_fail
    csrci mstatus, 8
    csrw mie, zero
    fence.i
    li t0, DATA_BASE
    li t1, WORDS
    li t2, 0
    li t3, 0x6ac135ef892047bd
1:
    ld t4, 0(t0)
    xor t5, t2, t3
    bne t4, t5, timer_fail
    addi t0, t0, 8
    addi t2, t2, 1
    bltu t2, t1, 1b
    li t0, STACK_TOP
    bne sp, t0, timer_fail
    li t0, SIGNATURE
    li t1, 0x54494d455250464f
    sd t1, 0(t0)
    csrr t1, mie
    sd t1, 32(t0)
    csrr t1, mstatus
    sd t1, 40(t0)
    fence rw, rw
    fence.i
timer_done:
    nop
    j timer_done
timer_fail:
    j timer_fail
.p2align 2
timer_trap:
    addi sp, sp, -64
    sd t0, 0(sp)
    sd t1, 8(sp)
    sd t2, 16(sp)
    sd t3, 24(sp)
    sd t4, 32(sp)
    sd t5, 40(sp)
    sd t6, 48(sp)
    csrr t0, mcause
    li t1, 0x8000000000000007
    bne t0, t1, timer_fail
    csrr t0, mip
    andi t0, t0, 128
    beqz t0, timer_fail
    li t0, SIGNATURE
    ld t1, 8(t0)
    addi t1, t1, 1
    sd t1, 8(t0)
    li t2, 2
    bgtu t1, t2, timer_fail
    csrr t3, mepc
    slli t4, t1, 3
    add t4, t4, t0
    sd t3, 8(t4)
    beq t1, t2, 2f
    li t0, TIMER_TIME
    ld t1, 0(t0)
    li t2, 3000
    add t1, t1, t2
    j 3f
2:
    li t1, -1
3:
    li t0, TIMER_CMP
    sd t1, 0(t0)
    ld t0, 0(sp)
    ld t1, 8(sp)
    ld t2, 16(sp)
    ld t3, 24(sp)
    ld t4, 32(sp)
    ld t5, 40(sp)
    ld t6, 48(sp)
    addi sp, sp, 64
timer_mret:
    mret
