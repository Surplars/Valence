/* Dedicated assembly page-sweep, not production GCC C binary. One image on both sides: host supplies mode/op/bytes/reps before boot.
 * Both Bare and Sv39 execute the actual S-mode CPU; code VA is identity mapped.
 * Retired NOP markers exclude warmup; fences and dirty writeback tails are separate.
 */
.option norvc
.section .text.start,"ax",@progbits
.globl _start
_start:
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 31
    csrw pmpcfg0, t0
    la t0, trap_stop
    csrw mtvec, t0
    li t0, 0x80600000
    ld s4, 0(t0)                 /* 0=Bare, 1=Sv39 */
    ld s5, 8(t0)                /* 0=READ, 1=WRITE, 2=COPY */
    ld s6, 16(t0) /* number of selected pages */
    ld s7, 24(t0)
    li s0, 0x80400000
    li s1, 0x81400000
    beqz s4, 1f
    li s0, 0x40000000
    li s1, 0x41000000
    li t0, 0x8000000000080300
    csrw satp, t0
1:  sfence.vma x0, x0
    la t0, supervisor_start
    csrw mepc, t0
    li t0, (1 << 11)
    csrw mstatus, t0
    mret
supervisor_start:
    mv s10, s0
    mv s11, s1
    /* Warm identical code and data before measuring; streaming buffers exceed
     * L1 at 64KiB and remain cache resident in the 4KiB control. */
    li s3, 1
    jal ra, kernel
    fence rw, rw
    li a0, 0
.globl bw_begin
bw_begin:
    nop
    fence rw, rw
    mv s3, s7
    jal ra, kernel
.globl bw_end
bw_end:
    nop
    fence rw, rw
.globl bw_drain
bw_drain:
    nop
    /* Store signature before the final cache clean so backing RAM is checked. */
    li t0, 0x80600020
    sd a0, 0(t0)
    fence.i
    fence rw, rw
.globl bw_done
bw_done:
    nop
    ecall
trap_stop:
    j trap_stop
kernel:
    mv s0, s10
    mv s1, s11
    mv s2, s6
    li t2, 4160
    beqz s5, read_loop
    li t0, 1
    beq s5, t0, write_loop
copy_loop:
    .irp offset,0
    ld t0, \offset(s0)
    sd t0, \offset(s1)
    .endr
    add s0, s0, t2
    add s1, s1, t2
    addi s2, s2, -1
    bnez s2, copy_loop
    j kernel_next
read_loop:
    .irp offset,0
    ld t0, \offset(s0)
    add a0, a0, t0
    .endr
    add s0, s0, t2
    addi s2, s2, -1
    bnez s2, read_loop
    j kernel_next
write_loop:
    li t0, 0x5a170000
    .irp offset,0
    sd t0, \offset(s1)
    .endr
    add s1, s1, t2
    addi s2, s2, -1
    bnez s2, write_loop
kernel_next:
    addi s3, s3, -1
    bnez s3, kernel
    ret
