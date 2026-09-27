#include <stdint.h>

__attribute__((noinline)) static uint64_t fold(uint64_t value) {
    // Exercise compiler-generated stack stores/loads, not just a hand-written instruction stream.
    volatile uint64_t scratch[2];
    scratch[0] = value;
    scratch[1] = 3;
    return scratch[0] + scratch[1];
}

uint64_t kernel(volatile uint64_t *data) {
    for (uint64_t i = 0; i < 64; ++i) data[i] = fold(i);
    uint64_t sum = 0;
    for (unsigned i = 0; i < 64; ++i) sum += data[i];
    return sum; // 0 + ... + 63 + 64 * 3 = 2208
}
