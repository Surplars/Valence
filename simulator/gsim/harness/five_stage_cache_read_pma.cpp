// Add a read-only qualification profile; the original R/W oracle and tests
// remain unchanged and are still run separately.
#define main i1_existing_rw_cache_main
#include "five_stage_cache.cpp"
#undef main
#include <string>

int main(int argc, char **argv) { try {
    bool wrongHint = argc > 1 && std::string(argv[1]) == "--wrong-hint";
    bool wrongData = argc > 1 && std::string(argv[1]) == "--wrong-data";
    Test t;
    t.d.set_io$$request$$bits$$atomic(0);
    t.d.set_io$$request$$bits$$atomicOperation(0);
    uint64_t checks = 0;
    auto read = [&](uint64_t address, bool noAllocate = false) {
        // PMA from independent public geometry, not the DUT decoder.
        bool inRam = address >= BASE && address < 0x90000000ULL;
        t.d.set_io$$readCacheable((inRam && !noAllocate) ^ wrongHint);
        auto old = t.requests;
        auto value = t.transact(address, false, 0, WORD == 8 ? 255 : 15, noAllocate);
        need(!value[1] && value[0] == (t.load(address & ~(WORD - 1ULL)) ^ uint64_t(wrongData)),
            "independent read-only PMA byte oracle");
        if (t.requests != old) {
            need(t.requests == old + 1, "read-only cache duplicated a backend owner");
            unsigned expected = CACHE_BYTES && inRam && !noAllocate ? LINE / WORD : 1;
            need(t.d.get_io$$memory$$request$$bits$$beats() == expected,
                "independent PMA scalar-versus-line geometry oracle");
        }
        ++checks;
    };
    read(BASE + 16); auto before = t.requests; read(BASE + 16);
    need(t.requests == before + (CACHE_BYTES ? 0 : 1), "trusted IF hit geometry");
    read(BASE + 24, true); // A warm line cannot erase explicit noAllocate.
    before = t.requests; read(0x10000000); read(0x10000000);
    need(t.requests == before + 2, "trusted IF PMA cached MMIO");
    read(0x90000000); read(DUT_XLEN == 64 ? 0x100000000ULL : 0xfffffff0ULL);
    read(BASE + (CACHE_BYTES ? CACHE_BYTES : 512) + 16); read(BASE + 16);
    t.invalidate(); t.errorBeat = CACHE_BYTES ? 3 : 0;
    t.d.set_io$$readCacheable(1);
    auto error = t.transact(BASE + 16); need(error[1], "trusted IF lost a real refill error");
    t.errorBeat = 999; before = t.requests; read(BASE + 16);
    need(t.requests == before + 1, "trusted IF published failed refill");
    t.invalidate(); t.invalidateFill = true; read(BASE + 16); t.invalidateFill = false;
    before = t.requests; read(BASE + 16);
    need(t.requests == before + 1, "trusted IF resurrected invalidated fill");
    if (CACHE_BYTES) {
        unsigned admitted = 0, returned = 0, elapsed = 0;
        before = t.requests; t.responseReady = true; t.d.set_io$$response$$ready(1);
        t.d.set_io$$readCacheable(1);
        for (; elapsed < 40 && returned < 16; ++elapsed) {
            bool valid = admitted < 16;
            t.d.set_io$$request$$valid(valid); t.d.set_io$$request$$bits$$address(BASE + 16);
            t.d.set_io$$request$$bits$$noAllocate(0); t.step();
            if (valid && t.d.get_io$$request$$ready()) ++admitted;
            if (t.d.get_io$$response$$valid()) {
                need(!t.d.get_io$$response$$bits$$error() &&
                    t.d.get_io$$response$$bits$$data() == t.load(BASE + 16),
                    "independent pipelined IF PMA byte oracle"); ++returned;
            }
        }
        need(admitted == 16 && returned == 16 && elapsed == 17 && t.requests == before,
            "trusted IF inserted hit bubbles or grew capacity");
        t.d.set_io$$request$$valid(0); t.d.set_io$$response$$ready(0); t.responseReady = false;
    }
    std::mt19937_64 random(0x504d41);
    for (unsigned n = 0; n < 256; ++n) {
        read(BASE + (random() % (8192 / WORD)) * WORD, n % 13 == 0);
        if (n % 37 == 0) t.invalidate();
    }
    t.d.set_reset(1); t.d.set_io$$request$$valid(0); t.d.set_io$$response$$ready(0);
    t.d.set_io$$memory$$response$$valid(0); t.d.step(); t.d.step(); t.d.set_reset(0);
    before = t.requests; read(BASE + 16);
    need(t.requests == before + 1, "trusted IF warm reset kept valid cache tags");
    std::cout << "I1_READ_PMA_CACHE_PASS xlen=" << DUT_XLEN << " bytes=" << CACHE_BYTES
        << " checks=" << checks << " requests=" << t.requests
        << " same_hit_latency_MMIO_noAllocate_errors_stale_fill_stalls_reset=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
