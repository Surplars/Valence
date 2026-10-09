.option norvc
.option norelax
.section .text.mmu_diagnostic_supervisor,"ax"
.balign 4
.globl mmu_diagnostic_supervisor
mmu_diagnostic_supervisor:
    /* All run-descriptor reads occur before warmup. No stack access anywhere. */
    ld a1,56(a0)
    ld a2,72(a0)
    ld a3,80(a0)
    ld t5,88(a0)
    li t3,4
1:  mv a5,a1
    mv a6,a2
.globl alias_warm_load
alias_warm_load:
    ld t0,0(a5)
    add a5,a5,t5
    addi a6,a6,-1
    bnez a6,alias_warm_load
    addi t3,t3,-1
    bnez t3,1b
    li a4,0
    mv a7,a3
    fence rw,rw
.globl alias_roi_begin
alias_roi_begin:
    rdtime t1
2:  mv a5,a1
    mv a6,a2
.globl alias_timed_load
alias_timed_load:
    ld t0,0(a5)
    add a4,a4,t0
    add a5,a5,t5
    addi a6,a6,-1
    bnez a6,alias_timed_load
    addi a7,a7,-1
    bnez a7,2b
    fence rw,rw
.globl alias_roi_end
alias_roi_end:
    rdtime t2
    sub t2,t2,t1
    /* Results only after the closing timestamp. */
    sd t2,104(a0)
    sd zero,112(a0)
    sd a4,120(a0)
    ret
