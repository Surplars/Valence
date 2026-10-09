OUTPUT_ARCH(riscv)
ENTRY(launcher_start)
SECTIONS {
  . = 0x80000000;
  .text : { *(.text) }
  /DISCARD/ : { *(.riscv.attributes) *(.comment) }
}
