#include "crc32.h"

/* One cache line in monitor RAM, initialized by start.S from the ROM image.
 * Explicit placement and volatile loads prevent compiler ROM-table folding.
 * Keep this shared by UART and netboot; do not allocate a table per caller. */
static const volatile uint32_t crc32_nibble_table[16]
    __attribute__((section(".data.crc32_table"), aligned(64))) = {
    0,0x1db71064,0x3b6e20c8,0x26d930ac,0x76dc4190,0x6b6b51f4,0x4db26158,0x5005713c,
    0xedb88320,0xf00f9344,0xd6d6a3e8,0xcb61b38c,0x9b64c2b0,0x86d3d2d4,0xa00ae278,0xbdbdf21c
};

uint32_t firmware_crc_update(uint32_t crc, const uint8_t *p, unsigned n) {
    while (n--) {
        crc ^= *p++;
        crc = (crc >> 4) ^ crc32_nibble_table[crc & 15];
        crc = (crc >> 4) ^ crc32_nibble_table[crc & 15];
    }
    return crc;
}
