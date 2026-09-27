#include "TileLinkCrossbarGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

static constexpr uint64_t base = 0x80000000ULL;
static void check(bool value, const char *message) { if (!value) throw std::runtime_error(message); }

struct Request {
    bool valid = false;
    unsigned opcode = 4, size = 6, source = 0;
    uint64_t address = 0, data = 0;
};
struct Response {
    bool valid = false;
    unsigned opcode = 1, size = 6, source = 0;
    uint64_t data = 0;
    bool denied = false, corrupt = false;
};

static void drive(STileLinkCrossbarGsim &dut, const std::array<Request, 2> &requests,
                  const std::array<Response, 2> &responses, const std::array<bool, 2> &bankReady,
                  const std::array<bool, 2> &masterReady) {
    const auto &a = requests;
    const auto &d = responses;
    dut.set_io$$master0$$a$$valid(a[0].valid);
    dut.set_io$$master1$$a$$valid(a[1].valid);
    dut.set_io$$master0$$a$$bits$$opcode(a[0].opcode);
    dut.set_io$$master1$$a$$bits$$opcode(a[1].opcode);
    dut.set_io$$master0$$a$$bits$$param(0);
    dut.set_io$$master1$$a$$bits$$param(0);
    dut.set_io$$master0$$a$$bits$$size(a[0].size);
    dut.set_io$$master1$$a$$bits$$size(a[1].size);
    dut.set_io$$master0$$a$$bits$$source(a[0].source);
    dut.set_io$$master1$$a$$bits$$source(a[1].source);
    dut.set_io$$master0$$a$$bits$$address(a[0].address);
    dut.set_io$$master1$$a$$bits$$address(a[1].address);
    dut.set_io$$master0$$a$$bits$$mask(255);
    dut.set_io$$master1$$a$$bits$$mask(255);
    dut.set_io$$master0$$a$$bits$$data(a[0].data);
    dut.set_io$$master1$$a$$bits$$data(a[1].data);
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
    dut.set_io$$bank0$$d$$valid(d[0].valid);
    dut.set_io$$bank1$$d$$valid(d[1].valid);
    dut.set_io$$bank0$$d$$bits$$opcode(d[0].opcode);
    dut.set_io$$bank1$$d$$bits$$opcode(d[1].opcode);
    dut.set_io$$bank0$$d$$bits$$param(0);
    dut.set_io$$bank1$$d$$bits$$param(0);
    dut.set_io$$bank0$$d$$bits$$size(d[0].size);
    dut.set_io$$bank1$$d$$bits$$size(d[1].size);
    dut.set_io$$bank0$$d$$bits$$source(d[0].source);
    dut.set_io$$bank1$$d$$bits$$source(d[1].source);
    dut.set_io$$bank0$$d$$bits$$sink(0);
    dut.set_io$$bank1$$d$$bits$$sink(0);
    dut.set_io$$bank0$$d$$bits$$denied(d[0].denied);
    dut.set_io$$bank1$$d$$bits$$denied(d[1].denied);
    dut.set_io$$bank0$$d$$bits$$data(d[0].data);
    dut.set_io$$bank1$$d$$bits$$data(d[1].data);
    dut.set_io$$bank0$$d$$bits$$corrupt(d[0].corrupt);
    dut.set_io$$bank1$$d$$bits$$corrupt(d[1].corrupt);
    dut.set_io$$bank0$$b$$valid(0);
    dut.set_io$$bank1$$b$$valid(0);
    dut.set_io$$bank0$$c$$ready(0);
    dut.set_io$$bank1$$c$$ready(0);
    dut.set_io$$bank0$$e$$ready(0);
    dut.set_io$$bank1$$e$$ready(0);
}

static void reset(STileLinkCrossbarGsim &dut) {
    drive(dut, {}, {}, {false, false}, {false, false});
    dut.set_reset(1);
    dut.step();
    dut.step();
    dut.set_reset(0);
}

static void writeBursts(STileLinkCrossbarGsim &dut) {
    reset(dut);
    std::array<unsigned, 2> accepted{0, 0};
    int activeOwner = -1;
    unsigned stalls = 0;
    for (unsigned cycle = 0; cycle < 100 && (accepted[0] < 8 || accepted[1] < 8); ++cycle) {
        std::array<Request, 2> a{};
        for (unsigned owner = 0; owner < 2; ++owner)
            a[owner] = {accepted[owner] < 8, 0, 6, 0, base + owner * 64,
                        0xabcd000000000000ULL | (uint64_t(owner) << 8) | accepted[owner]};
        const bool ready = cycle % 4 != 1;
        drive(dut, a, {}, {ready, true}, {true, true});
        dut.step();
        check(!dut.get_io$$bank1$$a$$valid(), "64-byte writes left their selected bank");
        if (dut.get_io$$bank0$$a$$valid() && !ready) ++stalls;
        if (!dut.get_io$$bank0$$a$$valid() || !ready) continue;
        const unsigned tag = dut.get_io$$bank0$$a$$bits$$source();
        const unsigned owner = tag >> 3;
        check(owner < 2 && (tag & 7) == 0 && accepted[owner] < 8 &&
              dut.get_io$$bank0$$a$$bits$$opcode() == 0 &&
              dut.get_io$$bank0$$a$$bits$$size() == 6 &&
              dut.get_io$$bank0$$a$$bits$$address() == base + owner * 64 &&
              dut.get_io$$bank0$$a$$bits$$data() ==
                  (0xabcd000000000000ULL | (uint64_t(owner) << 8) | accepted[owner]),
              "TileLink burst A beat or owner mismatch");
        if (activeOwner >= 0 && activeOwner != int(owner))
            check(accepted[activeOwner] == 8, "different A bursts interleaved on one bank");
        activeOwner = int(owner);
        ++accepted[owner];
    }
    check(accepted[0] == 8 && accepted[1] == 8 && stalls > 0,
          "two 64-byte PutFullData bursts or A backpressure were not covered");
    for (unsigned owner = 0; owner < 2; ++owner) {
        const Response ack{true, 0, 6, owner << 3, 0, false, false};
        drive(dut, {}, {ack, {}}, {true, true}, {true, true});
        dut.step();
        check(dut.get_io$$bank0$$d$$ready() &&
              (owner == 0 ? dut.get_io$$master0$$d$$valid() : dut.get_io$$master1$$d$$valid()),
              "burst write acknowledgement went to the wrong master");
    }
}

static void readBursts(STileLinkCrossbarGsim &dut) {
    reset(dut);
    for (unsigned bank = 0; bank < 2; ++bank) {
        const Request get{true, 4, 6, bank + 1, base + uint64_t(bank) * 65536 + 128, 0};
        bool accepted = false;
        for (unsigned cycle = 0; cycle < 10 && !accepted; ++cycle) {
            drive(dut, {get, {}}, {}, {true, true}, {true, true});
            dut.step();
            accepted = dut.get_io$$master0$$a$$ready();
            check((bank == 0 ? dut.get_io$$bank0$$a$$valid() : dut.get_io$$bank1$$a$$valid()) &&
                  (bank == 0 ? dut.get_io$$bank0$$a$$bits$$size() :
                               dut.get_io$$bank1$$a$$bits$$size()) == 6,
                  "64-byte Get was not routed as one A beat");
        }
        check(accepted, "64-byte Get was not accepted");
    }
    std::array<unsigned, 2> beats{0, 0};
    int activeSource = -1;
    unsigned activeBeats = 0, stalls = 0;
    for (unsigned cycle = 0; cycle < 100 && (beats[0] < 8 || beats[1] < 8); ++cycle) {
        std::array<Response, 2> d{};
        for (unsigned bank = 0; bank < 2; ++bank)
            d[bank] = {beats[bank] < 8, 1, 6, bank + 1,
                       0x1234000000000000ULL | (uint64_t(bank) << 8) | beats[bank], false, false};
        const bool ready = cycle % 5 != 2;
        drive(dut, {}, d, {true, true}, {ready, true});
        dut.step();
        check(!dut.get_io$$master1$$d$$valid(), "64-byte read went to the wrong master");
        if (!dut.get_io$$master0$$d$$valid()) continue;
        const unsigned source = dut.get_io$$master0$$d$$bits$$source();
        check(source == 1 || source == 2, "burst read response source changed");
        const unsigned bank = source - 1;
        check(dut.get_io$$master0$$d$$bits$$opcode() == 1 &&
              dut.get_io$$master0$$d$$bits$$size() == 6 &&
              dut.get_io$$master0$$d$$bits$$data() ==
                  (0x1234000000000000ULL | (uint64_t(bank) << 8) | beats[bank]),
              "burst read response data or beat order mismatch");
        if (!ready) { ++stalls; continue; }
        if (activeSource >= 0 && activeSource != int(source))
            check(activeBeats == 8, "D bursts from two banks interleaved at one master");
        if (activeSource != int(source)) { activeSource = int(source); activeBeats = 0; }
        ++activeBeats;
        ++beats[bank];
    }
    check(beats[0] == 8 && beats[1] == 8 && stalls > 0,
          "two 64-byte Get responses or D backpressure were not covered");
    const Request miss{true, 4, 6, 3, base + 2 * 65536, 0};
    drive(dut, {miss, {}}, {}, {true, true}, {true, true});
    dut.step();
    check(dut.get_io$$master0$$a$$ready() && !dut.get_io$$bank0$$a$$valid() &&
          !dut.get_io$$bank1$$a$$valid(), "unmapped burst Get reached a RAM bank");
    for (unsigned beat = 0; beat < 8; ++beat) {
        drive(dut, {}, {}, {true, true}, {true, true});
        dut.step();
        check(dut.get_io$$master0$$d$$valid() && dut.get_io$$master0$$d$$bits$$source() == 3 &&
              dut.get_io$$master0$$d$$bits$$opcode() == 1 &&
              dut.get_io$$master0$$d$$bits$$size() == 6 &&
              dut.get_io$$master0$$d$$bits$$denied() &&
              dut.get_io$$master0$$d$$bits$$corrupt(),
              "unmapped 64-byte Get did not return a complete denied D burst");
    }
}

int main() {
    STileLinkCrossbarGsim dut;
    writeBursts(dut);
    readBursts(dut);
    std::cout << "GSIM TileLink burst fabric: PASS PutFullData=2x8 Get=2x8 deniedGet=8" << '\n';
}
