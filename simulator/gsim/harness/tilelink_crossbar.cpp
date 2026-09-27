#include "TileLinkCrossbarGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr uint64_t base = 0x80000000ULL;
static void check(bool good, const char *message) { if (!good) throw std::runtime_error(message); }
static unsigned target(unsigned owner, unsigned n) { return n < 4 ? owner : n & 1; }
static uint64_t address(unsigned owner, unsigned n) {
    return base + uint64_t(target(owner, n)) * 65536 + uint64_t(owner) * 256 + 8 * n;
}
static uint64_t value(unsigned owner, unsigned n) {
    return 0x1234567800000000ULL ^ address(owner, n) ^ (uint64_t(owner) << 48);
}
struct Reply { unsigned tag, due, sequence; uint64_t data; };
struct Expected { bool busy = false; uint64_t data = 0; unsigned sequence = 0; };

static void drive(STileLinkCrossbarGsim &dut, const std::array<unsigned, 2> &issued,
                  const std::array<bool, 2> &masterReady, const std::array<bool, 2> &bankReady,
                  const std::array<std::optional<Reply>, 2> &offered) {
    dut.set_io$$master0$$a$$valid(issued[0] < 8);
    dut.set_io$$master1$$a$$valid(issued[1] < 8);
    dut.set_io$$master0$$a$$bits$$opcode(4);
    dut.set_io$$master1$$a$$bits$$opcode(4);
    dut.set_io$$master0$$a$$bits$$param(0);
    dut.set_io$$master1$$a$$bits$$param(0);
    dut.set_io$$master0$$a$$bits$$size(3);
    dut.set_io$$master1$$a$$bits$$size(3);
    dut.set_io$$master0$$a$$bits$$source(issued[0] & 7);
    dut.set_io$$master1$$a$$bits$$source(issued[1] & 7);
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
    dut.set_io$$bank0$$a$$ready(bankReady[0]);
    dut.set_io$$bank1$$a$$ready(bankReady[1]);
    dut.set_io$$bank0$$d$$valid(bool(offered[0]));
    dut.set_io$$bank1$$d$$valid(bool(offered[1]));
    dut.set_io$$bank0$$d$$bits$$opcode(1);
    dut.set_io$$bank1$$d$$bits$$opcode(1);
    dut.set_io$$bank0$$d$$bits$$param(0);
    dut.set_io$$bank1$$d$$bits$$param(0);
    dut.set_io$$bank0$$d$$bits$$size(3);
    dut.set_io$$bank1$$d$$bits$$size(3);
    dut.set_io$$bank0$$d$$bits$$source(offered[0] ? offered[0]->tag : 0);
    dut.set_io$$bank1$$d$$bits$$source(offered[1] ? offered[1]->tag : 0);
    dut.set_io$$bank0$$d$$bits$$sink(0);
    dut.set_io$$bank1$$d$$bits$$sink(0);
    dut.set_io$$bank0$$d$$bits$$denied(0);
    dut.set_io$$bank1$$d$$bits$$denied(0);
    dut.set_io$$bank0$$d$$bits$$data(offered[0] ? offered[0]->data : 0);
    dut.set_io$$bank1$$d$$bits$$data(offered[1] ? offered[1]->data : 0);
    dut.set_io$$bank0$$d$$bits$$corrupt(0);
    dut.set_io$$bank1$$d$$bits$$corrupt(0);
    dut.set_io$$bank0$$b$$valid(0);
    dut.set_io$$bank1$$b$$valid(0);
    dut.set_io$$bank0$$c$$ready(0);
    dut.set_io$$bank1$$c$$ready(0);
    dut.set_io$$bank0$$e$$ready(0);
    dut.set_io$$bank1$$e$$ready(0);
}

int main(int argc, char **argv) {
    const bool mismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    const bool wrongSource = argc == 2 && std::string(argv[1]) == "--inject-wrong-source";
    STileLinkCrossbarGsim dut;
    std::array<unsigned, 2> issued{0, 0};
    std::array<std::array<Expected, 8>, 2> expected{};
    std::array<std::vector<Reply>, 2> pending;
    std::array<std::optional<Reply>, 2> offered{};
    drive(dut, issued, {false, false}, {false, false}, offered);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    unsigned retired = 0, accepted = 0, dualA = 0, dualD = 0, contention = 0, aStalls = 0, dStalls = 0;
    bool injected = false;
    std::array<std::optional<std::pair<unsigned, uint64_t>>, 2> stalledA{};
    for (unsigned cycle = 0; cycle < 1000 && retired < 16; ++cycle) {
        for (unsigned bank = 0; bank < 2; ++bank) {
            if (offered[bank]) continue;
            int chosen = -1;
            for (unsigned i = 0; i < pending[bank].size(); ++i) {
                if (pending[bank][i].due <= cycle &&
                    (chosen < 0 || pending[bank][i].sequence > pending[bank][chosen].sequence)) chosen = int(i);
            }
            if (chosen >= 0) {
                offered[bank] = pending[bank][chosen];
                pending[bank].erase(pending[bank].begin() + chosen);
                if (mismatch && !injected) { offered[bank]->data ^= 1; injected = true; }
            }
        }
        const std::array<bool, 2> bankReady{cycle % 4 != 0, cycle % 5 != 0};
        const std::array<bool, 2> masterReady{cycle % 7 != 0, cycle % 9 != 0};
        drive(dut, issued, masterReady, bankReady, offered);
        dut.step();
        const std::array<bool, 2> aValid{bool(dut.get_io$$bank0$$a$$valid()),
                                         bool(dut.get_io$$bank1$$a$$valid())};
        const std::array<unsigned, 2> tags{unsigned(dut.get_io$$bank0$$a$$bits$$source()),
                                            unsigned(dut.get_io$$bank1$$a$$bits$$source())};
        const std::array<uint64_t, 2> addresses{dut.get_io$$bank0$$a$$bits$$address(),
                                                 dut.get_io$$bank1$$a$$bits$$address()};
        unsigned aFires = 0, dFires = 0;
        for (unsigned bank = 0; bank < 2; ++bank) {
            if (stalledA[bank]) check(aValid[bank] && tags[bank] == stalledA[bank]->first &&
                                      addresses[bank] == stalledA[bank]->second,
                                      "TileLink crossbar A changed under backpressure");
            stalledA[bank] = aValid[bank] && !bankReady[bank] ?
                std::make_optional(std::make_pair(tags[bank], addresses[bank])) : std::nullopt;
            if (aValid[bank] && bankReady[bank]) {
                const unsigned owner = tags[bank] >> 3;
                const unsigned source = tags[bank] & 7;
                check(owner < 2 && source == issued[owner] && bank == target(owner, source) &&
                      addresses[bank] == address(owner, source),
                      "TileLink crossbar A source, address or bank mismatch");
                check(!expected[owner][source].busy, "TileLink crossbar source reused");
                expected[owner][source] = {true, value(owner, source), accepted};
                pending[bank].push_back({tags[bank], cycle + ((source % 4 == 0) ? 9U : 2U),
                                         accepted, value(owner, source)});
                ++issued[owner]; ++accepted; ++aFires;
            } else if (aValid[bank]) ++aStalls;
        }
        if (aFires == 2) ++dualA;
        if (issued[0] >= 4 && issued[1] >= 4 && issued[0] < 8 && issued[1] < 8 &&
            target(0, issued[0]) == target(1, issued[1])) ++contention;
        for (unsigned owner = 0; owner < 2; ++owner) {
            const bool valid = owner == 0 ? dut.get_io$$master0$$d$$valid() : dut.get_io$$master1$$d$$valid();
            if (!valid) continue;
            const unsigned source = owner == 0 ? dut.get_io$$master0$$d$$bits$$source() :
                                                 dut.get_io$$master1$$d$$bits$$source();
            const uint64_t data = owner == 0 ? dut.get_io$$master0$$d$$bits$$data() :
                                               dut.get_io$$master1$$d$$bits$$data();
            check(source < 8 && expected[owner][source].busy && data == expected[owner][source].data,
                  "TileLink crossbar D source, data or owner mismatch");
            if (masterReady[owner]) { expected[owner][source].busy = false; ++retired; ++dFires; }
            else ++dStalls;
        }
        if (dFires == 2) ++dualD;
        if (offered[0] && dut.get_io$$bank0$$d$$ready()) offered[0].reset();
        if (offered[1] && dut.get_io$$bank1$$d$$ready()) offered[1].reset();
    }
    check(issued[0] == 8 && issued[1] == 8 && retired == 16 && dualA > 0 && dualD > 0 &&
          contention > 0 && aStalls > 0 && dStalls > 0,
          "TileLink crossbar parallel-bank or contention coverage missing");
    if (wrongSource) {
        offered[0] = Reply{15, 0, 0, 0};
        drive(dut, issued, {true, true}, {true, true}, offered);
        dut.step();
        throw std::runtime_error("TileLink crossbar accepted an unsolicited D");
    }
    std::cout << "GSIM TileLink crossbar: PASS requests=" << retired << " dualA=" << dualA
              << " dualD=" << dualD << " contention=" << contention <<
              " aStalls=" << aStalls << " dStalls=" << dStalls << '\n';
}
