#include "TileLinkAxi4Bridge.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>

#ifdef DDR_2G
static constexpr uint64_t base = 0x80200000ULL;
static constexpr uint64_t end = 0x100200000ULL;
#else
static constexpr uint64_t base = 0x80010000ULL;
#endif
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
#ifdef DDR_2G
using Memory = std::unordered_map<uint64_t, uint8_t>;
#else
using Memory = std::array<uint8_t, 4096>;
#endif

static uint64_t readBeat(const Memory &memory, uint64_t address) {
    const uint64_t offset = (address - base) & ~7ULL;
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) {
#ifdef DDR_2G
        auto entry = memory.find(offset + i);
        value |= uint64_t(entry == memory.end() ? 0 : entry->second) << (8 * i);
#else
        value |= uint64_t(memory.at(offset + i)) << (8 * i);
#endif
    }
    return value;
}
static void writeBeat(Memory &memory, uint64_t address, uint64_t data, unsigned mask) {
    const uint64_t offset = (address - base) & ~7ULL;
    for (unsigned i = 0; i < 8; ++i)
        if (mask & (1U << i)) {
#ifdef DDR_2G
            memory[offset + i] = uint8_t(data >> (8 * i));
#else
            memory.at(offset + i) = uint8_t(data >> (8 * i));
#endif
        }
}

struct Tx {
    bool write;
    unsigned size, source, mask;
    uint64_t address, seed;
    bool error = false;
    bool partial = false;
    bool variedMask = false;
    bool reject = false;
};
static uint64_t payload(const Tx &tx, unsigned beat) {
    return tx.seed ^ (0x0102040810204080ULL * (beat + 1));
}
static unsigned count(const Tx &tx) { return tx.size <= 3 ? 1U : 1U << (tx.size - 3); }
static unsigned maskFor(const Tx &tx, unsigned beat) {
    static constexpr std::array<unsigned,8> masks{0,255,85,170,1,128,7,254};
    return tx.variedMask ? masks[beat%8] : tx.mask;
}

struct Coverage { unsigned transactions = 0, burstReads = 0, burstWrites = 0;
    unsigned readErrors = 0, writeErrors = 0, aStalls = 0, dStalls = 0;
    unsigned arStalls = 0, awStalls = 0, wStalls = 0; };

static void exercise(STileLinkAxi4Bridge &dut, Memory &memory, const Tx &tx,
                     Coverage &coverage, bool badLast = false, bool injectData = false,
                     bool badControl = false) {
    const unsigned beats = count(tx);
    const unsigned dBeats = tx.write ? 1 : beats;
#ifdef DDR_2G
    const uint64_t expectedAxi = tx.address - base;
#else
    const uint64_t expectedAxi = tx.address;
#endif
    unsigned sentA = 0, sentW = 0, sentR = 0, receivedD = 0;
    bool sawAr = false, sawAw = false, sawB = false;
    unsigned arCycle = 0, lastWCycle = 0;
    std::optional<std::tuple<uint64_t, unsigned, unsigned>> heldAr, heldAw;
    std::optional<std::tuple<uint64_t, unsigned, bool>> heldW;
    std::optional<std::tuple<uint64_t, unsigned, bool>> heldD;
    for (unsigned cycle = 0; cycle < 1000 && receivedD < dBeats; ++cycle) {
        const bool aValid = tx.write ? sentA < beats : sentA == 0;
        const bool arReady = cycle % 7 != 1, awReady = cycle % 7 != 2;
        const bool wReady = cycle % 5 != 3, dReady = cycle % 4 != 1;
        const bool rValid = sawAr && sentR < beats && cycle >= arCycle + 3 && cycle % 5 != 2;
        const bool bValid = tx.write && sentW == beats && !sawB && cycle >= lastWCycle + 2;
        dut.set_io$$tl$$a$$valid(aValid);
        dut.set_io$$tl$$a$$bits$$opcode(tx.write ?
            (badControl && sentA==1 ? 0 : tx.partial || tx.size<=3 ? 1 : 0) : 4);
        dut.set_io$$tl$$a$$bits$$param(0);
        dut.set_io$$tl$$a$$bits$$size(tx.size);
        dut.set_io$$tl$$a$$bits$$source(tx.source);
        dut.set_io$$tl$$a$$bits$$address(tx.address);
        dut.set_io$$tl$$a$$bits$$mask(maskFor(tx,sentA));
        dut.set_io$$tl$$a$$bits$$data(payload(tx, sentA));
        dut.set_io$$tl$$a$$bits$$corrupt(0);
        dut.set_io$$tl$$d$$ready(dReady);
        dut.set_io$$tl$$c$$valid(0);
        dut.set_io$$tl$$e$$valid(0);
        dut.set_io$$axi$$ar$$ready(arReady);
        dut.set_io$$axi$$aw$$ready(awReady);
        dut.set_io$$axi$$w$$ready(wReady);
        dut.set_io$$axi$$r$$valid(rValid);
        dut.set_io$$axi$$r$$bits$$id(0);
        dut.set_io$$axi$$r$$bits$$data(rValid ? readBeat(memory,
            tx.address + (tx.size > 3 ? 8 * sentR : 0)) : 0);
        dut.set_io$$axi$$r$$bits$$resp(rValid && tx.error && sentR == beats / 2 ? 2 : 0);
        dut.set_io$$axi$$r$$bits$$last(rValid && (badLast ? sentR == 0 : sentR == beats - 1));
        dut.set_io$$axi$$b$$valid(bValid);
        dut.set_io$$axi$$b$$bits$$id(0);
        dut.set_io$$axi$$b$$bits$$resp(bValid && tx.error ? 2 : 0);
        dut.step();

        const bool arValid = dut.get_io$$axi$$ar$$valid();
        const bool awValid = dut.get_io$$axi$$aw$$valid();
        const bool wValid = dut.get_io$$axi$$w$$valid();
        const bool dValid = dut.get_io$$tl$$d$$valid();
        if (tx.reject) check(!arValid && !awValid && !wValid, "denied range issued AXI traffic");
        const auto ar = std::make_tuple(uint64_t(dut.get_io$$axi$$ar$$bits$$addr()),
            unsigned(dut.get_io$$axi$$ar$$bits$$len()), unsigned(dut.get_io$$axi$$ar$$bits$$size()));
        const auto aw = std::make_tuple(uint64_t(dut.get_io$$axi$$aw$$bits$$addr()),
            unsigned(dut.get_io$$axi$$aw$$bits$$len()), unsigned(dut.get_io$$axi$$aw$$bits$$size()));
        const auto w = std::make_tuple(uint64_t(dut.get_io$$axi$$w$$bits$$data()),
            unsigned(dut.get_io$$axi$$w$$bits$$strb()), bool(dut.get_io$$axi$$w$$bits$$last()));
        const auto d = std::make_tuple(uint64_t(dut.get_io$$tl$$d$$bits$$data()),
            unsigned(dut.get_io$$tl$$d$$bits$$source()), bool(dut.get_io$$tl$$d$$bits$$denied()));
        if (heldAr) check(arValid && ar == *heldAr, "AXI AR changed under backpressure");
        if (heldAw) check(awValid && aw == *heldAw, "AXI AW changed under backpressure");
        if (heldW) check(wValid && w == *heldW, "AXI W changed under backpressure");
        if (heldD) check(dValid && d == *heldD, "TL D changed under backpressure");
        heldAr = arValid && !arReady ? std::optional{ar} : std::nullopt;
        heldAw = awValid && !awReady ? std::optional{aw} : std::nullopt;
        heldW = wValid && !wReady ? std::optional{w} : std::nullopt;
        heldD = dValid && !dReady ? std::optional{d} : std::nullopt;
        if (aValid && dut.get_io$$tl$$a$$ready()) ++sentA;
        else if (aValid) ++coverage.aStalls;
        if (arValid) {
            check(!tx.write && !sawAr && std::get<0>(ar) == expectedAxi &&
                std::get<1>(ar) == beats - 1 &&
                std::get<2>(ar) == (tx.size > 3 ? 3U : tx.size) &&
                dut.get_io$$axi$$ar$$bits$$burst() == 1 &&
                dut.get_io$$axi$$ar$$bits$$id() == 0, "AXI AR burst attributes mismatch");
            if (arReady) { sawAr = true; arCycle = cycle; }
            else ++coverage.arStalls;
        }
        if (awValid) {
            check(tx.write && sentA == beats && !sawAw && std::get<0>(aw) == expectedAxi &&
                std::get<1>(aw) == beats - 1 &&
                std::get<2>(aw) == (tx.size > 3 ? 3U : tx.size) &&
                dut.get_io$$axi$$aw$$bits$$burst() == 1 &&
                dut.get_io$$axi$$aw$$bits$$id() == 0, "AXI AW burst attributes mismatch");
            if (awReady) sawAw = true;
            else ++coverage.awStalls;
        }
        if (wValid) {
            check(tx.write && sawAw && sentW < beats &&
                std::get<0>(w) == (payload(tx, sentW) ^ (injectData && sentW==0 ? 1ULL : 0ULL)) &&
                std::get<1>(w) == maskFor(tx,sentW) &&
                std::get<2>(w) == (sentW == beats - 1), "AXI W data/strobe/WLAST mismatch");
            if (wReady) {
                writeBeat(memory, tx.address + (tx.size > 3 ? 8 * sentW : 0),
                    std::get<0>(w), std::get<1>(w));
                ++sentW;
                if (sentW == beats) lastWCycle = cycle;
            } else ++coverage.wStalls;
        }
        if (rValid && dut.get_io$$axi$$r$$ready()) ++sentR;
        if (bValid && dut.get_io$$axi$$b$$ready()) sawB = true;
        if (dValid) {
            check(sentA == (tx.write ? beats : 1) &&
                (tx.reject || (tx.write ? sawB : sentR == beats)) &&
                dut.get_io$$tl$$d$$bits$$source() == tx.source &&
                dut.get_io$$tl$$d$$bits$$size() == tx.size &&
                dut.get_io$$tl$$d$$bits$$opcode() == (tx.write ? 0 : 1) &&
                bool(dut.get_io$$tl$$d$$bits$$denied()) == tx.error &&
                bool(dut.get_io$$tl$$d$$bits$$corrupt()) == (!tx.write && tx.error) &&
                dut.get_io$$tl$$d$$bits$$data() == (tx.write || tx.error ? 0 :
                    readBeat(memory, tx.address + (tx.size > 3 ? 8 * receivedD : 0))),
                "TL D response beat, data, or error mismatch");
            if (dReady) ++receivedD;
            else ++coverage.dStalls;
        }
    }
    check(sentA == (tx.write ? beats : 1) && receivedD == dBeats &&
        (tx.reject || (tx.write ? sawAw && sentW == beats && sawB : sawAr && sentR == beats)),
        "TL-AXI transaction did not drain");
    ++coverage.transactions;
    if (beats > 1) { if (tx.write) ++coverage.burstWrites; else ++coverage.burstReads; }
    if (tx.error) { if (tx.write) ++coverage.writeErrors; else ++coverage.readErrors; }
}

int main(int argc, char **argv) {
    STileLinkAxi4Bridge dut;
    Memory memory{};
    Coverage coverage;
    dut.set_io$$tl$$a$$valid(0);
    dut.set_io$$tl$$d$$ready(0);
    dut.set_io$$tl$$c$$valid(0);
    dut.set_io$$tl$$e$$valid(0);
    dut.set_io$$axi$$ar$$ready(0);
    dut.set_io$$axi$$aw$$ready(0);
    dut.set_io$$axi$$w$$ready(0);
    dut.set_io$$axi$$r$$valid(0);
    dut.set_io$$axi$$b$$valid(0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
#ifdef DDR_2G
    if (argc == 2 && std::string(argv[1]) == "--ddr2g") {
        const std::array<uint64_t, 8> addresses{
            base, base + 0x100, 0xfffff000ULL, 0xffffffc0ULL,
            0x100000000ULL, 0x100001000ULL, end - 4096, end - 64};
        for (unsigned n = 0; n < addresses.size(); ++n)
            exercise(dut,memory,{true,6,n%8,255,addresses[n],0x0123456789abcdefULL ^ (uint64_t(n)<<40)},coverage);
        // Check all after all writes so high/low address aliasing cannot hide.
        for (unsigned n = 0; n < addresses.size(); ++n)
            exercise(dut,memory,{false,6,n%8,255,addresses[n],0},coverage);
        for (uint64_t address : std::array<uint64_t,3>{base - 8, end, end + 0x100000000ULL}) {
            exercise(dut,memory,{false,3,0,255,address,0,true,false,false,true},coverage);
            exercise(dut,memory,{true,3,1,255,address,1,true,false,false,true},coverage);
        }
        exercise(dut,memory,{true,6,2,255,end,1,true,false,false,true},coverage);
        exercise(dut,memory,{false,6,3,255,end,0,true,false,false,true},coverage);
        std::cout << "DDR2G AXI PASS transactions=" << coverage.transactions
            << " sparseBytes=" << memory.size() << " physicalEnd=0x100200000 offsets=31bits\n";
        return 0;
    }
#endif
    if(argc==2 && std::string(argv[1])=="--bad-partial-mask") {
        exercise(dut,memory,{true,2,0,1,base+0x304,1,false,true},coverage);
        throw std::runtime_error("illegal partial mask accepted");
    }
    if(argc==2 && std::string(argv[1])=="--bad-partial-control") {
        exercise(dut,memory,{true,6,0,255,base+0x100,1,false,true,true},coverage,false,false,true);
        throw std::runtime_error("changed partial opcode accepted");
    }
    if(argc==2 && (std::string(argv[1])=="--partial-only" ||
        std::string(argv[1])=="--partial-single" || std::string(argv[1])=="--partial-inject")) {
        bool negative=std::string(argv[1])=="--partial-inject";
        for(unsigned mask=0;mask<256;++mask) {
            exercise(dut,memory,{true,3,mask%8,mask,base+0x100,0x1020304050607080ULL+mask,false,true},
                coverage,false,negative);
            exercise(dut,memory,{false,3,(mask+1)%8,255,base+0x100,0},coverage);
        }
        if(std::string(argv[1])!="--partial-single") {
            for(unsigned size:{4U,5U,6U,7U}) {
                exercise(dut,memory,{true,size,0,255,base+0x200,0x123456789abcdef0ULL,false,true,true},coverage);
                exercise(dut,memory,{false,size,1,255,base+0x200,0},coverage);
            }
            exercise(dut,memory,{true,6,2,255,base+0x300,0xfedcba9876543210ULL,true,true,true},coverage);
        }
        std::cout<<"TL_AXI_PARTIAL_PASS masks=256 transactions="<<coverage.transactions
            <<" burstWrites="<<coverage.burstWrites<<" wStalls="<<coverage.wStalls<<"\n";
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--high-address") {
        dut.set_io$$tl$$a$$valid(1);
        dut.set_io$$tl$$a$$bits$$opcode(4);
        dut.set_io$$tl$$a$$bits$$param(0);
        dut.set_io$$tl$$a$$bits$$size(3);
        dut.set_io$$tl$$a$$bits$$source(0);
        dut.set_io$$tl$$a$$bits$$address(base + 0x100000000ULL);
        dut.set_io$$tl$$a$$bits$$mask(255);
        dut.set_io$$tl$$a$$bits$$data(0);
        dut.set_io$$tl$$a$$bits$$corrupt(0);
        dut.step();
        throw std::runtime_error("32-bit AXI accepted a truncated TL address");
    }
    if (argc == 2 && std::string(argv[1]) == "--bad-rlast") {
        exercise(dut, memory, {false, 4, 0, 255, base + 0x100, 0}, coverage, true);
        throw std::runtime_error("bad RLAST was accepted");
    }
    if (argc == 2 && std::string(argv[1]) == "--long-burst") {
        exercise(dut, memory, {true, 11, 1, 255, base + 0x800,
            0x1122334455667788ULL}, coverage);
        exercise(dut, memory, {false, 11, 2, 255, base + 0x800, 0}, coverage);
        check(coverage.transactions == 2 && coverage.burstReads == 1 &&
            coverage.burstWrites == 1 && coverage.dStalls && coverage.wStalls,
            "256-beat burst coverage missing");
        std::cout << "GSIM TL-AXI4 256-beat INCR: PASS write/read bytes=2048\n";
        return 0;
    }
    exercise(dut, memory, {true, 6, 1, 255, base + 0x100, 0x1122334455667788ULL}, coverage);
    exercise(dut, memory, {false, 6, 2, 255, base + 0x100, 0}, coverage);
    exercise(dut, memory, {true, 7, 3, 255, base + 0x380, 0x8877665544332211ULL}, coverage);
    exercise(dut, memory, {false, 7, 4, 255, base + 0x380, 0}, coverage);
    exercise(dut, memory, {false, 6, 5, 255, base + 0x100, 0, true}, coverage);
    exercise(dut, memory, {true, 4, 6, 255, base + 0x200, 0x123456789abcdef0ULL, true}, coverage);
    exercise(dut, memory, {true, 2, 7, 240, base + 0x304, 0xfedcba9876543210ULL}, coverage);
    exercise(dut, memory, {false, 2, 0, 240, base + 0x304, 0}, coverage);
    exercise(dut, memory, {false, 4, 1, 255, base + 0xff0, 0}, coverage);
    check(coverage.transactions == 9 && coverage.burstReads == 4 &&
        coverage.burstWrites == 3 && coverage.readErrors == 1 && coverage.writeErrors == 1 &&
        coverage.dStalls && coverage.arStalls && coverage.awStalls &&
        coverage.wStalls, "burst bridge coverage missing");
    std::cout << "GSIM TL-AXI4 burst: PASS transactions=" << coverage.transactions
              << " burstReads=" << coverage.burstReads << " burstWrites=" << coverage.burstWrites
              << " readErrors=" << coverage.readErrors << " writeErrors=" << coverage.writeErrors
              << " aStalls=" << coverage.aStalls << " dStalls=" << coverage.dStalls << '\n';
}
