.section .text.init
.globl _start

_start:
    li   sp, 0x1000ff00
    la   s0, perf_data
    li   s1, 0x10010000

    csrw mcountinhibit, zero
    li   t0, 7
    csrw mhpmevent3, t0
    li   t0, 3
    csrw mhpmevent4, t0
    li   t0, 10
    csrw mhpmevent5, t0
    li   t0, 11
    csrw mhpmevent6, t0
    li   t0, 12
    csrw mhpmevent7, t0

    # NEMU models mhpmcounter/mhpmevent as read-only zero. Keep HPM counters
    # inhibited in difftest payloads so only IonSoC-local tests check events.
    li   t0, -8
    csrw mcountinhibit, t0
    csrw mhpmcounter3, zero
    csrw mhpmcounter4, zero
    csrw mhpmcounter5, zero
    csrw mhpmcounter6, zero
    csrw mhpmcounter7, zero

    li   t0, 0x0123456789abcdef
    sd   t0, 0(s0)
    sd   zero, 8(s0)
    fence

    li   t1, 4096
    li   t2, 0

loop:
    ld   t3, 0(s0)
    addi t3, t3, 1
    xor  t2, t2, t3
    sd   t3, 8(s0)
    ld   t4, 8(s0)
    add  t2, t2, t4
    addi t1, t1, -1
    bnez t1, loop

    csrr t0, minstret
    sd   t0, 16(s0)
    csrr t0, mhpmcounter3
    sd   t0, 24(s0)
    csrr t0, mhpmcounter4
    sd   t0, 32(s0)
    csrr t0, mhpmcounter5
    sd   t0, 40(s0)
    csrr t0, mhpmcounter6
    sd   t0, 48(s0)
    csrr t0, mhpmcounter7
    sd   t0, 56(s0)

    li   t5, 'P'
    sb   t5, 0(s1)
    li   a7, 93
    li   a0, 0
done:
    j    done

fail:
    li   t5, 'F'
    sb   t5, 0(s1)
    li   a7, 93
    li   a0, 1
fail_spin:
    j    fail_spin

.section .data
.align 3
perf_data:
    .dword 0
    .dword 0
    .dword 0
    .dword 0
    .dword 0
    .dword 0
    .dword 0
    .dword 0
