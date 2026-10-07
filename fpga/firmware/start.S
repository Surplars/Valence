.option norvc
.option norelax
.section .text.start,"ax"
.globl _start
_start:
    csrw mie, zero
    li t0, 0x20008
    csrc mstatus, t0
    csrw satp, zero
    csrw pmpcfg0, zero
    csrw pmpcfg2, zero
    la gp, __global_pointer$
    la sp, __boot_stack_top
    la t0, boot_trap
    csrw mtvec, t0
    la t0, __data_load
    la t1, __data_start
    la t2, __data_end
1:  bgeu t1, t2, 2f
    lbu t3, 0(t0)
    sb t3, 0(t1)
    addi t0, t0, 1
    addi t1, t1, 1
    j 1b
2:  la t0, __bss_start
    la t1, __bss_end
3:  bgeu t0, t1, 4f
    sb zero, 0(t0)
    addi t0, t0, 1
    j 3b
4:  call boot_main
5:  j 5b

.section .text,"ax"
.balign 4
.globl boot_trap
boot_trap:
    csrw mie, zero
    li t0, 0x20008
    csrc mstatus, t0
    csrw satp, zero
    csrw pmpcfg0, zero
    csrw pmpcfg2, zero
    la gp, __global_pointer$
    la sp, __boot_stack_top
    csrr a0, mcause
    csrr a1, mepc
    call boot_recover
1:  j 1b

.globl run_image
run_image:
    addi sp, sp, -128
    sd ra, 0(sp)
    sd gp, 8(sp)
    sd s0, 16(sp)
    sd s1, 24(sp)
    sd s2, 32(sp)
    sd s3, 40(sp)
    sd s4, 48(sp)
    sd s5, 56(sp)
    sd s6, 64(sp)
    sd s7, 72(sp)
    sd s8, 80(sp)
    sd s9, 88(sp)
    sd s10, 96(sp)
    sd s11, 104(sp)
    la t0, saved_boot_sp
    sd sp, 0(t0)
    csrw mie, zero
    li t0, 0x20008
    csrc mstatus, t0
    csrw satp, zero
    csrw pmpcfg0, zero
    csrw pmpcfg2, zero
    mv t0, a0
    la sp, __app_stack_top
    li a0, 0
    li a1, 0
    fence rw, rw
    fence.i
    jalr ra, t0, 0
    csrw mie, zero
    li t0, 0x20008
    csrc mstatus, t0
    csrw satp, zero
    csrw pmpcfg0, zero
    csrw pmpcfg2, zero
    la gp, __global_pointer$
    la t0, saved_boot_sp
    ld sp, 0(t0)
    la t0, boot_trap
    csrw mtvec, t0
    ld ra, 0(sp)
    ld gp, 8(sp)
    ld s0, 16(sp)
    ld s1, 24(sp)
    ld s2, 32(sp)
    ld s3, 40(sp)
    ld s4, 48(sp)
    ld s5, 56(sp)
    ld s6, 64(sp)
    ld s7, 72(sp)
    ld s8, 80(sp)
    ld s9, 88(sp)
    ld s10, 96(sp)
    ld s11, 104(sp)
    addi sp, sp, 128
    ret

.section .bss,"aw",@nobits
.balign 8
saved_boot_sp: .dword 0
