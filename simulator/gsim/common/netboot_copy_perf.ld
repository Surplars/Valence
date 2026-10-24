OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
 . = 0x80000000;
 .boot : { *(.boot) }
 .text : { *start.o(.text*) *driver.o(.text*) *crc.o(.text*) }
 .rodata : { *driver.o(.rodata* .srodata*) *crc.o(.rodata* .srodata*) }
 ASSERT(. < 0x80004000,"driver overlaps benchmark")
 .bench 0x80004000 : { __bench_start = .; *copy.o(.text* .rodata* .srodata*) . = ALIGN(8); __bench_end = .; }
 __data_load = .;
 .data 0x80238000 : AT(__data_load) { __data_start = .; *(.data* .sdata*) . = ALIGN(8); __data_end = .; }
 __global_pointer$ = 0x80238800;
 __stack = 0x8023f000;
 ASSERT(__data_end<0x8023e000,"table/stack overlap")
 ASSERT(__data_load+SIZEOF(.data)<0x80020000,"ROM overflow")
 /DISCARD/ : { *(.comment .eh_frame .riscv.attributes) }
}
