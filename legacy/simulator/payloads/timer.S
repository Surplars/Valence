.section .text.init
.globl _start

_start:
    # === Set up trap vector ===
    la   t0, trap_handler
    csrw mtvec, t0

    # === Enable timer interrupt ===
    li   t0, 0x80           # MTIE (bit 7)
    csrw mie, t0

    li   t0, 0x8            # MIE (bit 3)
    csrs mstatus, t0

    # === Set mtimecmp for first interrupt (500 cycles) ===
    li   t1, 0x200BFF8      # mtime
    ld   t0, 0(t1)
    li   t2, 500
    add  t0, t0, t2
    li   t1, 0x2004000      # mtimecmp
    sd   t0, 0(t1)

    # Init counter = 2 in mscratch (will count down)
    li   t0, 2
    csrw mscratch, t0

    # Print 'S' (started)
    li   t1, 0x10010000
    li   t2, 0x53
    sb   t2, 0(t1)

spin:
    j    spin

# === Trap Handler ===
.balign 4
trap_handler:
    # Decrement counter in mscratch
    csrr t0, mscratch
    addi t0, t0, -1
    csrw mscratch, t0

    # Print '!' for each interrupt
    li   t1, 0x10010000
    li   t2, 0x21           # '!'
    sb   t2, 0(t1)

    # Use jalr for computed jump: if counter==0, go to done
    # t1 = done, t2 = skip, select based on counter
    la   t1, done
    la   t2, set_next
    bnez t0, use_t2         # if counter != 0, use set_next
    jalr zero, t1, 0        # jump to done
use_t2:
    jalr zero, t2, 0        # jump to set_next

set_next:
    # Set next mtimecmp = mtime + 300
    li   t0, 0x200BFF8
    ld   t1, 0(t0)
    li   t2, 300
    add  t1, t1, t2
    li   t0, 0x2004000
    sd   t1, 0(t0)

    mret

done:
    # Print 'P' (pass)
    li   t0, 0x10010000
    li   t2, 0x50           # 'P'
    sb   t2, 0(t0)

    li   a7, 93
    li   a0, 0
trap_spin:
    j    trap_spin
