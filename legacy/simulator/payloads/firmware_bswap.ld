OUTPUT_ARCH("riscv")
OUTPUT_FORMAT("elf64-littleriscv")
ENTRY(_start)

MEMORY {
    ROM (rx)   : ORIGIN = 0x80000000, LENGTH = 0x1000
    SRAM (rwx) : ORIGIN = 0x40000000, LENGTH = 0x10000
}

SECTIONS {
    .text : {
        *(.text*)
    } > ROM

    .data : {
        *(.data*)
        *(.rodata*)
    } > SRAM

    .bss : {
        *(.bss*)
        *(COMMON)
    } > SRAM
}
