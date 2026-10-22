# Independent architectural atomic oracle; no synthetic memory responses.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, amo_d, check_d, lr_d, sc_d, check_sc, amo_w, check_w, guest_done, guest_fail
_start:
    li s0, 0x80200000
    li s4, 7
    sd s4, 0(s0)
    li s4, 5
amo_d:
    amoadd.d s7, s4, (s0)
    li t0, 7
    bne s7, t0, guest_fail
check_d:
    ld s5, 0(s0)
    li t0, 12
    bne s5, t0, guest_fail
    li s4, 99
lr_d:
    lr.d s5, (s0)
sc_d:
    sc.d s6, s4, (s0)
    li t0, 1
    bne s6, t0, guest_fail
check_sc:
    ld s7, 0(s0)
    li t0, 12
    bne s7, t0, guest_fail
    li s4, 0x800000013456789a
    sd s4, 8(s0)
    addi s1, s0, 12
    li s4, 2
amo_w:
    amoadd.w s5, s4, (s1)
    li t0, -2147483647
    bne s5, t0, guest_fail
check_w:
    ld s6, 8(s0)
    li t0, 0x800000033456789a
    bne s6, t0, guest_fail
guest_done:
    j guest_done
guest_fail:
    ebreak
    j guest_fail
