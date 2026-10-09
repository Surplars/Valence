#include "mmu_diagnostic.h"
.option norvc
.option norelax
.section .text.mmu_diagnostic_enter,"ax"
.balign 4
.globl mmu_diagnostic_enter
mmu_diagnostic_enter:
    addi sp, sp, -144
    sd a0, 0(sp)
    sd ra, 8(sp)
    sd gp, 16(sp)
    sd tp, 24(sp)
    sd s0, 32(sp)
    sd s1, 40(sp)
    sd s2, 48(sp)
    sd s3, 56(sp)
    sd s4, 64(sp)
    sd s5, 72(sp)
    sd s6, 80(sp)
    sd s7, 88(sp)
    sd s8, 96(sp)
    sd s9, 104(sp)
    sd s10, 112(sp)
    sd s11, 120(sp)
    csrw mscratch, sp
    la t0, mmu_diagnostic_trap
    csrw mtvec, t0
    ld t0, MMU_SATP(a0)
    csrw satp, t0
    sfence.vma x0, x0
    la t0, mmu_diagnostic_supervisor_entry
    csrw mepc, t0
    /* Clear MPRV, MPP, MIE, SIE, MPIE; mret really enters S mode. */
    csrr t0, mstatus
    li t1, 0x2188a
    not t1, t1
    and t0, t0, t1
    li t1, 0x800
    or t0, t0, t1
    csrw mstatus, t0
    ld sp, MMU_STACK(a0)
    mret
.balign 4
.globl mmu_diagnostic_supervisor_entry
mmu_diagnostic_supervisor_entry:
    call mmu_diagnostic_supervisor
.globl mmu_diagnostic_return_ecall
mmu_diagnostic_return_ecall:
    ecall
1:  j 1b
.balign 4
mmu_diagnostic_trap:
    /* Never trust the faulting S stack; mscratch owns the saved M frame. */
    csrrw sp, mscratch, sp
    csrw mie, zero
    ld t0, 0(sp)
    csrr t1, mcause
    sd t1, MMU_CAUSE(t0)
    csrr t1, mtval
    sd t1, MMU_TVAL(t0)
    csrr t1, mepc
    sd t1, MMU_EPC(t0)
    csrr t1, mscratch
    sd t1, MMU_TRAP_SP(t0)
    sd a0, MMU_RETURN(t0)
    csrw satp, zero
    sfence.vma x0, x0
    ld ra, 8(sp)
    ld gp, 16(sp)
    ld tp, 24(sp)
    ld s0, 32(sp)
    ld s1, 40(sp)
    ld s2, 48(sp)
    ld s3, 56(sp)
    ld s4, 64(sp)
    ld s5, 72(sp)
    ld s6, 80(sp)
    ld s7, 88(sp)
    ld s8, 96(sp)
    ld s9, 104(sp)
    ld s10, 112(sp)
    ld s11, 120(sp)
    addi sp, sp, 144
    /* M-mode trap handler returns to its original M-mode caller, not via mret. */
    ret
