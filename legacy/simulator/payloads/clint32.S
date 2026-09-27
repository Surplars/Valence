.section .text.init
.globl _start

_start:
    li   t0, 0x10010000
    li   t1, 'C'
    sb   t1, 0(t0)

    # Program mtimecmp using two 32-bit stores. The high-word write at
    # mtimecmp+4 must decode to the same 64-bit CLINT register beat.
    li   t2, 0x2004000
    li   t3, -1
    sw   t3, 0(t2)
    sw   zero, 4(t2)

    lw   t4, 0(t2)
    bne  t4, t3, fail_low
    lw   t4, 4(t2)
    bne  t4, zero, fail_high

    # Move compare close enough to trigger, again through 32-bit stores.
    li   t2, 0x200BFF8
    lw   t5, 0(t2)
    addi t5, t5, 100
    li   t2, 0x2004000
    sw   t5, 0(t2)
    sw   zero, 4(t2)

wait_mtip:
    li   t2, 0x200BFF8
    lw   t6, 0(t2)
    bltu t6, t5, wait_mtip

pass:
    li   t0, 0x10010000
    li   t1, 'P'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 0
done:
    j    done

fail_low:
    li   t0, 0x10010000
    li   t1, 'L'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
fail_low_spin:
    j    fail_low_spin

fail_high:
    li   t0, 0x10010000
    li   t1, 'H'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
fail_spin:
    j    fail_spin
