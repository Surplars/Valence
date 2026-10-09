OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS {
  . = 0x80200000;
  .text : { *(.text.start) *(.text*) }
  .rodata : { *(.rodata*) }
  /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.eh_frame*) }
  ASSERT(. < 0x80210000, "timer guest image overflow")
}
