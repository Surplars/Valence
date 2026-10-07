#include "TranslationContextGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string_view>
static void check(bool v, const char *m) { if (!v) throw std::runtime_error(m); }
int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    STranslationContextGsim d;
    d.set_io$$upstream$$request$$valid(0); d.set_io$$upstream$$response$$ready(0);
    d.set_io$$physical$$request$$ready(0); d.set_io$$physical$$response$$valid(0);
    d.set_io$$physical$$response$$bits$$data(0); d.set_io$$physical$$response$$bits$$error(0);
    d.set_io$$physical$$response$$bits$$pageFault(0);
    d.set_io$$translation$$request$$ready(0); d.set_io$$translation$$response$$valid(0);
    d.set_io$$translation$$response$$bits$$physicalAddress(0x1000);
    d.set_io$$translation$$response$$bits$$pageFault(0); d.set_io$$translation$$response$$bits$$accessFault(0);
    d.set_io$$translation$$response$$bits$$pbmt(0);
    unsigned checked = 0;
    for (unsigned epoch = 0; epoch < 32; ++epoch) {
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        for (unsigned n = 0; n < 2; ++n) {
            const uint64_t satp = (uint64_t{8} << 60) | (uint64_t(epoch + n + 1) << 44) | (0x1234 + n);
            d.set_io$$context$$satp(satp); d.set_io$$context$$dataPrivilege(n ? 0 : 1);
            d.set_io$$context$$sum(n); d.set_io$$context$$mxr(!n);
            d.set_io$$upstream$$request$$valid(1);
            d.set_io$$upstream$$request$$bits$$address(0x4000 + n * 8);
            d.set_io$$upstream$$request$$bits$$atomic(0); d.set_io$$upstream$$request$$bits$$atomicOp(0);
            d.set_io$$upstream$$request$$bits$$write(n); d.set_io$$upstream$$request$$bits$$size(3);
            d.set_io$$upstream$$request$$bits$$data(n); d.set_io$$upstream$$request$$bits$$mask(255);
            d.set_io$$upstream$$request$$bits$$virtualized(1); d.set_io$$upstream$$request$$bits$$uncached(0);
            d.step(); check(d.get_io$$upstream$$request$$ready(), "VM ingress lacks independent capacity");
        }
        d.set_io$$context$$satp(UINT64_MAX); d.set_io$$context$$dataPrivilege(3);
        d.set_io$$context$$sum(0); d.set_io$$context$$mxr(0); d.step();
        check(!d.get_io$$upstream$$request$$ready() && !d.get_io$$idle(), "VM input queue drain/credit mismatch");
        d.set_io$$upstream$$request$$valid(0);
        for (unsigned n = 0; n < 2; ++n) {
            for (unsigned hold = 0; hold < 3; ++hold) {
                d.step();
                uint64_t expected = 0x4000 + n * 8;
                if (inject && epoch == 0 && n == 0) expected ^= 8;
                check(d.get_io$$translation$$request$$valid() &&
                      d.get_io$$translation$$request$$bits$$virtualAddress() == expected &&
                      d.get_io$$translation$$request$$bits$$rootPpn() == 0x1234 + n &&
                      d.get_io$$translation$$request$$bits$$asid() == epoch + n + 1 &&
                      d.get_io$$translation$$request$$bits$$mode() == 8 &&
                      d.get_io$$translation$$request$$bits$$privilege() == (n ? 0 : 1) &&
                      d.get_io$$translation$$request$$bits$$access() == n &&
                      bool(d.get_io$$translation$$request$$bits$$sum()) == bool(n) &&
                      bool(d.get_io$$translation$$request$$bits$$mxr()) == !bool(n),
                      "VM context independent oracle mismatch"); ++checked;
            }
            d.set_io$$translation$$request$$ready(1); d.step();
            d.set_io$$translation$$request$$ready(0); d.set_io$$translation$$response$$valid(1); d.step();
            d.set_io$$translation$$response$$valid(0);
        }
    }
    d.set_reset(1); d.step(); d.step(); d.set_reset(0); d.step();
    check(d.get_io$$idle(), "VM reset retained queued context");
    std::cout << "TRANSLATION_CONTEXT_PASS checked=" << checked << " epochs=32 contexts=64\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
