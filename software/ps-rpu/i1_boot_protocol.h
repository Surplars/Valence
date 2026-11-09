#ifndef I1_BOOT_PROTOCOL_H
#define I1_BOOT_PROTOCOL_H
#include <stdint.h>
#include <stddef.h>

/* One cold launch: RPU publishes inputs before reset release; RV owns outputs.
 * RPU only reads afterwards. Runtime bidirectional service is a separate ABI.
 */
#define I1_PS_DDR_BASE 0x40000000U
#define I1_RV_DDR_BASE 0x80000000ULL
#define I1_PS_DDR_BYTES 0x10000000U
#define I1_BOOT_SHARED_OFFSET 0x0fff0000U
#define I1_BOOT_IMAGE_MAX_BYTES I1_BOOT_SHARED_OFFSET
#define I1_PS_BOOT_MAILBOX (I1_PS_DDR_BASE + I1_BOOT_SHARED_OFFSET)
#define I1_RV_BOOT_MAILBOX (I1_RV_DDR_BASE + I1_BOOT_SHARED_OFFSET)
#define I1_BOOT_MAGIC 0x49314254U
#define I1_BOOT_ABI 0x00010000U
#define I1_BOOT_SEED 0x6d5a56a9U
#define I1_BOOT_ITERATIONS 64U
#define I1_BOOT_FORCE_BREAKPOINT 1U
#define I1_BOOT_READY 1U
#define I1_BOOT_RUNNING 2U
#define I1_BOOT_PASSED 3U
#define I1_BOOT_FAILED 0x80000000U
#define I1_BOOT_BAD_CRC 1U
#define I1_BOOT_BAD_HEADER 3U
#define I1_BOOT_TRAP 4U

typedef struct {
    uint32_t magic, abi, image_bytes, image_crc32;
    uint32_t seed, iterations, flags;
    uint32_t reserved_input[9];
    uint32_t state, error, observed_crc32, kernel_checksum;
    uint64_t hart_id, misa, cycles, instructions;
    uint64_t trap_pc, trap_cause, trap_tval;
    uint8_t reserved_output[120];
} I1BootMailbox;

_Static_assert(offsetof(I1BootMailbox, state) == 64, "boot ABI output offset");
_Static_assert(offsetof(I1BootMailbox, trap_pc) == 112, "boot ABI trap offset");
_Static_assert(sizeof(I1BootMailbox) == 256, "boot ABI size");

static inline uint32_t I1BootCrc32(const uint8_t *data, uint32_t bytes)
{
    uint32_t crc = 0xffffffffU;
    for (uint32_t i = 0; i < bytes; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return ~crc;
}

/* Force real load/store traffic; 32-bit arithmetic has a portable wrap contract. */
static inline uint32_t I1BootKernel(uint32_t seed, uint32_t iterations)
{
    volatile uint32_t scratch[64];
    for (uint32_t i = 0; i < 64; ++i) {
        unsigned shift = i & 31U;
        uint32_t rotated = (seed << shift) | (seed >> ((32U - shift) & 31U));
        scratch[i] = (seed ^ (i * 0x9e3779b9U)) + rotated;
    }
    uint32_t hash = 0x811c9dc5U;
    for (uint32_t i = 0; i < iterations; ++i) {
        uint32_t x = scratch[i & 63U];
        x ^= x << 13; x ^= x >> 17; x ^= x << 5;
        scratch[i & 63U] = x + i + seed;
        hash = (hash ^ scratch[i & 63U]) * 0x01000193U;
    }
    return hash;
}
#endif
