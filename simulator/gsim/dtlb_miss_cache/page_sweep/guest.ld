OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS { . = 0x80200000; .text : { *(.text.start) *(.text*) } /DISCARD/ : { *(.comment .eh_frame .riscv.attributes) } }
