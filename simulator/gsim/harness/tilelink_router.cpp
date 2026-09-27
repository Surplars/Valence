#include "TileLinkRouterGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr uint64_t base = 0x80010000;
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }

struct Request { uint64_t address, data; unsigned source, opcode; };
struct Expected { uint64_t data; unsigned opcode, sequence; bool valid, denied; };
struct Reply { uint64_t data; unsigned source, opcode, due, sequence; };

static Request request(unsigned n) {
    unsigned bank = n % 4;
    uint64_t address = bank == 2 && (n / 4) % 2 == 0 ?
        base - 8 * (n / 4 + 1) :
        base + (bank == 0 ? 0 : bank == 2 ? 4096 : 2048) + 8 * (n / 4);
    return {address, 0xdead000000000000ULL + n, n % 8, n % 7 == 0 ? 1U : 4U};
}

static uint64_t readValue(uint64_t address, unsigned source) {
    return 0x1234000000000000ULL ^ address ^ (uint64_t(source) << 40);
}

static void drive(STileLinkRouterGsim &dut, const Request &req, bool valid, bool hostReady,
                  bool ready0, bool ready1, const std::array<std::optional<Reply>, 2> &offered) {
    dut.set_io$$host$$a$$valid(valid);
    dut.set_io$$host$$a$$bits$$opcode(req.opcode);
    dut.set_io$$host$$a$$bits$$param(0);
    dut.set_io$$host$$a$$bits$$size(3);
    dut.set_io$$host$$a$$bits$$source(req.source);
    dut.set_io$$host$$a$$bits$$address(req.address);
    dut.set_io$$host$$a$$bits$$mask(255);
    dut.set_io$$host$$a$$bits$$data(req.data);
    dut.set_io$$host$$a$$bits$$corrupt(0);
    dut.set_io$$host$$d$$ready(hostReady);
    dut.set_io$$host$$b$$ready(0);
    dut.set_io$$host$$c$$valid(0);
    dut.set_io$$host$$e$$valid(0);
    dut.set_io$$bank0$$a$$ready(ready0);
    dut.set_io$$bank1$$a$$ready(ready1);
    dut.set_io$$bank0$$d$$valid(bool(offered[0]));
    dut.set_io$$bank1$$d$$valid(bool(offered[1]));
    dut.set_io$$bank0$$d$$bits$$opcode(offered[0] ? offered[0]->opcode : 0);
    dut.set_io$$bank1$$d$$bits$$opcode(offered[1] ? offered[1]->opcode : 0);
    dut.set_io$$bank0$$d$$bits$$param(0);
    dut.set_io$$bank1$$d$$bits$$param(0);
    dut.set_io$$bank0$$d$$bits$$size(3);
    dut.set_io$$bank1$$d$$bits$$size(3);
    dut.set_io$$bank0$$d$$bits$$source(offered[0] ? offered[0]->source : 0);
    dut.set_io$$bank1$$d$$bits$$source(offered[1] ? offered[1]->source : 0);
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
    bool injectMismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    bool injectWrongOwner = argc == 2 && std::string(argv[1]) == "--inject-wrong-owner";
    STileLinkRouterGsim dut;
    std::array<Expected, 8> expected{};
    std::array<std::optional<Reply>, 2> offered{};
    std::array<std::vector<Reply>, 2> pending;
    drive(dut, {}, false, false, false, false, offered);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    unsigned issued = 0, retired = 0, bank0 = 0, bank1 = 0, unmapped = 0;
    unsigned outOfOrder = 0, highestReturned = 0, aStalls = 0, dStalls = 0;
    bool injected = false, wrongOwnerInjected = false;
    for (unsigned cycle = 0; cycle < 2000; ++cycle) {
        for (unsigned bank = 0; bank < 2; ++bank) {
            if (offered[bank]) continue;
            int selected = -1;
            for (unsigned i = 0; i < pending[bank].size(); ++i) {
                if (pending[bank][i].due <= cycle &&
                    (selected < 0 || pending[bank][i].source > pending[bank][selected].source)) selected = i;
            }
            if (selected >= 0) {
                offered[bank] = pending[bank][selected];
                pending[bank].erase(pending[bank].begin() + selected);
                if (injectMismatch && !injected && offered[bank]->opcode == 1) {
                    offered[bank]->data ^= 1;
                    injected = true;
                }
                if (injectWrongOwner && bank == 1 && !wrongOwnerInjected) {
                    offered[bank]->source = 0;
                    wrongOwnerInjected = true;
                }
            }
        }
        bool valid = issued < 16 && !expected[issued % 8].valid;
        bool hostReady = cycle % 5 != 0;
        bool ready0 = cycle % 7 != 1, ready1 = cycle % 11 != 2;
        Request req = valid ? request(issued) : Request{};
        drive(dut, req, valid, hostReady, ready0, ready1, offered);
        dut.step();
        bool aFire = valid && dut.get_io$$host$$a$$ready();
        bool fire0 = dut.get_io$$bank0$$a$$valid() && ready0;
        bool fire1 = dut.get_io$$bank1$$a$$valid() && ready1;
        if (dut.get_io$$host$$d$$valid()) {
            unsigned source = dut.get_io$$host$$d$$bits$$source();
            check(source < 8 && expected[source].valid, "TileLink router response without request");
            check(dut.get_io$$host$$d$$bits$$data() == expected[source].data &&
                  bool(dut.get_io$$host$$d$$bits$$denied()) == expected[source].denied &&
                  dut.get_io$$host$$d$$bits$$opcode() == expected[source].opcode &&
                  dut.get_io$$host$$d$$bits$$size() == 3,
                  "TileLink router response data, source or route mismatch");
            if (hostReady) {
                if (expected[source].sequence < highestReturned) ++outOfOrder;
                if (expected[source].sequence > highestReturned) highestReturned = expected[source].sequence;
                expected[source].valid = false;
                ++retired;
            } else ++dStalls;
        }
        if (offered[0] && dut.get_io$$bank0$$d$$ready()) offered[0].reset();
        if (offered[1] && dut.get_io$$bank1$$d$$ready()) offered[1].reset();
        if (aFire) {
            unsigned target = req.address >= base && req.address < base + 2048 ? 0 :
                req.address >= base + 2048 && req.address < base + 4096 ? 1 : 2;
            check((fire0 == (target == 0)) && (fire1 == (target == 1)),
                  "TileLink router request sent to wrong bank");
            if (target == 0 || target == 1) {
                unsigned bank = target;
                check((bank == 0 ? dut.get_io$$bank0$$a$$bits$$address() :
                        dut.get_io$$bank1$$a$$bits$$address()) == req.address &&
                      (bank == 0 ? dut.get_io$$bank0$$a$$bits$$source() :
                        dut.get_io$$bank1$$a$$bits$$source()) == req.source,
                      "TileLink router request payload mismatch");
                pending[bank].push_back({req.opcode == 1 ? 0 : readValue(req.address, req.source),
                                         req.source, req.opcode == 1 ? 0U : 1U,
                                         cycle + (bank == 0 ? 15U : 2U), issued});
                if (bank == 0) ++bank0; else ++bank1;
            } else ++unmapped;
            expected[req.source] = {target == 2 || req.opcode == 1 ? 0 : readValue(req.address, req.source),
                                    req.opcode == 1 ? 0U : 1U, issued, true, target == 2};
            ++issued;
        } else if (valid) ++aStalls;
        if (issued == 16 && retired == 16) break;
    }
    check(issued == 16 && retired == 16 && bank0 == 4 && bank1 == 8 && unmapped == 4 &&
          outOfOrder > 0 && aStalls > 0 && dStalls > 0,
          "TileLink router routing, arbitration or backpressure coverage missing");
    std::cout << "GSIM TileLink router: PASS requests=" << issued << " bank0=" << bank0
              << " bank1=" << bank1 << " denied=" << unmapped << " outOfOrderD=" << outOfOrder
              << " aStalls=" << aStalls << " dStalls=" << dStalls << '\n';
}
