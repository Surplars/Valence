/* Separate replay ROM. The archived diagnostic is never rebuilt or patched. */
.option norvc
.option norelax
.section .text,"ax"
.globl launcher_start, launcher_returned, launcher_done, launcher_fail
launcher_start:
    lui t0, 0x10000
    li t1, 7
    sb t1, 2(t0)              /* Same UART FIFO initialization as board fixtures. */
    la t0, diagnostic_entry
    ld t0, 0(t0)
    jalr ra, 0(t0)            /* Original _start saves/restores this return PC. */
launcher_returned:
    bnez a0, launcher_fail
    fence rw,rw
    fence.i                  /* Only after the entire diagnostic returned. */
    fence rw,rw
launcher_done:
    j launcher_done
launcher_fail:
    j launcher_fail
.balign 8
diagnostic_entry:
    .dword 0xfff78000
