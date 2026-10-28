OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { RAM (rx) : ORIGIN = 0x80200000, LENGTH = 128K }
PHDRS { text PT_LOAD FLAGS(5); }
SECTIONS {
    . = ORIGIN(RAM);
    .text : { *(.text .text.*) } > RAM :text
    ASSERT(_start == ORIGIN(RAM), "entry must match common boot")
    ASSERT(. <= ORIGIN(RAM) + LENGTH(RAM), "branch text outside common RAM")
    /DISCARD/ : { *(.comment .note .eh_frame .riscv.attributes) }
}
