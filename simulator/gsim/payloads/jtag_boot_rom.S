/* Minimal ROM-side policy. No firmware C/CRC claim: CRC is a frozen metadata token. */
.option norvc
.option norelax
.section .text
.globl _start
_start:
    li s0, 0x10003000
    li s1, 0x80020000
    jalr ra, s1, 0
    li t0, 0x111
    bne s10, t0, fail
    lwu t1, 64(s1)
    li t0, 0x11223344
    bne t1, t0, fail
    li t0, 0x55667788
    sd t0, 128(s1)
    li s11, 0x101
    li t0, 1
    sd t0, 8(s0)
.globl poll
poll:
    ld t0, 0(s0)
    andi t0, t0, 2
    beqz t0, poll
    ld s2, 40(s0)
    li t0, 1
    bne s2, t0, fail
    ld s3, 16(s0)
    bne s3, s1, fail
    ld s4, 24(s0)
    li t0, 192
    bne s4, t0, fail
    ld s5, 32(s0)
    li t0, 0x12345678
    bne s5, t0, fail
    ld t0, 48(s0)
    bne t0, s1, fail
    ld t0, 56(s0)
    li t1, 0x8009c000
    bne t0, t1, fail
    fence rw, rw
    slli t0, s2, 32
    ori t0, t0, 3
    sd t0, 8(s0)
    ld t0, 0(s0)
    andi t0, t0, 0x43
    li t1, 0x40
    bne t0, t1, fail
    ld t0, 16(s0)
    bne t0, s3, fail
    ld t0, 24(s0)
    bne t0, s4, fail
    ld t0, 32(s0)
    bne t0, s5, fail
    ld t0, 40(s0)
    bne t0, s2, fail
.globl visibility_fence
visibility_fence:
    fence.i
    jr s3
fail:
    li s11, 0xbad
1:  j 1b
