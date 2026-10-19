    .option norvc
    .option norelax
    .section .text.start,"ax"
    .globl _start
_start:
    la sp, _stack_top
    addi sp,sp,-16
    li a0,0
    call target
    li t2,1
    bne a0,t2,fail
    call target
    li t2,2
    bne a0,t2,fail
    la t0,target
    li t1,0x00500513
    sw t1,0(t0)
    fence.i
    call target
    li t2,5
    bne a0,t2,fail
    li t0,50
    li t1,0
    li t3,0
1:  xori t1,t1,1
    beq t1,zero,2f
    j 3f
2:  addi t3,t3,1
3:  addi t0,t0,-1
    bne t0,zero,1b
    li t2,25
    bne t3,t2,fail
    # Closest-producer bypass, signed/unsigned comparisons and taken/not-taken
    # next-PC selection. This same binary runs on frozen and new CPU models.
    li t0,-1
    li t1,1
    blt t0,t1,4f
    j fail
4:  bgeu t0,t1,5f
    j fail
5:  bge t0,t1,fail
    bltu t0,t1,fail
    addi t0,t1,0
    beq t0,t1,6f
    j fail
6:  addi t0,t0,1
    addi t0,t0,1
    addi t0,t0,-1
    bne t0,t1,7f
    j fail
7:  li t2,2
    bne t0,t2,fail
    # Younger speculative EX may advance at an ADDR redirect, but its ADDR
    # owner must be discarded before a store, register write or trap escapes.
    li t0,0x17ac5e
    sd t0,0(sp)
    beq zero,zero,8f
    sd zero,0(sp)
    mul t0,t1,t2
    ebreak
8:  ld t3,0(sp)
    bne t3,t0,fail
    beq zero,zero,9f
    addi t0,zero,0
    sd zero,0(sp)
    ebreak
9:  ld t3,0(sp)
    bne t3,t0,fail
    la t0,done
    ori t0,t0,1
    jalr zero,t0,0
    j fail
    la t0,done
    jalr zero,t0,0
    sd zero,0(sp)
    .word 0xffffffff
done:
    li a0,0
    la t0,park
    csrw mtvec,t0
    ebreak
park:
    j park
fail:
    li a0,1
    ebreak
    .balign 64
target:
    addi a0,a0,1
    ret
