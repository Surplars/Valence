OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY { DDR (rwx) : ORIGIN = 0x80200000, LENGTH = 64K }
SECTIONS {
    .text : { *(.text.start) } > DDR
    .supervisor 0x80201000 : { *(.text.supervisor) } > DDR
    .user 0x80202000 : { *(.text.user) } > DDR
}
