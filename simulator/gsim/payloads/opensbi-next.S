    .section .text.start, "ax"
    .globl _start
_start:
    li a7, 0x10                 # SBI base extension
    li a6, 0                    # get SBI specification version
    ecall
    li a2, 0x53424921          # visible only after an S-mode SBI round trip
    li t0, 0x10000000          # S-mode UART echo probe after the boot marker
1:  lbu t1, 5(t0)             # LSR data ready
    andi t1, t1, 1
    beqz t1, 1b
    lbu t2, 0(t0)             # RBR
2:  lbu t1, 5(t0)             # wait until THR can accept a byte
    andi t1, t1, 0x20
    beqz t1, 2b
    sb t2, 0(t0)              # THR
    j 1b
