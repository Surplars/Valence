#pragma once
// Independent AXI memory service, shared unchanged by managed CPU test drivers.
// Frozen excerpt SHA-256: ac065c283f2c3d97932ae185fbeec704c5b361cd72c6f46177688c823acd6d29
struct AxiRead { uint64_t address, due; unsigned id, len, size, beat = 0; };
struct AxiWrite { uint64_t address; unsigned id, len, size; };
struct WriteBeat { uint64_t data; unsigned mask; bool last; };
struct AxiReply { unsigned id; uint64_t due; bool error; };
struct AxiMemory {
    Model &d;
    std::map<uint64_t, uint8_t> bytes;
    std::deque<AxiRead> reads;
    std::deque<AxiWrite> addresses;
    std::deque<WriteBeat> writeBeats;
    std::deque<AxiReply> replies;
    std::mt19937_64 rng{0x534f43};
    std::optional<AxiRead> sending;
    uint64_t readData = 0;
    bool arReady = false, awReady = false, wReady = false, rValid = false, bValid = false;
    unsigned readCount = 0, writeCount = 0, maxReadOwners = 0, bursts = 0;
    uint64_t readBeats = 0, writtenBeats = 0, overlapOwnerCycles = 0, readWithWritePending = 0;
    unsigned readLatency = 3, writeLatency = 2;
    std::optional<std::array<uint64_t, 7>> arHeld, awHeld;
    std::optional<std::array<uint64_t, 3>> wHeld;
    bool inject, exerciseFaults;
    AxiMemory(Model &model, const std::vector<uint8_t> &image, bool bad, bool faults = true)
        : d(model), inject(bad), exerciseFaults(faults) {
        for (uint64_t j = 0; j < image.size(); ++j) bytes[j] = image[j];
    }
    uint64_t load(uint64_t address) {
        uint64_t value = 0; for (unsigned j = 0; j < 8; ++j) value |= uint64_t(bytes[address + j]) << (8 * j);
        return value;
    }
    void inputs(uint64_t cycle) {
        arReady = rng() % 3 != 0; awReady = rng() % 3 != 0; wReady = rng() % 4 != 0;
        if (!sending) {
            // Different IDs may complete out of issue order, but a selected R offer is irrevocable.
            for (size_t n = reads.size(); n > 0; --n) if (reads[n - 1].due <= cycle) {
                sending = reads[n - 1]; reads.erase(reads.begin() + n - 1); break;
            }
        }
        rValid = bool(sending); bValid = !replies.empty() && replies.front().due <= cycle;
        if (sending) {
            uint64_t a = sending->address + (uint64_t(sending->beat) << sending->size);
            readData = load(a & ~7ULL);
            if (inject && a == 0x11000) readData ^= 1;
        }
        d.set_io$$memory$$ar$$ready(arReady); d.set_io$$memory$$aw$$ready(awReady);
        d.set_io$$memory$$w$$ready(wReady); d.set_io$$memory$$r$$valid(rValid);
        d.set_io$$memory$$r$$bits$$data(readData);
        d.set_io$$memory$$r$$bits$$resp(exerciseFaults && sending && sending->address == 0x18000 &&
            sending->beat == sending->len ? 2 : 0);
        d.set_io$$memory$$r$$bits$$id(sending ? sending->id : 0);
        d.set_io$$memory$$r$$bits$$last(sending && sending->beat == sending->len);
        d.set_io$$memory$$b$$valid(bValid);
        d.set_io$$memory$$b$$bits$$resp(!replies.empty() && replies.front().error ? 2 : 0);
        d.set_io$$memory$$b$$bits$$id(replies.empty() ? 0 : replies.front().id);
    }
    void outputs(uint64_t cycle) {
        if (rValid && d.get_io$$memory$$r$$ready()) {
            ++readBeats;
            if (sending->beat++ == sending->len) sending.reset();
        }
        if (bValid && d.get_io$$memory$$b$$ready()) replies.pop_front();
#define ASIG(PORT, SUFFIX) get_io$$memory$$ ## PORT ## SUFFIX
#define ADDR(PORT, READY, HELD) \
        std::array<uint64_t, 7> PORT{d.ASIG(PORT, $$bits$$addr)(), \
            d.ASIG(PORT, $$bits$$id)(), d.ASIG(PORT, $$bits$$len)(), \
            d.ASIG(PORT, $$bits$$size)(), d.ASIG(PORT, $$bits$$burst)(), \
            d.ASIG(PORT, $$bits$$cache)(), d.ASIG(PORT, $$bits$$prot)()}; \
        bool PORT##Valid = d.ASIG(PORT, $$valid)(); \
        if (HELD) need(PORT##Valid && PORT == *HELD, "AXI address offer changed under backpressure"); \
        HELD.reset(); if (PORT##Valid && !READY) HELD = PORT; \
        if (PORT##Valid) need(PORT[4] == 1 && PORT[3] <= 3 && PORT[0] < 0x80000000ULL && \
            !(PORT[0] & ((1ULL << PORT[3]) - 1)) && \
            (PORT[0] & 4095) + ((PORT[2] + 1) << PORT[3]) <= 4096, "independent AXI geometry mismatch");
        ADDR(ar, arReady, arHeld) ADDR(aw, awReady, awHeld)
#undef ADDR
#undef ASIG
        if (arValid && arReady) {
            readWithWritePending += !addresses.empty() || !replies.empty() || awValid;
            reads.push_back({ar[0], cycle + readLatency + rng() % 13,
                unsigned(ar[1]), unsigned(ar[2]), unsigned(ar[3])});
            ++readCount; bursts += ar[2] != 0;
        }
        if (awValid && awReady) {
            addresses.push_back({aw[0], unsigned(aw[1]), unsigned(aw[2]), unsigned(aw[3])}); ++writeCount;
        }
        std::array<uint64_t, 3> w{d.get_io$$memory$$w$$bits$$data(), d.get_io$$memory$$w$$bits$$strb(),
            d.get_io$$memory$$w$$bits$$last()};
        bool wv = d.get_io$$memory$$w$$valid();
        if (wHeld) need(wv && w == *wHeld, "AXI W offer changed under backpressure");
        wHeld.reset(); if (wv && !wReady) wHeld = w;
        if (wv && wReady) {
            ++writtenBeats;
            writeBeats.push_back({w[0], unsigned(w[1]), bool(w[2])});
        }
        while (!addresses.empty() && writeBeats.size() >= addresses.front().len + 1) {
            auto a = addresses.front(); addresses.pop_front();
            for (unsigned n = 0; n <= a.len; ++n) {
                auto w = writeBeats.front(); writeBeats.pop_front();
                need(w.last == (n == a.len), "independent AXI WLAST mismatch");
                uint64_t target = (a.address + (uint64_t(n) << a.size)) & ~7ULL;
                for (unsigned j = 0; j < 8; ++j) if (w.mask >> j & 1) bytes[target + j] = w.data >> (8 * j);
            }
            replies.push_back({a.id, cycle + writeLatency + rng() % 11,
                exerciseFaults && a.address == 0x18008});
        }
        maxReadOwners = std::max(maxReadOwners, unsigned(reads.size() + bool(sending)));
        overlapOwnerCycles += (!reads.empty() || bool(sending)) &&
            (!addresses.empty() || !replies.empty() || !writeBeats.empty());
    }
};
