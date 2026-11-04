#include "FiveStageCompressed.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
#include "i1_compressed_reference.h"
using namespace I1CompressedReference;
int main(int argc, char **argv) { try {
    SFiveStageCompressed d; d.set_reset(0); unsigned legal = 0;
    bool mutate = argc > 1 && std::string(argv[1]) == "--wrong-expansion";
    for (unsigned c = 0; c < 65536; ++c) {
        auto expected = decode(c); if (mutate && c == 1) expected.value ^= 1;
        d.set_io$$instruction(c); d.step();
        if (bool(d.get_io$$legal()) != expected.legal || (expected.legal && d.get_io$$expanded() != expected.value)) {
            std::cerr << "C mismatch encoding=0x" << std::hex << c << " expected=" << expected.value
                << " got=" << d.get_io$$expanded() << '\n';
            throw std::runtime_error("independent exhaustive C expansion oracle");
        }
        legal += expected.legal;
    }
    std::cout << "FIVE_STAGE_COMPRESSED_PASS xlen=" << DUT_XLEN << " encodings=65536 legal=" << legal
        << " hints_reserved_integer_only_immediates_registers=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
