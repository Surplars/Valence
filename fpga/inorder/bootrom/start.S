/* Stackless RV64I/Zicsr/Zifencei boot. Local addresses are PC-relative.
 * M mode, mie/MIE=0, a0=mhartid, a1=0; guest initializes sp/gp and mtvec.
 */
.section .text.start
.globl _start
_start:
    csrw mie, zero
    csrw mstatus, zero
    la t0, fault
    csrw mtvec, t0
    li s0, 0x10002000
    ld s1, 8(s0)
    li s2, 0x10003000
    ld t0, 0(s0)
    andi t0, t0, 8
    beqz t0, wait_ddr
    li a2, 0x10000000
    la a3, banner
    jal puts
wait_ddr:
    ld t0, 0(s0)
    andi t1, t0, 4
    bnez t1, fault
    andi t1, t0, 1
    beqz t1, wait_ddr
    andi t1, t0, 2
    bnez t1, wait_link
    mv s4, s1
    j launch
wait_link:
    ld t0, 0(s2)
    andi t1, t0, 32
    beqz t1, wait_link
    li t0, 1
    sd t0, 8(s2)
wait_commit:
    ld t0, 0(s2)
    andi t1, t0, 4
    bnez t1, wait_link
    andi t1, t0, 2
    beqz t1, wait_commit
    ld s4, 16(s2)
    ld s5, 24(s2)
    ld s6, 32(s2)
    ld s3, 40(s2)
    li s7, 0xffffffff
    li s8, 0xedb88320
    mv t3, s1
    mv t4, s5
crc_byte:
    lbu t0, 0(t3)
    xor s7, s7, t0
    li t2, 8
crc_bit:
    andi t1, s7, 1
    srli s7, s7, 1
    beqz t1, crc_next
    xor s7, s7, s8
crc_next:
    addi t2, t2, -1
    bnez t2, crc_bit
    addi t3, t3, 1
    addi t4, t4, -1
    bnez t4, crc_byte
    xori s7, s7, -1
    slli s7, s7, 32
    srli s7, s7, 32
    bne s7, s6, reject
    slli t0, s3, 32
    ori t0, t0, 3
    sd t0, 8(s2)
    ld t0, 0(s2)
    andi t0, t0, 64
    beqz t0, fault
launch:
    fence rw, rw
    fence.i
    csrr a0, mhartid
    li a1, 0
    la ra, fault
    jr s4
reject:
    li t0, 2
    sd t0, 8(s2)
    j wait_link
fault:
    j fault
puts:
    lbu t0, 0(a3)
    beqz t0, puts_done
puts_ready:
    lbu t1, 5(a2)
    andi t1, t1, 32
    beqz t1, puts_ready
    sb t0, 0(a2)
    addi a3, a3, 1
    j puts
puts_done:
    ret
.section .rodata
banner: .asciz "Valence Orbital-I1 BootROM V0.1\r\n"
