/* Same ELF for precheck off/on. M-mode code, Sv39 S-effective data via MPRV.
 * Host initializes independently specified page tables/data before reset release.
 * No stack, timer, UART output, or host-controlled memory latency in the ROI.
 */
.option norvc
.section .text.start,"ax",@progbits
.globl _start
_start:
    la t0, trap_handler
    csrw mtvec, t0
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 0x1f
    csrw pmpcfg0, t0
    li s0, 0x40000000
    li s10, 0x80600000
    li s7, 0
    li t0, 0x8000000000080300
    csrw satp, t0
    sfence.vma zero, zero
    li t0, 0x20800
    csrw mstatus, t0

    /* Warm this exact load kernel, its DTLB entry and its L1 line. */
    li s1, 1
    jal ra, warm_kernel
    fence rw, rw
.globl warm_begin
warm_begin:
    nop
    li s1, 64
    jal ra, warm_kernel
    fence rw, rw
.globl warm_end
warm_end:
    nop

    /* Four new VA pages and new physical cache lines, no artificial flush/hold. */
    fence rw, rw
.globl cold_begin
cold_begin:
    nop
    li t1, 0x40002000
    ld a1, 0(t1)
    li t1, 0x40003000
    ld a2, 0(t1)
    li t1, 0x40004000
    ld a3, 0(t1)
    li t1, 0x40005000
    ld a4, 0(t1)
    add s4, a1, a2
    add s4, s4, a3
    add s4, s4, a4
    fence rw, rw
.globl cold_end
cold_end:
    nop

    /* Populate all 64 linked-list lines and warm the dependent-load code first. */
    li s1, 64
    jal ra, chase_kernel
    fence rw, rw
.globl chase_begin
chase_begin:
    nop
    li s1, 256
    jal ra, chase_kernel
    fence rw, rw
.globl chase_end
chase_end:
    nop

    /* Warm a device translation, never its data cache. Only this LSR read is legal. */
    li t5, 0x40007000
.globl allowed_mmio_load
allowed_mmio_load:
    lbu t1, 5(t5)
    li s11, 0x123
    fence rw, rw
.globl cancel_begin
cancel_begin:
    nop
    /* Cold line / warm TLB lets the younger safe RAM load overlap an unresolved branch. */
    ld t0, 0x300(s0)
.globl cancel_branch
cancel_branch:
    beq t0, t0, cancel_target
.globl wrong_path_begin
wrong_path_begin:
    ld s11, 0(s0)
    lbu t1, 5(t5)
    li s11, 0xbad
.globl wrong_path_end
wrong_path_end:
.globl cancel_target
cancel_target:
    li t0, 0x123
    bne s11, t0, fail

    /* Fault has a distinct VA from every physical address in this image. */
    li t0, 0x40008000
.globl fault_load
fault_load:
    ld a0, 0(t0)
    j fail
.globl fault_resume
fault_resume:
    /* mret changes MPP; restore MPRV/S before the next data access. */
    li t0, 0x20800
    csrw mstatus, t0
    li t0, 0x40006000
    li t1, 0x99
    sd t1, 0(t0)
    ld s6, 0(s0)
    bne s6, t1, fail

    /* Physical signatures are checked by the host only after the real cache/fabric drain. */
    csrw mstatus, zero
    li t0, 0x564952544c4f4144
    sd t0, 0(s10)
    sd s3, 8(s10)
    sd s4, 16(s10)
    sd s5, 24(s10)
    sd s11, 32(s10)
    sd s7, 40(s10)
    sd s6, 72(s10)
    fence rw, rw
    fence.i
.globl done
done:
    nop
    j done
.globl fail
fail:
    nop
    j fail

.align 6
warm_kernel:
    li s3, 0
1:
    ld a1, 0(s0)
    ld a2, 8(s0)
    ld a3, 16(s0)
    ld a4, 24(s0)
    ld a5, 32(s0)
    ld a6, 40(s0)
    ld a7, 48(s0)
    ld t0, 56(s0)
    add s3, s3, a1
    add s3, s3, a2
    add s3, s3, a3
    add s3, s3, a4
    add s3, s3, a5
    add s3, s3, a6
    add s3, s3, a7
    add s3, s3, t0
    addi s1, s1, -1
    bnez s1, 1b
    ret

.align 6
chase_kernel:
    li t0, 0x40001000
2:
    ld t0, 0(t0)
    addi s1, s1, -1
    bnez s1, 2b
    mv s5, t0
    ret

.align 6
.globl trap_handler
trap_handler:
    csrr t0, mcause
    li t1, 13
    bne t0, t1, fail
    csrr t2, mtval
    li t1, 0x40008000
    bne t2, t1, fail
    csrr t3, mepc
    la t4, fault_load
    bne t3, t4, fail
    /* Trap entry makes effective data privilege M until mret. */
    sd t0, 48(s10)
    sd t2, 56(s10)
    sd t3, 64(s10)
    addi s7, s7, 1
    la t4, fault_resume
    csrw mepc, t4
    mret
