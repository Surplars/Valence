OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
    . = 0x80000000;
    .text : { KEEP(*(.text.start)) *(.text*) }
    _program_end = .;
    _data_start = 0x80010000;
    _stack_top = 0x80011000;
    /DISCARD/ : { *(.riscv.attributes) *(.comment) *(.eh_frame*) }
}
