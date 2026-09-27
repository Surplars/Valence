ENTRY(_start)
MEMORY { rom (rx) : ORIGIN = 0x80000000, LENGTH = 64K
         ram (rw) : ORIGIN = 0x80010000, LENGTH = 8K }
SECTIONS {
    .text : { *(.text.start) *(.text*) *(.rodata*) . = ALIGN(8); } > rom
    .data : { _data_start = .; *(.sdata*) *(.data*) . = ALIGN(8); _data_end = .; } > ram AT > rom
    _data_load = LOADADDR(.data);
    .bss (NOLOAD) : { _bss_start = .; *(.sbss*) *(.bss*) *(COMMON) _bss_end = .; } > ram
    _stack_top = ORIGIN(ram) + LENGTH(ram);
    /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.eh_frame*) }
}
