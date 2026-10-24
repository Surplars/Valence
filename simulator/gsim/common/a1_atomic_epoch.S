# Independent architectural atomic oracle; no synthetic memory responses.
.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, amo_d, check_d, guest_done, guest_fail
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
guest_done:
    j guest_done
guest_fail:
    ebreak
    j guest_fail
