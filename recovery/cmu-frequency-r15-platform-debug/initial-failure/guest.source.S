# Real I1 guest: arm RAM-loader using the CPU scalar MMIO path, read its
# control/status on every iteration, and independently check persistent RAM.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, control_open, control_read, control_generation, configured
.globl loop_previous, loop_previous_compare, loop_increment, loop_store, loop_load
.globl loop_compare, loop_control, loop_jump, guest_fail
_start:
    li s0, 0x80200000
    li s1, 0x10003000
    li t0, 1
control_open:
    sd t0, 8(s1)
control_read:
    ld s2, 0(s1)
control_generation:
    ld s3, 40(s1)
    li s4, 0
    sd s4, 0(s0)
configured:
loop_previous:
    ld s7, 0(s0)
loop_previous_compare:
    bne s4, s7, guest_fail
loop_increment:
    addi s4, s4, 1
loop_store:
    sd s4, 0(s0)
loop_load:
    ld s5, 0(s0)
loop_compare:
    bne s4, s5, guest_fail
loop_control:
    ld s6, 0(s1)
loop_jump:
    j loop_previous
guest_fail:
    ebreak
    j guest_fail
