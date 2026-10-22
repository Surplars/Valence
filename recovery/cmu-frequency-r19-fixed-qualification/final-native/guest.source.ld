OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ROM (rx) : ORIGIN = 0x80000000, LENGTH = 2048 }
SECTIONS {
  . = ORIGIN(ROM);
  .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.*) } > ROM
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
  ASSERT(SIZEOF(.text) <= LENGTH(ROM), "network runtime guest exceeds 512-word fixture ROM")
}
