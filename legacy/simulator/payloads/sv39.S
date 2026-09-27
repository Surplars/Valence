.section .text.init
.globl _start

.equ UART_BASE,      0x10010000
.equ ROM_VA,         0x80000000
.equ EXEC_VA_BASE,   0x00200000
.equ DATA_VA_BASE,   0x40000000
.equ DATA_VA_OFFSET, 0x4000
.equ DATA_VA,        DATA_VA_BASE + DATA_VA_OFFSET
.equ PTE_V,          0x001
.equ PTE_R,          0x002
.equ PTE_W,          0x004
.equ PTE_X,          0x008
.equ PTE_A,          0x040
.equ PTE_D,          0x080
.equ SATP_MODE_SV39, 0x8000000000000000

_start:
    la   t0, fail
    csrw mtvec, t0
    la   t0, fail
    csrw stvec, t0

    # Permit S-mode access to the complete simulated physical address space.
    li   t0, -1
    csrw pmpaddr0, t0
    li   t0, 0x1f
    csrw pmpcfg0, t0

    # root[2] covers ROM VA 0x80000000 through a level-1 identity leaf.
    la   t0, l1_rom
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V
    la   t1, root_pt
    sd   t0, 16(t1)

    li   t0, ROM_VA
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V | PTE_R | PTE_X | PTE_A | PTE_D
    la   t1, l1_rom
    sd   t0, 0(t1)

    # root[0] maps EXEC_VA_BASE to the ROM physical superpage. Entering
    # S-mode through this non-identity VA proves the I-cache fetch path uses
    # Sv39 translation instead of treating the PC as a physical address.
    la   t0, l1_exec
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V
    la   t1, root_pt
    sd   t0, 0(t1)

    li   t0, ROM_VA
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V | PTE_R | PTE_X | PTE_A | PTE_D
    la   t1, l1_exec
    sd   t0, 8(t1)

    # root[1] maps S-mode data VA 0x40000000 to the physical SRAM superpage
    # containing sv39_data.
    la   t0, l1_data
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V
    la   t1, root_pt
    sd   t0, 8(t1)

    la   t0, sv39_data
    li   t2, -0x200000
    and  t0, t0, t2
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V | PTE_R | PTE_W | PTE_A | PTE_D
    la   t1, l1_data
    sd   t0, 0(t1)

    la   t0, root_pt
    srli t0, t0, 12
    li   t1, SATP_MODE_SV39
    or   t0, t0, t1
    csrw satp, t0
    sfence.vma x0, x0

    la   t0, supervisor_entry
    li   t1, ROM_VA
    sub  t0, t0, t1
    li   t1, EXEC_VA_BASE
    add  t0, t0, t1
    csrw mepc, t0
    li   t0, 0x800
    csrs mstatus, t0
    mret

supervisor_entry:
    li   t0, DATA_VA
    ld   t1, 0(t0)
    li   t2, 0x1122334455667788
    bne  t1, t2, fail_load

    li   t1, 0x8877665544332211
    sd   t1, 0(t0)
    ld   t4, 0(t0)
    bne  t4, t1, fail_store

pass:
    li   a7, 93
    li   a0, 0
pass_spin:
    j    pass_spin

fail:
    csrr t2, mcause
    li   t0, 5
    beq  t2, t0, fail_load_access
    li   t0, 7
    beq  t2, t0, fail_store_access
    li   t0, 13
    beq  t2, t0, fail_load_page
    li   t0, 15
    beq  t2, t0, fail_store_page
    li   t0, UART_BASE
    li   t1, 'F'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 1
fail_spin:
    j    fail_spin

fail_load_access:
    li   t0, UART_BASE
    li   t1, 'A'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 5
fail_load_access_spin:
    j    fail_load_access_spin

fail_store_access:
    li   t0, UART_BASE
    li   t1, 'B'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 7
fail_store_access_spin:
    j    fail_store_access_spin

fail_load_page:
    li   t0, UART_BASE
    li   t1, 'P'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 13
fail_load_page_spin:
    j    fail_load_page_spin

fail_store_page:
    li   t0, UART_BASE
    li   t1, 'Q'
    sb   t1, 0(t0)
    li   a7, 93
    li   a0, 15
fail_store_page_spin:
    j    fail_store_page_spin

fail_load:
    li   a7, 93
    li   a0, 1
fail_load_spin:
    j    fail_load_spin

fail_store:
    li   a7, 93
    li   a0, 2
fail_store_spin:
    j    fail_store_spin

.section .data
.align 12
root_pt:
    .zero 4096
.align 12
l1_rom:
    .zero 4096
.align 12
l1_exec:
    .zero 4096
.align 12
l1_data:
    .zero 4096
.align 12
sv39_data:
    .dword 0x1122334455667788
