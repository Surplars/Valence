OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ROM (rx) : ORIGIN = 0x10000, LENGTH = 4K }
SECTIONS { .text : { *(.text.start) *(.text*) *(.rodata*) } > ROM
    ASSERT(SIZEOF(.text) <= LENGTH(ROM), "I1 BootROM overflow") }
