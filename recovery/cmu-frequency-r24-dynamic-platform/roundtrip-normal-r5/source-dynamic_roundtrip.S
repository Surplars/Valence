# Real I1 guest. No request/token/ACK is injected. All rate writes are eight-byte
# aligned SD through the ordinary CPU/Home/MMIO path and the real reply CDC.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, guest_done, guest_fail
_start:
    li s0, 0x10080800
    li s1, 50000000
    li s2, 100000000
    li s3, 0
boot_wait:
    ld t0, 8(s0)
    bne t0, s1, boot_wait
    ld t0, 88(s0)
    bnez t0, boot_wait
    li s4, 1
    sd s2, 0(s0)
wait_up:
    ld t0, 80(s0)
    bne t0, s4, wait_up
    ld t0, 24(s0)
    bnez t0, guest_fail
    ld t0, 8(s0)
    bne t0, s2, guest_fail
    li s4, 2
    sd s1, 0(s0)
wait_down:
    ld t0, 80(s0)
    bne t0, s4, wait_down
    ld t0, 24(s0)
    bnez t0, guest_fail
    ld t0, 8(s0)
    bne t0, s1, guest_fail
    bnez s3, guest_done
    addi s0, s0, 128
    li s3, 1
    j boot_wait
guest_done:
    j guest_done
guest_fail:
    j guest_fail
