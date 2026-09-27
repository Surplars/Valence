.option norvc
.option norelax
.section .text.start,"ax"
.globl _start, boot_done, supervisor_wait, boot_fail
_start:
    la t0, boot_fail
    csrw mtvec, t0
    la t0, supervisor_trap
    csrw stvec, t0

    # One unlocked NAPOT entry allows S-mode access to ROM, RAM and MMIO.
    li t0, -1
    csrw pmpaddr0, t0
    li t0, 0x1f
    csrw pmpcfg0, t0

    # Source 3 is the UART. The M root delegates it to child domain zero.
    li s0, 0x0c000000
    li t0, 0x400
    sw t0, 12(s0)
    li s1, 0x0c004000
    li t0, 4
    sw t0, 12(s1)
    li t0, 3
    li t1, 0x0c00700c
    sw t0, 0(t1)
    li t1, 0x0c005edc
    sw t0, 0(t1)
    li t0, 0x100
    sw t0, 0(s1)

    # S IMSIC delivery and identity 3 enable.
    li t0, 0x70
    csrw siselect, t0
    li t0, 1
    csrw sireg, t0
    li t0, 0xc0
    csrw siselect, t0
    li t0, 8
    csrw sireg, t0

    li s2, 0x10000000
    li t0, 3
    sb t0, 3(s2)
    li t0, 1
    sb t0, 1(s2)

    li t0, 0x200
    csrw mideleg, t0
    csrw sie, t0
    la t0, supervisor_wait
    csrw mepc, t0
    li t0, 0x800
    csrw mstatus, t0
    mret

supervisor_wait:
    csrsi sstatus, 2
1:  wfi
    j 1b

boot_fail:
    j boot_fail

.section .text.trap,"ax"
supervisor_trap:
    csrr t0, scause
    li t1, 0x8000000000000009
    bne t0, t1, boot_fail
    csrrw t0, stopei, zero
    li t1, 0x30003
    bne t0, t1, boot_fail
    lbu t0, 0(s2)
    li t1, 'Z'
    bne t0, t1, boot_fail
boot_done:
    j boot_done
