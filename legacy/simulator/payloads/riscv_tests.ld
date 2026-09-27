OUTPUT_ARCH("riscv")
OUTPUT_FORMAT("elf64-littleriscv")
ENTRY(_start)

MEMORY {
    ROM  (rx)  : ORIGIN = 0x80000000, LENGTH = 0x10000
    SRAM (rwx) : ORIGIN = 0x10000000, LENGTH = 0x10000
}

SECTIONS {
    . = ORIGIN(ROM);

    .text.boot : {
        *(.text.boot)
    } > ROM

    . = ORIGIN(SRAM);

    .tohost : ALIGN(64) {
        *(.tohost)
    } > SRAM

    . = ORIGIN(SRAM) + 0x1000;

    .text.init : {
        *(.text.init)
    } > SRAM

    .text : ALIGN(4) {
        *(.text*)
    } > SRAM

    .data : ALIGN(0x1000) {
        *(.data*)
        *(.sdata*)
        *(.rodata*)
    } > SRAM

    .bss : ALIGN(8) {
        *(.bss*)
        *(.sbss*)
        *(COMMON)
    } > SRAM

    _end = .;
}
