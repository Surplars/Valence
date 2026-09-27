ENTRY(_start)
SECTIONS {
  . = 0x80000000;
  .text : { *(.text.start) *(.text) }
  /* Keep the trap vector separate from sequential fetch lookahead. */
  . = 0x80001000;
  .trap : { *(.text.trap) }
  /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.eh_frame*) }
}
