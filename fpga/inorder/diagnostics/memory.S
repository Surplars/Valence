.option norvc
.text
.balign 4
.globl stream_read
stream_read:
    add a1,a0,a1
    li a2,0
    li a3,0
    li a4,0
    li a5,0
1:  ld t0,0(a0)
    ld t1,8(a0)
    ld t2,16(a0)
    ld t3,24(a0)
    ld t4,32(a0)
    ld t5,40(a0)
    ld t6,48(a0)
    ld a6,56(a0)
    add a2,a2,t0
    add a3,a3,t1
    add a4,a4,t2
    add a5,a5,t3
    add a2,a2,t4
    add a3,a3,t5
    add a4,a4,t6
    add a5,a5,a6
    addi a0,a0,64
    bltu a0,a1,1b
    add a0,a2,a3
    add a4,a4,a5
    add a0,a0,a4
    ret
.globl stream_write
stream_write:
    add a1,a0,a1
1:  addi t0,a2,1
    addi t1,a2,2
    addi t2,a2,3
    addi t3,a2,4
    addi t4,a2,5
    addi t5,a2,6
    addi t6,a2,7
    sd a2,0(a0)
    sd t0,8(a0)
    sd t1,16(a0)
    sd t2,24(a0)
    sd t3,32(a0)
    sd t4,40(a0)
    sd t5,48(a0)
    sd t6,56(a0)
    addi a2,a2,8
    addi a0,a0,64
    bltu a0,a1,1b
    ret
.globl stream_copy
stream_copy:
    add a2,a1,a2
1:  ld t0,0(a1)
    ld t1,8(a1)
    ld t2,16(a1)
    ld t3,24(a1)
    ld t4,32(a1)
    ld t5,40(a1)
    ld t6,48(a1)
    ld a3,56(a1)
    sd t0,0(a0)
    sd t1,8(a0)
    sd t2,16(a0)
    sd t3,24(a0)
    sd t4,32(a0)
    sd t5,40(a0)
    sd t6,48(a0)
    sd a3,56(a0)
    addi a0,a0,64
    addi a1,a1,64
    bltu a1,a2,1b
    ret
.globl scalar_copy
scalar_copy:
    add a2,a1,a2
1:  ld t0,0(a1)
    sd t0,0(a0)
    addi a0,a0,8
    addi a1,a1,8
    bltu a1,a2,1b
    ret
