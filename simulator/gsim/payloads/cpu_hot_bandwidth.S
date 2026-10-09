/* Integer M-mode, physical addresses, no stack or UART. Host provides initial
 * RAM words independently; one load per line warms both bounded buffers.
 * NOP retirement markers avoid rdtime's implicit memory-drain serialization.
 */
.option norvc
.section .text.start,"ax",@progbits
.globl _start
_start:
    li s0, 0x80400000
    li s1, 0x80402000
    li s2, HOT_BYTES / 64
1:  ld t0, 0(s0)
    ld t1, 0(s1)
    addi s0, s0, 64
    addi s1, s1, 64
    addi s2, s2, -1
    bnez s2, 1b
    fence rw, rw
    li s8, 0
    li s9, 0
    li s10, 0
    li s11, 0
    /* One untimed pass warms the exact kernel instructions and branch path. */
    li s3, 1
    jal ra, hot_kernel
    fence rw, rw
    li s8, 0
    li s9, 0
    li s10, 0
    li s11, 0
.globl hot_begin
hot_begin:
    nop
    /* Keep the first accepted operation after the retirement marker. */
    fence rw, rw
    li s3, HOT_REPS
    jal ra, hot_kernel
.globl hot_kernel_end
hot_kernel_end:
    nop
    fence rw, rw
.globl hot_drain_end
hot_drain_end:
    nop
    fence.i
    fence rw, rw
.globl hot_complete_end
hot_complete_end:
    nop
    add s8, s8, s9
    add s10, s10, s11
    add s8, s8, s10
    li s0, 0x80600000
    sd s8, 0(s0)
    li t0, HOT_BYTES
    sd t0, 8(s0)
    li t0, HOT_OP
    sd t0, 16(s0)
    li t0, HOT_REPS
    sd t0, 24(s0)
    fence rw, rw
    fence.i
    fence rw, rw
.globl hot_done
hot_done:
    nop
    j hot_done
.globl hot_kernel
hot_kernel:
2:  li s0, 0x80400000
    li s1, 0x80402000
    li s2, HOT_BYTES / 64
#if HOT_OP == 1
    li t0, 0x5a170000
    li t1, 0x5a170001
    li t2, 0x5a170002
    li t3, 0x5a170003
    li t4, 0x5a170004
    li t5, 0x5a170005
    li t6, 0x5a170006
    li a0, 0x5a170007
#endif
3:
#if HOT_OP != 1
    ld t0, 0(s0)
    ld t1, 8(s0)
    ld t2, 16(s0)
    ld t3, 24(s0)
    ld t4, 32(s0)
    ld t5, 40(s0)
    ld t6, 48(s0)
    ld a0, 56(s0)
#endif
#if HOT_OP != 0
    sd t0, 0(s1)
    sd t1, 8(s1)
    sd t2, 16(s1)
    sd t3, 24(s1)
    sd t4, 32(s1)
    sd t5, 40(s1)
    sd t6, 48(s1)
    sd a0, 56(s1)
#endif
#if HOT_OP == 0
    add s8, s8, t0
    add s9, s9, t1
    add s10, s10, t2
    add s11, s11, t3
    add s8, s8, t4
    add s9, s9, t5
    add s10, s10, t6
    add s11, s11, a0
#elif HOT_OP == 1
    addi t0, t0, 8
    addi t1, t1, 8
    addi t2, t2, 8
    addi t3, t3, 8
    addi t4, t4, 8
    addi t5, t5, 8
    addi t6, t6, 8
    addi a0, a0, 8
#endif
    addi s0, s0, 64
    addi s1, s1, 64
    addi s2, s2, -1
    bnez s2, 3b
    addi s3, s3, -1
    bnez s3, 2b
    ret
.globl hot_image_end
hot_image_end:
