#include "RegisterAxiLiteGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static void check(bool ok, const char *reason) { if (!ok) throw std::runtime_error(reason); }
int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SRegisterAxiLiteGsim d;
    std::mt19937_64 random(0x20261004a41ULL);
    constexpr uint64_t base = 0x10040000;
    unsigned reads=0, writes=0, rejects=0, awFirst=0, wFirst=0, stalled=0;
    d.set_io$$registers$$request$$valid(0); d.set_io$$registers$$response$$ready(0);
    d.set_io$$axi$$aw$$ready(0); d.set_io$$axi$$w$$ready(0); d.set_io$$axi$$ar$$ready(0);
    d.set_io$$axi$$b$$valid(0); d.set_io$$axi$$r$$valid(0);
    d.set_io$$axi$$b$$bits(0); d.set_io$$axi$$r$$bits$$data(0); d.set_io$$axi$$r$$bits$$resp(0);
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    for (unsigned number=0; number<240; ++number) {
        const bool write = (number & 1) != 0;
        const unsigned size = number % 7 == 0 ? 3 : number % 3;
        const unsigned offset = (number * 3) & 3;
        uint64_t address = base + 4 * (number % 63) + offset;
        if (number % 17 == 0) address = base - 4;
        if (number % 19 == 0) address = base + 0x40000;
        const uint64_t data = random();
        const unsigned mask = number % 13 == 0 ? 0 : (1u << (1u << size)) - 1;
        const bool bad = address < base || address >= base+0x40000 || size>2 ||
            (address & 3) + (1u << size) > 4;
        const unsigned responseCode = number % 11 == 0 ? 2 : 0;
        const uint32_t aligned = uint32_t(address-base) & ~3u;
        const uint32_t word = aligned ^ 0x7834cdefu;
        bool accepted=false, aw=false, w=false, ar=false, sentReply=false, complete=false;
        unsigned awCycle=999, wCycle=999, responseDue=999;
        bool awStall=false, wStall=false, arStall=false, replyStall=false;
        uint32_t heldAw=0, heldW=0, heldAr=0;
        unsigned heldStrobe=0;
        uint64_t heldReply=0;
        bool heldError=false;
        for (unsigned cycle=0; cycle<160 && !complete; ++cycle) {
            bool awReady = cycle >= ((number/2) % 2 ? 2u : 8u) && (random()%4 != 0);
            bool wReady = cycle >= ((number/2) % 2 ? 8u : 2u) && (random()%4 != 0);
            bool arReady = random()%4 != 0;
            bool responseReady = cycle >= 20 && random()%3 != 0;
            d.set_io$$registers$$request$$valid(!accepted);
            d.set_io$$registers$$request$$bits$$address(address);
            d.set_io$$registers$$request$$bits$$write(write);
            d.set_io$$registers$$request$$bits$$size(size);
            d.set_io$$registers$$request$$bits$$data(data);
            d.set_io$$registers$$request$$bits$$byteEnable(mask);
            d.set_io$$registers$$response$$ready(responseReady);
            d.set_io$$axi$$aw$$ready(awReady); d.set_io$$axi$$w$$ready(wReady);
            d.set_io$$axi$$ar$$ready(arReady);
            d.set_io$$axi$$b$$valid(!sentReply && write && cycle >= responseDue);
            d.set_io$$axi$$b$$bits(responseCode);
            d.set_io$$axi$$r$$valid(!sentReply && !write && cycle >= responseDue);
            d.set_io$$axi$$r$$bits$$data(word); d.set_io$$axi$$r$$bits$$resp(responseCode);
            d.step();
            if (!accepted && d.get_io$$registers$$request$$ready()) accepted=true;
            bool av=d.get_io$$axi$$aw$$valid(), wv=d.get_io$$axi$$w$$valid(), rv=d.get_io$$axi$$ar$$valid();
            check(!bad || (!av && !wv && !rv), "AXI invalid request caused side effect");
            check(!awStall || (av && d.get_io$$axi$$aw$$bits$$addr()==heldAw), "AXI AW stalled payload changed");
            check(!wStall || (wv && d.get_io$$axi$$w$$bits$$data()==heldW &&
                d.get_io$$axi$$w$$bits$$strb()==heldStrobe), "AXI W stalled payload changed");
            check(!arStall || (rv && d.get_io$$axi$$ar$$bits$$addr()==heldAr), "AXI AR stalled payload changed");
            if (av && awReady) {
                check(write && !aw && d.get_io$$axi$$aw$$bits$$addr()==aligned, "AXI AW oracle mismatch");
                check(d.get_io$$axi$$aw$$bits$$prot()==0, "AXI AW protection mismatch");
                aw=true; awCycle=cycle;
            }
            if (wv && wReady) {
                check(write && !w && d.get_io$$axi$$w$$bits$$data()==uint32_t(data << (8*(address&3))) &&
                    d.get_io$$axi$$w$$bits$$strb()==((mask << (address&3))&15), "AXI W oracle mismatch");
                w=true; wCycle=cycle;
            }
            if (rv && arReady) {
                check(!write && !ar && d.get_io$$axi$$ar$$bits$$addr()==aligned, "AXI AR oracle mismatch");
                ar=true;
            }
            if (responseDue==999 && ((write && aw && w) || (!write && ar))) responseDue=cycle+3;
            if (!sentReply && cycle >= responseDue && (write ? d.get_io$$axi$$b$$ready() : d.get_io$$axi$$r$$ready()))
                sentReply=true;
            bool valid=d.get_io$$registers$$response$$valid();
            if (replyStall) check(valid && d.get_io$$registers$$response$$bits$$data()==heldReply &&
                bool(d.get_io$$registers$$response$$bits$$error())==heldError, "AXI upstream reply changed under backpressure");
            if (valid) {
                uint64_t expected = bad || write ? 0 : uint64_t(word >> (8*(address&3)));
                if (inject && number==7) expected ^= 1;
                check(d.get_io$$registers$$response$$bits$$data()==expected &&
                    bool(d.get_io$$registers$$response$$bits$$error())==(bad || responseCode!=0),
                    "AXI register independent oracle mismatch");
                check(bad || sentReply, "AXI replied before downstream response");
                if (responseReady) complete=true;
            }
            awStall=av&&!awReady; heldAw=d.get_io$$axi$$aw$$bits$$addr();
            wStall=wv&&!wReady; heldW=d.get_io$$axi$$w$$bits$$data(); heldStrobe=d.get_io$$axi$$w$$bits$$strb();
            arStall=rv&&!arReady; heldAr=d.get_io$$axi$$ar$$bits$$addr();
            replyStall=valid&&!responseReady; heldReply=d.get_io$$registers$$response$$bits$$data();
            heldError=d.get_io$$registers$$response$$bits$$error();
            stalled += awStall || wStall || arStall || replyStall;
        }
        check(complete, "AXI register transaction timeout");
        if (bad) ++rejects; else if (write) { ++writes; awFirst+=awCycle<wCycle; wFirst+=wCycle<awCycle; }
        else ++reads;
    }
    // Coordinated adapter/slave reset cancels an accepted in-flight request.
    d.set_io$$registers$$request$$valid(1); d.set_io$$registers$$request$$bits$$address(base);
    d.set_io$$registers$$request$$bits$$write(1); d.set_io$$registers$$request$$bits$$size(2);
    d.set_io$$axi$$aw$$ready(0); d.set_io$$axi$$w$$ready(0); d.set_io$$axi$$b$$valid(0);
    d.step(); d.set_io$$registers$$request$$valid(0); d.step();
    d.set_reset(1); d.step(); d.step(); d.set_reset(0); d.step();
    check(d.get_io$$registers$$request$$ready() && !d.get_io$$registers$$response$$valid() &&
        !d.get_io$$axi$$aw$$valid() && !d.get_io$$axi$$w$$valid(), "AXI coordinated reset retained stale transaction");
    check(reads && writes && rejects && awFirst && wFirst && stalled, "AXI coverage incomplete");
    std::cout << "REGISTER_AXI_LITE_PASS transactions=240 reads=" << reads << " writes=" << writes <<
        " rejects=" << rejects << " aw_first=" << awFirst << " w_first=" << wFirst << " stalled=" << stalled << '\n';
    return 0;
} catch(const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
