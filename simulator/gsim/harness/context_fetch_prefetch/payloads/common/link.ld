OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { RAM (rwx) : ORIGIN = 0x80200000, LENGTH = 128K }
SECTIONS {
 . = ORIGIN(RAM);
 .text : { KEEP(*(.text.start)) *(.text .text.*) } >RAM
 .rodata : { *(.rodata .rodata.*) } >RAM
 ASSERT(. < 0x80210000, "Code/rodata exceeds 64KiB")
 .data 0x80210000 : { __global_pointer$ = .+0x800; *(.data .data.* .sdata .sdata.*) } >RAM
 .bss (NOLOAD) : ALIGN(8) { __bss_start = .; *(.bss .bss.* .sbss .sbss.* COMMON) . = ALIGN(8); __bss_end = .; } >RAM
 ASSERT(. < 0x80218000, "Data/BSS exceeds reserved region")
 __stack_top = 0x8021fff0;
 /DISCARD/ : { *(.comment .note .eh_frame .riscv.attributes) }
}
