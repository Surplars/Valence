OUTPUT_ARCH("riscv")
OUTPUT_FORMAT("elf64-littleriscv")
ENTRY(_start)

MEMORY {
    SRAM (rwx) : ORIGIN = 0x40100000, LENGTH = 0x00f00000
}

SECTIONS {
    .text : {
        *(.text*)
    } > SRAM

    .rodata : {
        *(.rodata*)
    } > SRAM

    .data : {
        *(.data*)
        *(.sdata*)
    } > SRAM

    .bss : {
        *(.bss*)
        *(COMMON)
        *(.sbss*)
    } > SRAM
}
