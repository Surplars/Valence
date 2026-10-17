#include "FiveStageTileLink.h"
#define FIVE_STAGE_ORACLE_ONLY
#include "five_stage.cpp"

int main(int argc, char **) { try {
    SFiveStageTileLink d;
    std::mt19937_64 rng(0x711a);
    d.set_reset(1);
    d.set_io$$native$$request$$valid(0); d.set_io$$native$$response$$ready(0);
    d.set_io$$tl$$a$$ready(0); d.set_io$$tl$$d$$valid(0); d.set_io$$tl$$b$$valid(0);
    d.set_io$$tl$$c$$ready(0); d.set_io$$tl$$e$$ready(0);
    d.step(); d.step(); d.set_reset(0);
    uint64_t cycles = 0, transfers = 0;
    for (unsigned test = 0; test < 1200; ++test) {
        bool write = test % 3 == 0, error = test % 7 == 0;
        unsigned beats = !write && test % 4 == 0 ? 64 / BYTES : 1;
        unsigned size = beats > 1 ? (N == 64 ? 3 : 2) : test % (N == 64 ? 4 : 3);
        unsigned offset = beats > 1 ? 0 : (rng() % BYTES) & ~((1U << size) - 1);
        uint64_t address = 0x80202000 + (test / 16) * 64;
        unsigned mask = ((1U << (1U << size)) - 1) << offset;
        uint64_t data = fit(rng());
        bool accepted = false; unsigned returned = 0, age = 0;
        std::optional<uint64_t> offered;
        while (returned < beats) {
            need(++age < 300, "adapter bounded completion failed"); ++cycles;
            bool ar = rng() % 4 == 0, nr = rng() % 3 == 0;
            bool dv = accepted && (offered || rng() % 3 == 0);
            if (dv && !offered) offered = fit(rng());
            d.set_io$$native$$request$$valid(!accepted);
            d.set_io$$native$$request$$bits$$address(address);
            d.set_io$$native$$request$$bits$$write(write);
            d.set_io$$native$$request$$bits$$data(data);
            d.set_io$$native$$request$$bits$$mask(mask);
            d.set_io$$native$$request$$bits$$beats(beats);
            d.set_io$$native$$request$$bits$$size(size);
            d.set_io$$native$$request$$bits$$byteOffset(offset);
            d.set_io$$native$$response$$ready(nr); d.set_io$$tl$$a$$ready(ar);
            d.set_io$$tl$$d$$valid(dv); d.set_io$$tl$$d$$bits$$data(offered.value_or(0));
            d.set_io$$tl$$d$$bits$$opcode(write ? 0 : 1);
            d.set_io$$tl$$d$$bits$$source(argc > 1 && test == 10 ? 1 : 0);
            d.set_io$$tl$$d$$bits$$size(beats > 1 ? 6 : size);
            d.set_io$$tl$$d$$bits$$denied(error && test % 2 == 0);
            d.set_io$$tl$$d$$bits$$corrupt(error && test % 2 != 0);
            d.set_io$$tl$$d$$bits$$param(0); d.set_io$$tl$$d$$bits$$sink(0);
            d.step();
            if (d.get_io$$tl$$a$$valid()) {
                need(!accepted, "adapter reused source before final D");
                need(d.get_io$$tl$$a$$bits$$address() == address + offset &&
                    d.get_io$$tl$$a$$bits$$size() == (beats > 1 ? 6 : size) &&
                    d.get_io$$tl$$a$$bits$$mask() == mask &&
                    d.get_io$$tl$$a$$bits$$data() == data &&
                    d.get_io$$tl$$a$$bits$$opcode() == (write ? 1 : 4) &&
                    d.get_io$$tl$$a$$bits$$source() == 0, "independent TL request oracle mismatch");
            }
            need(bool(d.get_io$$native$$request$$ready()) == (!accepted && ar), "native request admission mismatch");
            need(bool(d.get_io$$native$$response$$valid()) == (accepted && dv), "response ownership mismatch");
            if (dv) {
                need(d.get_io$$native$$response$$bits$$data() == *offered &&
                    bool(d.get_io$$native$$response$$bits$$error()) == error &&
                    bool(d.get_io$$native$$response$$bits$$last()) == (returned + 1 == beats),
                    "independent TL response oracle mismatch");
                if (nr) { ++returned; ++transfers; offered.reset(); }
            }
            if (!accepted && ar) { need(d.get_io$$tl$$a$$valid(), "lost TL A offer"); accepted = true; }
        }
        // Step once with neither producer offering; final handshake frees the owner at this edge.
        d.set_io$$native$$request$$valid(0); d.set_io$$tl$$d$$valid(0); d.step();
    }
    std::cout << "FIVE_STAGE_TILELINK_PASS xlen=" << N << " requests=1200 beats=" << transfers
        << " cycles=" << cycles << " subword_burst_denied_corrupt_backpressure=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
