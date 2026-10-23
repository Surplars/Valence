OUTPUT_ARCH(riscv)
ENTRY(_start)
/* Dedicated RAM payload allocation below standard firmware/DTB at80300000.
 * No scratch is selected outside this explicit1MiB exclusive allocation. */
MEMORY { APP (rwx) : ORIGIN = 0x80200000, LENGTH = 1M }
SECTIONS {
 .text : { KEEP(*(.text.start)) *(.text .text.*) } > APP
 .rodata : { *(.srodata .srodata.* .rodata .rodata.*) } > APP
 .data : ALIGN(8) { __global_pointer$ = . + 0x800; *(.sdata .sdata.* .data .data.*) } > APP
 .bss (NOLOAD) : ALIGN(64) { __bss_start = .; *(.sbss .sbss.* .bss .bss.* COMMON) __bss_end = .; } > APP
 .scratch (NOLOAD) : ALIGN(64) { __scratch_start = .; *(.scratch) __scratch_end = .; } > APP
 __app_stack_top = ORIGIN(APP) + LENGTH(APP);
 ASSERT(__scratch_end <= __app_stack_top - 16K, "payload scratch overlaps stack/DTB")
 /DISCARD/ : { *(.comment .eh_frame .riscv.attributes) }
}
