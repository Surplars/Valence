#include "ExecuteSelectGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
#include <vector>
// The existing shared ISA header also declares a memory interpreter. Keep its
// original core fixture types even though this driver only invokes execute().
constexpr uint64_t dataBase = 0x80010000;
using Memory = std::array<uint8_t, 4096>;
#include "isa_model.h"

int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    const bool injectPayload = argc == 2 && std::string_view(argv[1]) == "--inject-payload";
    SExecuteSelectGsim d;
    d.set_reset(0);
    uint64_t arithmetic = 0, arbitration = 0, overlap = 0, illegal = 0;
    auto alu = [&](unsigned op, bool word, uint64_t a, uint64_t b) {
        Encoding e{"raw", 0, 0, op, word, false, false, false};
        bool legal = (op <= 11 && (!word || op <= 1 || (op >= 5 && op <= 7))) ||
            (op >= 16 && op <= 44 && (!word || (op >= 27 && op <= 29) || op == 37 || op == 38));
        uint64_t expected = execute(e, a, b);
        if (inject && arithmetic == 100) expected ^= 1;
        d.set_io$$operation(op); d.set_io$$word(word);
        d.set_io$$left(a); d.set_io$$right(b); d.step();
        if (d.get_io$$result() != expected || bool(d.get_io$$legal()) != legal ||
            d.get_io$$baselineResult() != expected || bool(d.get_io$$baselineLegal()) != legal)
            throw std::runtime_error("execute selection arithmetic oracle mismatch op=" + std::to_string(op));
        ++arithmetic; illegal += !legal;
    };
    auto payload = [&](unsigned mask, uint64_t seed) {
        unsigned source = 5, count = 0;
        for (unsigned i = 0; i < 5; ++i) if ((mask >> i) & 1) {
            if (source == 5) source = i;
            ++count;
        }
        d.set_io$$present(mask); d.set_io$$seed(seed); d.step();
        const uint64_t id = source + 1;
        const uint64_t expectedTag = (~seed ^ (id << 32)) ^
            (injectPayload && arbitration == 100 ? uint64_t(1) << 63 : 0);
        if (d.get_io$$grants() != (1U << source) ||
            d.get_io$$selected$$token$$index() != ((seed & 15) ^ source) ||
            d.get_io$$selected$$token$$tag() != expectedTag ||
            d.get_io$$selected$$data() != (seed ^ id) ||
            d.get_io$$selected$$nextPc() != (seed ^ (id * 17)) ||
            bool(d.get_io$$selected$$exception()) != bool((seed >> source) & 1) ||
            d.get_io$$selected$$cause() != (seed ^ (id * 257)) ||
            d.get_io$$selected$$tval() != (~seed ^ (id * 65537)))
            throw std::runtime_error("execute selection completion payload oracle mismatch");
        ++arbitration; overlap += count >= 2;
    };
    // Initialize every scalar input before evaluation. Check ALL six-bit controls,
    // both word modes (including illegal combinations), overflow and shift wrapping.
    d.set_io$$present(0); d.set_io$$seed(0);
    const std::array<uint64_t, 12> edges{0, 1, 31, 32, 63, 64, 127, UINT64_MAX,
        0x8000000000000000ULL, 0x7fffffffffffffffULL, 0xffffffffULL, 0x80000000ULL};
    for (unsigned op = 0; op < 64; ++op) for (bool word : {false, true})
        for (auto a : edges) for (auto b : edges) alu(op, word, a, b);
    for (unsigned op = 0; op < 64; ++op) for (bool word : {false, true})
        for (unsigned bit = 0; bit < 64; ++bit) for (unsigned shift = 0; shift < 128; ++shift)
            alu(op, word, uint64_t(1) << bit, shift);
    for (unsigned mask = 0; mask < 32; ++mask) for (auto seed : edges) payload(mask, seed);
    std::mt19937_64 rng(0x20261002e5e1ULL);
    for (unsigned i = 0; i < 20000; ++i) {
        unsigned op = rng() % 64; bool word = rng() & 1; uint64_t a = rng(), b = rng();
        alu(op, word, a, b); unsigned mask = rng() % 32; uint64_t seed = rng();
        payload(mask, seed);
    }
    if (!illegal || !overlap) throw std::runtime_error("execute selection coverage incomplete");
    std::cout << "GSIM execute selection: PASS arithmetic=" << arithmetic << " illegal=" << illegal
              << " arbitration=" << arbitration << " overlap=" << overlap << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
