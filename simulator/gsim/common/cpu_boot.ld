OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ROM (rx) : ORIGIN = 0x80000000, LENGTH = 128K }
SECTIONS {
  . = ORIGIN(ROM);
  .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.*) } > ROM
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
  ASSERT(SIZEOF(.text) <= LENGTH(ROM), "test guest exceeds common 128 KiB ROM")
}
