OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
    . = 0x80200000;
    .text : { *(.text.start) *(.text*) }
    /DISCARD/ : { *(.riscv.attributes) *(.comment) *(.eh_frame*) }
}
