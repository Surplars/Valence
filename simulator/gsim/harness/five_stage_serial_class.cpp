#include "FiveStageSerialClassFixture.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>

int main(int argc, char **) { try {
    SFiveStageSerialClassFixture d;
    d.set_reset(0);
    const bool wrong = argc > 1;
    std::mt19937 random{0x53455249};
    unsigned cases = 0, serialSeen = 0;
    for (unsigned test = 0; test < 98304; ++test) {
        const bool compressed = test < 65536;
        const uint32_t instruction = compressed ? (0xa1390000U | test) : random();
        d.set_io$$instruction(instruction); d.set_io$$compressed(compressed); d.step();
        unsigned expected = 0;
        for (unsigned config = 0; config < 7; ++config) {
            const bool a = config == 1 || config == 2 || config == 3 || config == 5 || config == 6;
            const bool f = config == 2 || config == 3 || config == 4 || config == 6;
            const bool fp64 = config == 3 || config == 4 || config == 6;
            bool serial = false;
            if (compressed && config != 6) {
                const unsigned quadrant = instruction & 3, function = (instruction >> 13) & 7;
                // Includes the reserved JR-x0 encoding, whose expanded class
                // is SYSTEM although its legal flag is false.
                serial = quadrant == 2 && function == 4 && !(instruction & 0xffc);
                serial |= f && ((quadrant == 0 && (function == 1 || function == 5)) ||
                                (quadrant == 2 && fp64 && (function == 1 || function == 5)));
            } else {
                switch (instruction & 127) {
                case 0x0f: case 0x73: serial = true; break;
                case 0x2f: serial = a; break;
                case 0x07: case 0x27: case 0x53: case 0x43: case 0x47: case 0x4b: case 0x4f:
                    serial = f; break;
                }
            }
            expected |= unsigned(serial) << config;
        }
        if (unsigned(d.get_io$$serial()) != (expected ^ unsigned(wrong)))
            throw std::runtime_error("independent ISA serial class oracle");
        serialSeen += expected != 0; ++cases;
    }
    if (!serialSeen) throw std::runtime_error("missing serial instruction coverage");
    std::cout << "I1_SERIAL_CLASS_PASS cases=" << cases
              << " compressed=65536 configs=7 illegal_classes_retained=1\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
