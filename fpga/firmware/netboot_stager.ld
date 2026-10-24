OUTPUT_ARCH(riscv)
ENTRY(_start)
MEMORY {
    BOOT (rx) : ORIGIN = 0x80200000, LENGTH = 128K
    STAGE (rwx) : ORIGIN = 0xffe00000, LENGTH = 128K
}
PHDRS { boot PT_LOAD FLAGS(5); code PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
    .boot : ALIGN(8) { KEEP(*(.boot)) . = ALIGN(8); } > BOOT :boot
    __stage_load_start = LOADADDR(.boot) + SIZEOF(.boot);
    .stage_text ORIGIN(STAGE) : AT(__stage_load_start) {
        __stage_start = .;
        KEEP(*(.text.stage_start))
        *(.text .text.*)
        *(.srodata .srodata.* .rodata .rodata.*)
        . = ALIGN(64);
    } > STAGE :code
    .stage_data : AT(__stage_load_start + SIZEOF(.stage_text)) {
        __global_pointer$ = . + 0x800;
        *(.sdata .sdata.* .data .data.*)
        . = ALIGN(8);
        __stage_initialized_end = .;
    } > STAGE :data
    __stage_load_end = __stage_load_start + SIZEOF(.stage_text) + SIZEOF(.stage_data);
    .bss (NOLOAD) : ALIGN(64) {
        __stage_bss_start = .;
        *(.sbss .sbss.* .bss .bss.* COMMON)
        . = ALIGN(16);
        __stage_bss_end = .;
    } > STAGE :data
    __stage_stack_top = ORIGIN(STAGE) + LENGTH(STAGE);
    __stage_stack_bottom = __stage_stack_top - 16K;
    ASSERT(ADDR(.stage_data)==ADDR(.stage_text)+SIZEOF(.stage_text), "relocation VMA gap")
    ASSERT(__stage_initialized_end-__stage_start==__stage_load_end-__stage_load_start, "relocation span mismatch")
    ASSERT(__stage_load_end <= ORIGIN(BOOT)+LENGTH(BOOT), "stager download too large")
    ASSERT(__stage_bss_end <= __stage_stack_bottom, "stager BSS/RX overlaps stack")
    ASSERT(__stage_stack_top <= 0xfff78000, "stager overlaps existing ROM diagnostics")
    ASSERT(__stage_start == 0xffe00000, "stager/image boundary changed")
    ASSERT((__stage_load_start % 8)==0 && ((SIZEOF(.stage_text)+SIZEOF(.stage_data))%8)==0, "relocation alignment")
    /DISCARD/ : { *(.comment .eh_frame .riscv.attributes) }
}
