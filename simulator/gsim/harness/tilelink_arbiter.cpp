#include "TileLinkArbiterGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

static void check(bool good, const char *message) { if (!good) throw std::runtime_error(message); }

struct Reply { unsigned tag, due, sequence; uint64_t data; };
struct Expected { bool busy = false; unsigned sequence = 0; uint64_t data = 0; };

static uint64_t address(unsigned owner, unsigned sequence) {
    return 0x80010000ULL + 0x100ULL * owner + 8ULL * sequence;
}
static uint64_t responseData(unsigned owner, unsigned sequence) {
    return 0xabc0000000000000ULL ^ address(owner, sequence) ^ (uint64_t(owner) << 48);
}

static void drive(STileLinkArbiterGsim &dut, const std::array<unsigned, 2> &issued,
                  const std::array<std::array<Expected, 4>, 2> &expected, bool managerReady,
                  const std::array<bool, 2> &masterReady, const std::optional<Reply> &reply) {
    const bool v0 = issued[0] < 12 && !expected[0][issued[0] % 4].busy;
    const bool v1 = issued[1] < 12 && !expected[1][issued[1] % 4].busy;
    dut.set_io$$master0$$a$$valid(v0);
    dut.set_io$$master1$$a$$valid(v1);
    dut.set_io$$master0$$a$$bits$$opcode(4);
    dut.set_io$$master1$$a$$bits$$opcode(4);
    dut.set_io$$master0$$a$$bits$$param(0);
    dut.set_io$$master1$$a$$bits$$param(0);
    dut.set_io$$master0$$a$$bits$$size(3);
    dut.set_io$$master1$$a$$bits$$size(3);
    dut.set_io$$master0$$a$$bits$$source(issued[0] % 4);
    dut.set_io$$master1$$a$$bits$$source(issued[1] % 4);
    dut.set_io$$master0$$a$$bits$$address(address(0, issued[0]));
    dut.set_io$$master1$$a$$bits$$address(address(1, issued[1]));
    dut.set_io$$master0$$a$$bits$$mask(255);
    dut.set_io$$master1$$a$$bits$$mask(255);
    dut.set_io$$master0$$a$$bits$$data(0);
    dut.set_io$$master1$$a$$bits$$data(0);
    dut.set_io$$master0$$a$$bits$$corrupt(0);
    dut.set_io$$master1$$a$$bits$$corrupt(0);
    dut.set_io$$master0$$d$$ready(masterReady[0]);
    dut.set_io$$master1$$d$$ready(masterReady[1]);
    dut.set_io$$master0$$b$$ready(0);
    dut.set_io$$master1$$b$$ready(0);
    dut.set_io$$master0$$c$$valid(0);
    dut.set_io$$master1$$c$$valid(0);
    dut.set_io$$master0$$e$$valid(0);
    dut.set_io$$master1$$e$$valid(0);
    dut.set_io$$manager$$a$$ready(managerReady);
    dut.set_io$$manager$$d$$valid(bool(reply));
    dut.set_io$$manager$$d$$bits$$opcode(1);
    dut.set_io$$manager$$d$$bits$$param(0);
    dut.set_io$$manager$$d$$bits$$size(3);
    dut.set_io$$manager$$d$$bits$$source(reply ? reply->tag : 0);
    dut.set_io$$manager$$d$$bits$$sink(0);
    dut.set_io$$manager$$d$$bits$$denied(0);
    dut.set_io$$manager$$d$$bits$$data(reply ? reply->data : 0);
    dut.set_io$$manager$$d$$bits$$corrupt(0);
    dut.set_io$$manager$$b$$valid(0);
    dut.set_io$$manager$$c$$ready(0);
    dut.set_io$$manager$$e$$ready(0);
}

int main(int argc, char **argv) {
    const bool mismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    const bool wrongSource = argc == 2 && std::string(argv[1]) == "--inject-wrong-source";
    STileLinkArbiterGsim dut;
    std::array<unsigned, 2> issued{0, 0};
    std::array<std::array<Expected, 4>, 2> expected{};
    std::vector<Reply> pending;
    std::optional<Reply> offered;
    drive(dut, issued, expected, false, {false, false}, offered);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    unsigned retired = 0, accepted = 0, outOfOrder = 0, highestReturned = 0;
    unsigned aStalls = 0, dStalls = 0, contention = 0;
    std::optional<std::pair<unsigned, uint64_t>> stalledA;
    bool injected = false;
    for (unsigned cycle = 0; cycle < 1000 && retired < 24; ++cycle) {
        if (!offered) {
            int chosen = -1;
            for (unsigned i = 0; i < pending.size(); ++i) {
                if (pending[i].due <= cycle &&
                    (chosen < 0 || pending[i].sequence > pending[chosen].sequence)) chosen = int(i);
            }
            if (chosen >= 0) {
                offered = pending[chosen];
                pending.erase(pending.begin() + chosen);
                if (mismatch && !injected) { offered->data ^= 1; injected = true; }
            }
        }
        const bool managerReady = cycle % 5 != 0;
        const std::array<bool, 2> masterReady{cycle % 7 != 0, cycle % 9 != 0};
        const bool v0 = issued[0] < 12 && !expected[0][issued[0] % 4].busy;
        const bool v1 = issued[1] < 12 && !expected[1][issued[1] % 4].busy;
        drive(dut, issued, expected, managerReady, masterReady, offered);
        dut.step();
        const bool aValid = dut.get_io$$manager$$a$$valid();
        const unsigned tag = dut.get_io$$manager$$a$$bits$$source();
        const uint64_t addr = dut.get_io$$manager$$a$$bits$$address();
        if (stalledA) check(aValid && tag == stalledA->first && addr == stalledA->second,
                            "TileLink arbiter A payload changed under backpressure");
        stalledA = aValid && !managerReady ? std::make_optional(std::make_pair(tag, addr)) : std::nullopt;
        if (v0 && v1) ++contention;
        if (aValid && managerReady) {
            const unsigned owner = tag >> 2;
            check(owner < 2 && (tag & 3) == issued[owner] % 4 &&
                  addr == address(owner, issued[owner]) &&
                  dut.get_io$$manager$$a$$bits$$opcode() == 4 &&
                  dut.get_io$$manager$$a$$bits$$size() == 3 &&
                  dut.get_io$$manager$$a$$bits$$mask() == 255,
                  "TileLink arbiter request tag or payload mismatch");
            check((owner == 0 ? dut.get_io$$master0$$a$$ready() : dut.get_io$$master1$$a$$ready()) &&
                  !(owner == 0 ? dut.get_io$$master1$$a$$ready() : dut.get_io$$master0$$a$$ready()),
                  "TileLink arbiter acknowledged the wrong master");
            check(!expected[owner][tag & 3].busy, "TileLink arbiter reused a live source");
            expected[owner][tag & 3] = {true, accepted, responseData(owner, issued[owner])};
            pending.push_back({tag, cycle + ((issued[owner] % 4 == 0) ? 14U : 3U),
                               accepted, responseData(owner, issued[owner])});
            ++issued[owner];
            ++accepted;
        } else if (v0 || v1) ++aStalls;
        if (offered) {
            const unsigned owner = offered->tag >> 2;
            const unsigned source = offered->tag & 3;
            check(owner < 2 && expected[owner][source].busy,
                  "TileLink arbiter response source was not outstanding");
            check((owner == 0 ? dut.get_io$$master0$$d$$valid() : dut.get_io$$master1$$d$$valid()) &&
                  !(owner == 0 ? dut.get_io$$master1$$d$$valid() : dut.get_io$$master0$$d$$valid()) &&
                  (owner == 0 ? dut.get_io$$master0$$d$$bits$$source() :
                                dut.get_io$$master1$$d$$bits$$source()) == source &&
                  (owner == 0 ? dut.get_io$$master0$$d$$bits$$data() :
                                dut.get_io$$master1$$d$$bits$$data()) == expected[owner][source].data,
                  "TileLink arbiter response data, source or destination mismatch");
            if (dut.get_io$$manager$$d$$ready()) {
                if (offered->sequence < highestReturned) ++outOfOrder;
                if (offered->sequence > highestReturned) highestReturned = offered->sequence;
                expected[owner][source].busy = false;
                offered.reset();
                ++retired;
            } else ++dStalls;
        }
    }
    check(issued[0] == 12 && issued[1] == 12 && retired == 24 && contention > 0 &&
          outOfOrder > 0 && aStalls > 0 && dStalls > 0,
          "TileLink arbiter contention, backpressure or out-of-order coverage missing");
    if (wrongSource) {
        offered = Reply{7, 0, 0, 0};
        drive(dut, issued, expected, true, {true, true}, offered);
        dut.step();
        throw std::runtime_error("TileLink arbiter accepted an unsolicited response");
    }
    std::cout << "GSIM TileLink arbiter: PASS requests=" << retired << " contention=" << contention
              << " outOfOrderD=" << outOfOrder << " aStalls=" << aStalls << " dStalls=" << dStalls << '\n';
}
