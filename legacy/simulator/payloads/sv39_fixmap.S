.section .text.init
.globl _start

.equ ROM_VA,          0x80000000
.equ EXEC_VA_BASE,    0x00200000
.equ DATA_PHYS_BASE,  0x40000000
.equ DATA_VA_BASE,    0x40000000
.equ FIXMAP_VA,       0xfffffffffebfa000
.equ FIXMAP_VPN1,     501
.equ FIXMAP_VPN0,     506
.equ PTE_V,           0x001
.equ PTE_R,           0x002
.equ PTE_W,           0x004
.equ PTE_X,           0x008
.equ PTE_A,           0x040
.equ PTE_D,           0x080
.equ SATP_MODE_SV39,  0x8000000000000000

_start:
    la   t0, fail
    csrw mtvec, t0
    la   t0, fail
    csrw stvec, t0

    li   t0, -1
    csrw pmpaddr0, t0
    li   t0, 0x1f
    csrw pmpcfg0, t0

    # root[2] maps the linked ROM VA so traps still have executable code.
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

    # root[0] maps the S-mode execution alias to the ROM physical superpage.
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

    # root[1] maps a data alias used after paging is enabled to edit PTEs.
    la   t0, l1_data
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V
    la   t1, root_pt
    sd   t0, 8(t1)

    li   t0, DATA_PHYS_BASE
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V | PTE_R | PTE_W | PTE_A | PTE_D
    la   t1, l1_data
    sd   t0, 0(t1)

    # root[511] covers the high-half fixmap VA used by Linux text poking.
    la   t0, l1_fixmap
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V
    la   t1, root_pt
    li   t2, 511 * 8
    add  t1, t1, t2
    sd   t0, 0(t1)

    la   t0, l0_fixmap
    srli t0, t0, 12
    slli t0, t0, 10
    ori  t0, t0, PTE_V
    la   t1, l1_fixmap
    li   t2, FIXMAP_VPN1 * 8
    add  t1, t1, t2
    sd   t0, 0(t1)

    # Prepare S-mode registers without using la after the PC is remapped.
    la   s0, l0_fixmap
    li   t0, DATA_PHYS_BASE
    sub  s0, s0, t0
    li   t0, DATA_VA_BASE
    add  s0, s0, t0

    la   s1, fixmap_data
    srli s1, s1, 12
    slli s1, s1, 10
    ori  s1, s1, PTE_V | PTE_R | PTE_W | PTE_A | PTE_D

    la   s2, fixmap_data
    li   t0, DATA_PHYS_BASE
    sub  s2, s2, t0
    li   t0, DATA_VA_BASE
    add  s2, s2, t0

    li   s3, FIXMAP_VA
    li   s4, FIXMAP_VPN0 * 8

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
    add  t0, s0, s4
    sd   s1, 0(t0)
    sfence.vma s3, x0

    li   t1, 0x8877665544332211
    sd   t1, 0(s3)
    ld   t2, 0(s3)
    bne  t2, t1, fail_load

    ld   t3, 0(s2)
    bne  t3, t1, fail_alias

    sd   zero, 0(t0)
    sfence.vma s3, x0

pass:
    li   a7, 93
    li   a0, 0
pass_spin:
    j    pass_spin

fail:
    csrr a0, mcause
    li   a7, 93
fail_spin:
    j    fail_spin

fail_load:
    li   a7, 93
    li   a0, 1
fail_load_spin:
    j    fail_load_spin

fail_alias:
    li   a7, 93
    li   a0, 2
fail_alias_spin:
    j    fail_alias_spin

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
l1_fixmap:
    .zero 4096
.align 12
l0_fixmap:
    .zero 4096
.align 12
fixmap_data:
    .dword 0x1122334455667788
