OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { APP (rwx) : ORIGIN = DIAGNOSTIC_BASE, LENGTH = 128K }
SECTIONS {
 .text : { KEEP(*(.text.start)) *(.text .text.*) } > APP
 .rodata : { *(.srodata .srodata.* .rodata .rodata.*) } > APP
 .data : ALIGN(8) { __global_pointer$ = .+0x800; *(.sdata .sdata.* .data .data.*) } > APP
 .bss (NOLOAD) : ALIGN(8) { __bss_start = .; *(.sbss .sbss.* .bss .bss.* COMMON) __bss_end = .; } > APP
 __app_stack_top = DIAGNOSTIC_BASE+128K;
 ASSERT(__bss_end <= __app_stack_top-16K,"diagnostic globals exceed code/data region; reserve16KiB stack")
 /DISCARD/ : { *(.comment .eh_frame .riscv.attributes) }
}
