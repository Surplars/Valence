OUTPUT_ARCH(riscv)
ENTRY(_start)
__ram_bytes = DEFINED(BOARD_RAM_BYTES) ? BOARD_RAM_BYTES : 1M;
__monitor_base = DEFINED(BOARD_MONITOR_BASE) ? BOARD_MONITOR_BASE : 0x80200000 + __ram_bytes - 16K;
MEMORY {
    APP (rwx) : ORIGIN = 0x80200000, LENGTH = __monitor_base - 0x80200000 - 16K
}
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text .text.*) } > APP
    .rodata : { *(.srodata .srodata.* .rodata .rodata.*) } > APP
    .data : ALIGN(8) {
        __global_pointer$ = . + 0x800;
        *(.sdata .sdata.* .data .data.*)
    } > APP
    .bss (NOLOAD) : ALIGN(8) {
        __bss_start = .;
        *(.sbss .sbss.* .bss .bss.* COMMON)
        __bss_end = .;
    } > APP
    /* 16 KiB application stack, then the ROM monitor's reserved 16 KiB. */
    __app_stack_top = __monitor_base;
    ASSERT(__bss_end <= __app_stack_top - 16K, "application overlaps its stack")
    ASSERT(__bss_end <= (DEFINED(DDR_TEST_PROGRAM_LIMIT) ? DDR_TEST_PROGRAM_LIMIT : __app_stack_top - 16K),
           "DDR test program overlaps destructive test region")
    /DISCARD/ : { *(.comment .eh_frame .riscv.attributes) }
}
