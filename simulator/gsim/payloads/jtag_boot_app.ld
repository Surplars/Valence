OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
    . = 0x80020000;
    .text : { *(.text*) }
    /DISCARD/ : { *(.riscv.attributes) *(.comment) *(.eh_frame*) }
}
