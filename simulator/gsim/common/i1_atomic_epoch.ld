OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { ROM (rx) : ORIGIN = 0x80000000, LENGTH = 1024 }
SECTIONS {
  . = ORIGIN(ROM);
  .text : { KEEP(*(.text.start)) *(.text .text.*) *(.rodata .rodata.*) } > ROM
  /DISCARD/ : { *(.comment) *(.riscv.attributes) }
  ASSERT(SIZEOF(.text) <= LENGTH(ROM), "Atomic epoch guest exceeds isolated 256-word ROM")
}
