.section .text.init
.globl _start

_start:
    la   t0, msg          # t0 = address of message
    li   t1, 0x10010000   # t1 = UART TX base address
    li   t2, 0            # t2 = char counter

loop:
    lbu  t3, 0(t0)        # load next char
    beqz t3, pass         # if null terminator, done

    sb   t3, 0(t1)        # send char to UART TX
    #addi t2, t2, 1       # uncomment to count chars printed

    addi t0, t0, 1        # advance pointer
    j    loop

pass:
    # Send newline
    li   t3, 0x0a         # '\n'
    sb   t3, 0(t1)

    li   a7, 93           # exit syscall
    li   a0, 0            # return 0
spin:
    j    spin

fail:
    slli gp, gp, 1
    ori  gp, gp, 1
    li   a7, 93
    mv   a0, gp
    j    fail

trap_vector:
    j    fail

.section .rodata
msg:
    .ascii "Hello, World!"
    .byte 0
