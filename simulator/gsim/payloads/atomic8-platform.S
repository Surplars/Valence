    .section .text.start,"ax"
    .globl _start
_start:
    li s0, 0x80011000
    li t0, 41
    sd t0, 0(s0)
    amoadd.d t1, t0, (s0)
    lr.d t2, (s0)
    sc.d t3, t0, (s0)
    ld t4, 0(s0)

    li s1, 0x80011ffc
    sw t0, 0(s1)
    amoadd.w t5, t0, (s1)
    lw t6, 0(s1)

    li s2, 0x80012000
    .globl atomic8_fault
atomic8_fault:
    amoadd.d a0, t0, (s2)
    j atomic8_fault
