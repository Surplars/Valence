.option norvc
.option norelax
.section .boot,"ax"
.globl _start
_start:
    csrw mie, zero
    li t0, 0x20008
    csrc mstatus, t0
    la t0, .Lboot_trap
    csrw mtvec, t0
    la t0, __stage_load_start
    la t1, __stage_start
    la t2, __stage_load_end
.Lcopy:
    bgeu t0, t2, .Lcopied
    ld t3, 0(t0)
    sd t3, 0(t1)
    addi t0, t0, 8
    addi t1, t1, 8
    j .Lcopy
.Lcopied:
    fence rw,rw
    fence.i
    la t0, stage_start
    jr t0
.balign 4
.Lboot_trap:
    csrw mie, zero
    j .Lboot_trap

.section .text.stage_start,"ax"
.globl stage_start
stage_start:
    la sp, __stage_stack_top
    la gp, __global_pointer$
    la t0, stage_trap
    csrw mtvec, t0
    la t0, __stage_bss_start
    la t1, __stage_bss_end
.Lbss:
    bgeu t0,t1,.Lmain
    sb zero,0(t0)
    addi t0,t0,1
    j .Lbss
.Lmain:
    call stage_main
    j stage_trap
.balign 4
.globl stage_trap
stage_trap:
    csrw mie,zero
    j stage_trap

.globl stage_launch
stage_launch:
    # RV64 psABI sign-extends uint32_t arguments. Entry is a physical u32.
    slli t0,a0,32
    srli t0,t0,32
    csrw mie,zero
    li t1,0x20008
    csrc mstatus,t1
    csrw satp,zero
    csrw pmpcfg0,zero
    csrw pmpcfg2,zero
    li a0,0
    li a1,0
    la ra,stage_trap
    fence rw,rw
    fence.i
    jr t0
