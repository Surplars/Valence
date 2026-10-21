OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ROM (rx) : ORIGIN = 0x80000000, LENGTH = 256 }
SECTIONS {
  . = ORIGIN(ROM);
  .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.*) } > ROM
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
  ASSERT(SIZEOF(.text) <= LENGTH(ROM), "MSI epoch guest exceeds unchanged 64-word fixture ROM")
}
