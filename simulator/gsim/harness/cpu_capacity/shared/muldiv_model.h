#pragma once
// ISA oracle uses host full-width arithmetic, independently of the DUT's partial-product/restoring implementation.
static uint64_t multiplyDivide(unsigned op, bool word, uint64_t a, uint64_t b) {
    const uint64_t mask = word ? UINT64_C(0xffffffff) : UINT64_MAX;
    const unsigned width = word ? 32 : 64;
    a &= mask; b &= mask;
    uint64_t value;
    if (op < 4) {
        const __uint128_t product = __uint128_t(a) * b;
        value = op == 0 ? uint64_t(product) : uint64_t(product >> 64);
        if ((op == 1 || op == 2) && (a >> 63)) value -= b;
        if (op == 1 && (b >> 63)) value -= a;
    } else {
        const bool sign = !(op & 1), negA = sign && (a >> (width - 1)), negB = sign && (b >> (width - 1));
        const uint64_t aa = negA ? (-a & mask) : a, bb = negB ? (-b & mask) : b;
        if (op < 6) {
            value = bb ? aa / bb : mask;
            if (bb && negA != negB) value = -value;
        } else {
            value = bb ? aa % bb : aa;
            if (negA) value = -value;
        }
    }
    if (word) { value &= mask; if (value & UINT64_C(0x80000000)) value |= ~mask; }
    return value;
}
