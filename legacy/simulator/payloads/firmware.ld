OUTPUT_ARCH("riscv")
OUTPUT_FORMAT("elf64-littleriscv")
ENTRY(_start)

MEMORY {
    SRAM (rwx) : ORIGIN = 0x40000000, LENGTH = 0x00080000
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
