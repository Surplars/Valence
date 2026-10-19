.option rvc
.option norelax
.section .text.start
.globl _start
_start:
    li sp, 0x80420000
    li s0, 0x80410000
    sd a0, 0(s0)
    sd a1, 8(s0)
    bnez a0, fail
    li t0, 0x80500000
    bne a1, t0, fail
    # A real S ECALL must be handled by the stock OpenSBI M trap handler.
    li a7, 0x10
    li a6, 0
    ecall
    bnez a0, fail
    sd a1, 16(s0)
    srli t0, a1, 24
    li t1, 3
    bne t0, t1, fail
    li a7, 0x10
    li a6, 3
    li a0, 0x54494d45
    ecall
    bnez a0, fail
    beqz a1, fail
    sd a1, 24(s0)
    # LR/SC and AMO execute under the domain PMP configured by OpenSBI, not host bypasses.
    li s1, 0x80411000
    sd zero, 0(s1)
    lr.d.aq t0, (s1)
    bnez t0, fail
    li t0, 7
    sc.d.rl t1, t0, (s1)
    bnez t1, fail
    li t0, 5
    amoadd.d.aqrl t1, t0, (s1)
    li t2, 7
    bne t1, t2, fail
    ld t1, 0(s1)
    li t2, 12
    bne t1, t2, fail
    sd t1, 32(s0)
    sd zero, 40(s0)
    la t0, timer_handler
    csrw stvec, t0
    li t0, 32
    csrw sie, t0
    csrsi sstatus, 2
    rdtime a0
    addi a0, a0, 1024
    li a7, 0x54494d45
    li a6, 0
    ecall
    bnez a0, fail
    li t3, 100000
1:  ld t0, 40(s0)
    bnez t0, 2f
    addi t3, t3, -1
    bnez t3, 1b
    j fail
2:  csrw sie, zero
    csrci sstatus, 2
    # Debug-console write-byte is the standard SBI v3 DBCN, not a fake host console.
    la s2, message
3:  lbu a0, 0(s2)
    beqz a0, done
    li a7, 0x4442434e
    li a6, 2
    ecall
    bnez a0, fail
    addi s2, s2, 1
    j 3b
done:
    fence rw, rw
    li t0, 0x534d4f4445504153
    sd t0, 48(s0)
4:  j 4b
.balign 4
timer_handler:
    csrr t0, scause
    li t1, 0x8000000000000005
    bne t0, t1, fail
    li t0, 1
    sd t0, 40(s0)
    li t0, 32
    csrc sie, t0
    sret
fail:
    li t0, 0xbad
    sd t0, 48(s0)
5:  j 5b
message:
    .asciz "ORBITAL_I1_OPENSBI_S_MODE_PASS\r\n"
