OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { DDR (rwx) : ORIGIN = 0x80200000, LENGTH = 1M }
SECTIONS {
    .text : { *(.text.start) *(.text*) *(.rodata*) } > DDR
    .data : { *(.data*) } > DDR
    .bss (NOLOAD) : { *(.bss*) *(COMMON) } > DDR
}
