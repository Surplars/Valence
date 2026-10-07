#ifndef VALENCE_CRC32_H
#define VALENCE_CRC32_H
#include <stdint.h>
/* Raw reflected CRC32 accumulator; callers retain their init/final XOR. */
uint32_t firmware_crc_update(uint32_t crc, const uint8_t *p, unsigned n);
#endif
