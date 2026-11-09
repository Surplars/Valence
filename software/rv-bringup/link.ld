OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 0x0fff0000 }
SECTIONS {
    . = ORIGIN(RAM);
    .text : { KEEP(*(.text.init)) *(.text .text.*) } > RAM
    .rodata : { *(.rodata .rodata.*) } > RAM
    . = ALIGN(8);
    __data_start = .;
    __global_pointer$ = __data_start + 0x800;
    .data : { *(.data .data.* .sdata .sdata.*) } > RAM
    __image_end = .;
    . = ALIGN(8);
    __bss_start = .;
    .bss (NOLOAD) : { *(.bss .bss.* .sbss .sbss.*) *(COMMON) . = ALIGN(8); } > RAM
    __bss_end = .;
    __stack_top = ORIGIN(RAM) + 0x20000;
    ASSERT(__bss_end < __stack_top - 0x4000, "bringup image overlaps its stack")
}
