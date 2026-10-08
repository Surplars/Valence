OUTPUT_ARCH(riscv)
ENTRY(_start)
__ram_bytes = DEFINED(BOARD_RAM_BYTES) ? BOARD_RAM_BYTES : 1M;
__monitor_base = DEFINED(BOARD_MONITOR_BASE) ? BOARD_MONITOR_BASE : 0x80200000 + __ram_bytes - 16K;
MEMORY {
    ROM (rx) : ORIGIN = 0x80000000, LENGTH = 128K
    BOOT (rw) : ORIGIN = __monitor_base, LENGTH = 16K
}
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text .text.*) } > ROM
    .rodata : { *(.srodata .srodata.* .rodata .rodata.*) } > ROM
    .data : ALIGN(8) {
        __data_start = .;
        __global_pointer$ = . + 0x800;
        . = ALIGN(64);
        __crc32_table_start = .;
        KEEP(*(.data.crc32_table))
        __crc32_table_end = .;
        *(.sdata .sdata.* .data .data.*)
        __data_end = .;
    } > BOOT AT > ROM
    __data_load = LOADADDR(.data);
    ASSERT((__crc32_table_start & 63) == 0, "CRC table must be cache-line aligned")
    ASSERT((__crc32_table_end - __crc32_table_start == 64) ||
           (__crc32_table_end - __crc32_table_start == 1024) ||
           (__crc32_table_end - __crc32_table_start == 4096), "unsupported CRC table size")
    .bss (NOLOAD) : ALIGN(8) {
        __bss_start = .;
        *(.sbss .sbss.* .bss .bss.* COMMON)
        __bss_end = .;
    } > BOOT
    __app_stack_top = ORIGIN(BOOT);
    __boot_stack_top = ORIGIN(BOOT) + LENGTH(BOOT);
    ASSERT(__bss_end <= ORIGIN(BOOT) + 8192, "boot globals exceed reserved 8 KiB; keep 8 KiB stack")
    ASSERT(ORIGIN(BOOT) >= 0x80200000 && ORIGIN(BOOT) + 16K <= 0x80200000 + __ram_bytes,
           "monitor outside RAM")
    ASSERT(ORIGIN(BOOT) <= 0xffff8000, "BootROM medany globals out of reach")
    /DISCARD/ : { *(.comment .eh_frame .riscv.attributes) }
}
