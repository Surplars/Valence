    .section .text.start,"ax"
    .globl _start
_start:
    la sp, _stack_top
    li a0, 0
    call target
    li t2, 1
    bne a0, t2, fail
    call target
    li t2, 2
    bne a0, t2, fail
    la t0, target
    li t1, 0x00500513  # replace ADDI a0,a0,1 with ADDI a0,zero,5
    sw t1, 0(t0)
    fence.i
    call target
    li t2, 5
    bne a0, t2, fail
    # Train two conditional sites with alternating direction and repeated loop exits.
    li t0, 50
    li t1, 0
1:  xori t1, t1, 1
    beq t1, zero, 2f
    j 3f
2:  addi t3, t3, 1
3:  addi t0, t0, -1
    bne t0, zero, 1b
    li t2, 25
    bne t3, t2, fail
    la t0, done
    jalr zero, t0, 0
    # Must not execute either the store or exception on this wrong path.
    sd zero, 0(sp)
    .word 0xffffffff
done:
    li a0, 0
    ebreak
fail:
    li a0, 1
    ebreak
    .balign 64
target:
    addi a0, a0, 1
    ret
