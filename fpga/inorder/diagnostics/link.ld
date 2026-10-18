OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ram (rwx) : ORIGIN = 0x80200000, LENGTH = 1M }
SECTIONS {
    .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) . = ALIGN(16); } > ram
    .data : { *(.data*) . = ALIGN(16); __global_pointer$ = . + 0x800; *(.sdata*) . = ALIGN(16); } > ram
    _file_end = .;
    .bss (NOLOAD) : { _bss_start = .; *(.sbss*) *(.bss*) *(COMMON) . = ALIGN(16); _bss_end = .; } > ram
    _stack_top = ORIGIN(ram) + LENGTH(ram);
    ASSERT(_bss_end + 32768 < _stack_top, "diagnostic overlaps stack")
    ASSERT(_file_end - ORIGIN(ram) <= 0x4000000, "JTAG aperture exceeded")
    /DISCARD/ : { *(.comment) *(.eh_frame*) }
}
