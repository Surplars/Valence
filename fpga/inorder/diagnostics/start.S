.option norvc
.option norelax
.section .text.start,"ax"
.globl _start
_start:
    csrw mie,zero
    csrw mstatus,zero
    csrw satp,zero
    sfence.vma
    la gp,__global_pointer$
    la sp,_stack_top
    la t0,trap_entry
    csrw mtvec,t0
    la t0,_bss_start
    la t1,_bss_end
1:  bgeu t0,t1,2f
    sd zero,0(t0)
    addi t0,t0,8
    j 1b
2:  csrw mcountinhibit,zero
    li t0,7
    csrw mcounteren,t0
    li t0,0x40080000
    csrw pmpaddr0,t0
    li t0,0xf
    csrw pmpcfg0,t0
    call main
.globl diag_halt
diag_halt:
    ebreak
    j diag_halt

.text
.balign 4
.globl run_supervisor
run_supervisor:
    addi sp,sp,-112
    sd ra,0(sp)
    sd s0,8(sp)
    sd s1,16(sp)
    sd s2,24(sp)
    sd s3,32(sp)
    sd s4,40(sp)
    sd s5,48(sp)
    sd s6,56(sp)
    sd s7,64(sp)
    sd s8,72(sp)
    sd s9,80(sp)
    sd s10,88(sp)
    sd s11,96(sp)
    csrw mscratch,sp
    la t0,supervisor_active
    li t1,1
    sd t1,0(t0)
    la t0,3f
    csrw mepc,t0
    csrr t0,mstatus
    li t1,0x21808
    not t1,t1
    and t0,t0,t1
    li t1,0x800
    or t0,t0,t1
    csrw mstatus,t0
    mret
3:  jalr a0
    ecall
    j 3b
.balign 4
.globl trap_entry
trap_entry:
    csrr a0,mcause
    csrr a1,mepc
    csrr a2,mtval
    la t0,trap_cause
    sd a0,0(t0)
    la t0,trap_pc
    sd a1,0(t0)
    la t0,trap_value
    sd a2,0(t0)
    la t0,supervisor_active
    ld t1,0(t0)
    beqz t1,fatal_trap
    sd zero,0(t0)
    csrr sp,mscratch
    li t0,9
    xor a0,a0,t0
    snez a0,a0
    la t0,4f
    csrw mepc,t0
    csrr t0,mstatus
    li t1,0x1800
    or t0,t0,t1
    csrw mstatus,t0
    mret
4:  ld ra,0(sp)
    ld s0,8(sp)
    ld s1,16(sp)
    ld s2,24(sp)
    ld s3,32(sp)
    ld s4,40(sp)
    ld s5,48(sp)
    ld s6,56(sp)
    ld s7,64(sp)
    ld s8,72(sp)
    ld s9,80(sp)
    ld s10,88(sp)
    ld s11,96(sp)
    addi sp,sp,112
    ret
