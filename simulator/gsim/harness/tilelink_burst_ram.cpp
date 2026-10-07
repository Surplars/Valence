#ifdef SPLIT_BANK
#include "TileLinkSplitBurstRamGsim.h"
using BurstRamDut = STileLinkSplitBurstRamGsim;
#else
#include "TileLinkBurstRamGsim.h"
using BurstRamDut = STileLinkBurstRamGsim;
#endif
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

static constexpr uint64_t base = 0x80010000ULL;
static constexpr std::array<unsigned,8> fullMasks{255,255,255,255,255,255,255,255};
static void check(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }

struct Request {
    bool valid = false;
    unsigned opcode = 4, size = 3, source = 0, mask = 255;
    uint64_t address = 0, data = 0;
};

static void drive(BurstRamDut &dut, const Request &a, bool dReady) {
    dut.set_io$$tl$$a$$valid(a.valid);
    dut.set_io$$tl$$a$$bits$$opcode(a.opcode);
    dut.set_io$$tl$$a$$bits$$param(0);
    dut.set_io$$tl$$a$$bits$$size(a.size);
    dut.set_io$$tl$$a$$bits$$source(a.source);
    dut.set_io$$tl$$a$$bits$$address(a.address);
    dut.set_io$$tl$$a$$bits$$mask(a.mask);
    dut.set_io$$tl$$a$$bits$$data(a.data);
    dut.set_io$$tl$$a$$bits$$corrupt(0);
    dut.set_io$$tl$$d$$ready(dReady);
    dut.set_io$$tl$$b$$ready(0);
    dut.set_io$$tl$$c$$valid(0);
    dut.set_io$$tl$$e$$valid(0);
}

static void putLine(BurstRamDut &dut, uint64_t address,
                    const std::array<uint64_t, 8> &data, unsigned source, bool denied,
                    const std::array<unsigned,8> &masks=fullMasks, bool partial=false) {
    unsigned sent = 0, acknowledgements = 0;
    for (unsigned cycle = 0; cycle < 300 && acknowledgements == 0; ++cycle) {
        Request a{sent < 8, partial?1U:0U, 6, source, masks[sent<8?sent:0], address, data[sent < 8 ? sent : 0]};
        const bool ready = cycle % 5 != 2;
        drive(dut, a, ready);
        dut.step();
        if (a.valid && dut.get_io$$tl$$a$$ready()) ++sent;
        if (dut.get_io$$tl$$d$$valid()) {
            check(sent == 8 && dut.get_io$$tl$$d$$bits$$opcode() == 0 &&
                  dut.get_io$$tl$$d$$bits$$size() == 6 &&
                  dut.get_io$$tl$$d$$bits$$source() == source &&
                  bool(dut.get_io$$tl$$d$$bits$$denied()) == denied,
                  "64-byte PutFullData acknowledgement or error mismatch");
            if (ready) ++acknowledgements;
        }
    }
    check(sent == 8 && acknowledgements == 1,
          "64-byte PutFullData failed to complete");
}

static void get(BurstRamDut &dut, uint64_t address, unsigned size, unsigned source,
                const std::array<uint64_t, 8> &expected, bool denied) {
    const unsigned count = size <= 3 ? 1 : 1U << (size - 3);
    bool issued = false;
    unsigned received = 0, held = 0;
    for (unsigned cycle = 0; cycle < 300 && received < count; ++cycle) {
        const bool ready = cycle % 4 != 1;
        drive(dut, { !issued, 4, size, source, 255, address, 0 }, ready);
        dut.step();
        if (!issued && dut.get_io$$tl$$a$$ready()) issued = true;
        if (!dut.get_io$$tl$$d$$valid()) continue;
        check(issued && dut.get_io$$tl$$d$$bits$$opcode() == 1 &&
              dut.get_io$$tl$$d$$bits$$size() == size &&
              dut.get_io$$tl$$d$$bits$$source() == source &&
              bool(dut.get_io$$tl$$d$$bits$$denied()) == denied &&
              bool(dut.get_io$$tl$$d$$bits$$corrupt()) == denied &&
              dut.get_io$$tl$$d$$bits$$data() == (denied ? 0 : expected[received]),
              "TileLink burst Get beat, source, data or error mismatch");
        if (ready) ++received;
        else ++held;
    }
    check(issued && received == count && (count == 1 || held > 0),
          "TileLink burst Get or D backpressure incomplete");
}

static void drainSmallBeforeBurst(BurstRamDut &dut, uint64_t expected) {
    const Request small{true, 4, 3, 6, 255, base + 64, 0};
    const Request burst{true, 4, 6, 7, 255, base + 64, 0};
    drive(dut, small, false);
    dut.step();
    check(dut.get_io$$tl$$a$$ready(), "small read before burst was not accepted");
    for (unsigned cycle = 0; cycle < 3; ++cycle) {
        drive(dut, burst, false);
        dut.step();
        check(!dut.get_io$$tl$$a$$ready() && dut.get_io$$tl$$d$$valid() &&
              dut.get_io$$tl$$d$$bits$$source() == 6 &&
              dut.get_io$$tl$$d$$bits$$data() == expected,
              "burst overtook a backpressured single-beat response");
    }
    drive(dut, burst, true);
    dut.step();
    check(!dut.get_io$$tl$$a$$ready() && dut.get_io$$tl$$d$$valid(),
          "burst started before the older single-beat response drained");
}
static void readStream(BurstRamDut &dut, const std::array<uint64_t, 8> &expected,
                       bool backpressure = false, bool mixedDenied = false) {
    unsigned issued = 0, received = 0, firstA = 0, lastD = 0;
    std::array<unsigned, 4> aCycles{};
    std::array<unsigned, 4> receivedBySource{};
    for (unsigned cycle = 1; cycle <= 200 && received < 32; ++cycle) {
        const bool ready = !backpressure || cycle % 5 != 2;
        drive(dut, {issued < 4, 4, 6, issued, 255,
            mixedDenied && issued == 1 ? base + 4096 : base + 64, 0}, ready);
        dut.step();
        if (issued < 4 && dut.get_io$$tl$$a$$ready()) {
            aCycles[issued] = cycle;
            if (!firstA) firstA = cycle;
            ++issued;
        }
        if (dut.get_io$$tl$$d$$valid()) {
            const unsigned source = dut.get_io$$tl$$d$$bits$$source();
            check(source < 4 && source < issued && receivedBySource[source] < 8,
                  "streamed line read returned an unknown or excess source");
            const bool denied = mixedDenied && source == 1;
            check(dut.get_io$$tl$$d$$bits$$size() == 6 &&
                  bool(dut.get_io$$tl$$d$$bits$$denied()) == denied &&
                  dut.get_io$$tl$$d$$bits$$data() ==
                      (denied ? 0 : expected[receivedBySource[source]]),
                  "streamed line read returned a wrong beat or source");
            if (ready) { ++receivedBySource[source]; ++received; lastD = cycle; }
        }
    }
    check(issued == 4 && received == 32, "four-line read stream did not finish");
    std::cout << "GSIM TileLink burst read stream: cycles=" << lastD - firstA + 1
              << " backpressure=" << backpressure << " denied=" << mixedDenied
              << " aGaps=" << aCycles[1] - aCycles[0] << ',' << aCycles[2] - aCycles[1]
              << ',' << aCycles[3] - aCycles[2] << '\n';
}

int main(int argc, char **argv) {
    BurstRamDut dut;
    drive(dut, {}, false);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    if(argc==2 && (std::string(argv[1])=="--partial-only" || std::string(argv[1])=="--partial-inject")) {
        std::array<uint64_t,8> expected{};
        expected.fill(0x0123456789abcdefULL);
        putLine(dut,base+64,expected,0,false);
        for(unsigned mask=0;mask<256;++mask) {
            std::array<uint64_t,8> data{}; std::array<unsigned,8> masks{};
            for(unsigned beat=0;beat<8;++beat) {
                masks[beat]=(mask+37*beat)&255;
                data[beat]=0xfedcba9876543210ULL ^ (0x0101010101010101ULL*(mask+beat));
                for(unsigned byte=0;byte<8;++byte) if(masks[beat]&(1U<<byte))
                    expected[beat]=(expected[beat]&~(0xffULL<<(byte*8))) | (data[beat]&(0xffULL<<(byte*8)));
            }
            putLine(dut,base+64,data,1,false,masks,true);
            if(std::string(argv[1])=="--partial-inject") expected[0]^=1;
            get(dut,base+64,6,2,expected,false);
        }
        std::array<unsigned,8> masks{0,1,3,7,15,85,170,255};
        putLine(dut,base+4096,expected,3,true,masks,true);
        get(dut,base+64,6,4,expected,false);
        std::cout<<"TL_RAM_PARTIAL_PASS masks=256 beats=2048 zero_sparse_preserved=1 denied_partial=1\n";
        return 0;
    }
    if (argc == 2 && std::string(argv[1]) == "--inject-control") {
        const Request first{true, 0, 6, 0, 255, base + 64, 0x1122334455667788ULL};
        drive(dut, first, true);
        dut.step();
        check(dut.get_io$$tl$$a$$ready(), "first burst write beat was not accepted");
        Request changed = first;
        changed.source = 1;
        drive(dut, changed, true);
        dut.step();
        throw std::runtime_error("malformed burst source was accepted");
    }
    const std::array<uint64_t, 8> data{
        0x1122334455667788ULL, 0x0123456789abcdefULL, 0x5555aaaa5555aaaaULL,
        0xfedcba9876543210ULL, 0x0000000000000000ULL, 0xffffffffffffffffULL,
        0x0101010101010101ULL, 0x8080808080808080ULL
    };
    putLine(dut, base + 64, data, 0, false);
    drainSmallBeforeBurst(dut, data[0]);
    get(dut, base + 64, 6, 7, data, false);
    get(dut, base + 64, 6, 1, data, false);
    const std::array<uint64_t, 8> one{data[2]};
    get(dut, base + 80, 3, 2, one, false);
#ifdef SPLIT_BANK
    const std::array<uint64_t, 8> secondData{
        0x123456789abcdef0ULL, 0x8899aabbccddeeffULL, 0x76543210fedcba98ULL,
        0x0102030405060708ULL, 0x8000000000000001ULL, 0x0ULL,
        0xdeadbeefcafebabeULL, 0xffeeddccbbaa9988ULL
    };
    putLine(dut, base + 2048 + 64, secondData, 3, false);
    get(dut, base + 2048 + 64, 6, 4, secondData, false);
#endif
    putLine(dut, base + 4096, data, 3, true);
    get(dut, base + 4096, 6, 4, {}, true);
    get(dut, base + 64, 6, 5, data, false);
#ifdef SPLIT_BANK
    get(dut, base + 2048 + 64, 6, 6, secondData, false);
#endif
    readStream(dut, data);
    readStream(dut, data, true, true);
    std::cout << "GSIM TileLink burst RAM: PASS write64 read64 smallRead deniedWrite deniedRead retainedData" << '\n';
}
