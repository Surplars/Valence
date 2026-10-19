#include "FiveStageSoc.h"
#define FIVE_STAGE_ORACLE_ONLY
#include "five_stage.cpp"
#include <fstream>
#include <iterator>
#include <map>
#include "five_stage_jtag_host.h"

#ifndef I1_HAS_ROM
#define I1_HAS_ROM 0
#endif

struct AxiRead { uint64_t address, due; unsigned id, len, size, beat = 0; };
struct AxiWrite { uint64_t address; unsigned id, len, size; };
struct WriteBeat { uint64_t data; unsigned mask; bool last; };
struct AxiReply { unsigned id; uint64_t due; bool error; };
struct AxiMemory {
    SFiveStageSoc &d;
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
    AxiMemory(SFiveStageSoc &model, const std::vector<uint8_t> &image, bool bad, bool faults = true)
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
        d.set_io$$ddrAxi$$ar$$ready(arReady); d.set_io$$ddrAxi$$aw$$ready(awReady);
        d.set_io$$ddrAxi$$w$$ready(wReady); d.set_io$$ddrAxi$$r$$valid(rValid);
        d.set_io$$ddrAxi$$r$$bits$$data(readData);
        d.set_io$$ddrAxi$$r$$bits$$resp(exerciseFaults && sending && sending->address == 0x18000 &&
            sending->beat == sending->len ? 2 : 0);
        d.set_io$$ddrAxi$$r$$bits$$id(sending ? sending->id : 0);
        d.set_io$$ddrAxi$$r$$bits$$last(sending && sending->beat == sending->len);
        d.set_io$$ddrAxi$$b$$valid(bValid);
        d.set_io$$ddrAxi$$b$$bits$$resp(!replies.empty() && replies.front().error ? 2 : 0);
        d.set_io$$ddrAxi$$b$$bits$$id(replies.empty() ? 0 : replies.front().id);
    }
    void outputs(uint64_t cycle) {
        if (rValid && d.get_io$$ddrAxi$$r$$ready()) {
            ++readBeats;
            if (sending->beat++ == sending->len) sending.reset();
        }
        if (bValid && d.get_io$$ddrAxi$$b$$ready()) replies.pop_front();
#define ASIG(PORT, SUFFIX) get_io$$ddrAxi$$ ## PORT ## SUFFIX
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
        std::array<uint64_t, 3> w{d.get_io$$ddrAxi$$w$$bits$$data(), d.get_io$$ddrAxi$$w$$bits$$strb(),
            d.get_io$$ddrAxi$$w$$bits$$last()};
        bool wv = d.get_io$$ddrAxi$$w$$valid();
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

#ifndef FIVE_STAGE_SOC_MEMORY_ONLY
int main(int argc, char **argv) { try {
    need(argc >= 2, "bare SoC image required");
    bool inject = false, jtag = false, badCrc = false, retry = false;
    for (int n = 2; n < argc; ++n) {
        inject |= std::string(argv[n]) == "--inject"; jtag |= std::string(argv[n]) == "--jtag";
        badCrc |= std::string(argv[n]) == "--bad-crc"; retry |= std::string(argv[n]) == "--retry";
    }
    std::ifstream file(argv[1], std::ios::binary); need(bool(file), "missing bare SoC image");
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
    SFiveStageSoc d; AxiMemory memory(d, jtag ? std::vector<uint8_t>{} : image, inject);
    d.set_reset(1); d.set_io$$uartRx(1); d.set_io$$externalIrq(0);
    d.set_io$$clockLocked(0); d.set_io$$ddrReady(0); d.set_io$$jtagLinkUp(jtag);
    d.set_io$$jtagDmi$$request$$valid(0); d.set_io$$jtagDmi$$response$$ready(0);
#if I1_HAS_ROM
    need(argc >= 3, "ROM hex path required");
    std::ifstream rom(argv[2]); need(bool(rom), "missing ROM initialization");
    d.set_io$$romInitialize$$valid(1);
    uint64_t word;
    for (unsigned n = 0; n < 512; ++n) {
        need(bool(rom >> std::hex >> word), "short ROM initialization");
        d.set_io$$romInitialize$$bits$$index(n); d.set_io$$romInitialize$$bits$$data(word);
        memory.inputs(0); d.step();
    }
    need(!(rom >> std::hex >> word), "overlong ROM initialization");
    d.set_io$$romInitialize$$valid(0);
#endif
    memory.inputs(0); d.step(); d.step(); d.set_reset(0);
    I1JtagHost host(d, image, badCrc, retry);
    unsigned traps = 0; uint64_t retired = 0, romRetired = 0;
    constexpr uint64_t readyAt = 20000;
    for (uint64_t cycle = 0; cycle < 2000000; ++cycle) {
        d.set_io$$clockLocked(cycle >= 17); d.set_io$$ddrReady(cycle >= readyAt);
        if (jtag) host.inputs();
        memory.inputs(cycle); d.step(); memory.outputs(cycle); if (jtag) host.outputs();
        if (cycle < readyAt) need(memory.readCount == 0 && memory.writeCount == 0, "DDR accessed before calibration");
        if (cycle < 17) need(!d.get_io$$retire$$valid(), "CPU released before clock lock");
        if (badCrc && host.done && host.rejected) {
            need(retired == 0 && romRetired > 0, "bad CRC reached DDR code");
            std::cout << "FIVE_STAGE_BOOT_CRC_REJECT_PASS rom_retired=" << romRetired << "\n"; return 0;
        }
        // IRQ entry occurs BETWEEN instructions, not as a fake retirement. Count the explicit trap event.
        if (d.get_io$$trapTaken() && d.get_io$$trapCause() != 3) {
            uint64_t cause = d.get_io$$trapCause();
            need(cause == 5 || cause == 7 || cause == 0x8000000000000003ULL || cause == 0x8000000000000007ULL ||
                cause == 0x800000000000000bULL, "unexpected bare SoC trap event"); ++traps;
        }
        if (!d.get_io$$retire$$valid()) continue;
        uint64_t pc = d.get_io$$retire$$bits$$pc();
#if I1_HAS_ROM
        if (pc >= 0x10000 && pc < 0x11000) {
            ++romRetired; need(!d.get_io$$retire$$bits$$trap(), "BootROM trapped"); continue;
        }
#endif
        ++retired;
        if (jtag) need(host.action >= I1JtagHost::Claimed, "CPU entered image before commit");
        need(pc >= 0x80200000 && pc < 0x80200000 + image.size(), "bare SoC retired outside its image");
        if (d.get_io$$retire$$bits$$trap()) {
            uint64_t cause = d.get_io$$retire$$bits$$cause();
            if (cause == 3) {
                // The guest's fail path ALSO ends at EBREAK; the last retired a0 value determines success.
                need(d.get_io$$retire$$bits$$instruction() == 0x00100073, "unexpected breakpoint");
                for (unsigned n = 0; n < 5; ++n) need(memory.load(0x10000 + n * 8) == (n == 3 ? 2 : 1),
                    "bare SoC IRQ/fault completion oracle mismatch");
                need(memory.load(0x7ffffff8) == 0x7c00005a, "2GiB last word/subword mapping mismatch");
                need(traps == 6, "bare SoC precise interrupt/access-fault count mismatch");
                if (jtag) {
                    need(host.done && (!retry || host.rejected), "JTAG claim/protection/retry incomplete");
                    for (unsigned n = 0; n < image.size(); ++n)
                        need(memory.bytes[n] == image[n], "JTAG image bytes corrupted after launch");
                }
                std::cout << "FIVE_STAGE_SOC_PASS cycles=" << cycle << " retired=" << retired
                    << " axi_reads=" << memory.readCount << " axi_writes=" << memory.writeCount
                    << " line_bursts=" << memory.bursts << " max_parallel_reads=" << memory.maxReadOwners
                    << " rom_retired=" << romRetired << " jtag=" << jtag << " retry=" << retry
                    << " ddr_2g_uart_loopback_msip_mtip_plic_mmio_axi_fault=PASS\n"; return 0;
            }
            need(cause == 5 || cause == 7 || cause == 0x8000000000000003ULL || cause == 0x8000000000000007ULL ||
                cause == 0x800000000000000bULL, "unexpected bare SoC exception");
        }
        if (d.get_io$$retire$$bits$$writesRd() && d.get_io$$retire$$bits$$rd() == 10)
            need(d.get_io$$retire$$bits$$data() == 0, "bare SoC guest fail path");
    }
    throw std::runtime_error("bare SoC bounded completion failed");
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
#endif
