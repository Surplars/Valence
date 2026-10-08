#include "StoreBufferGsim.h"
#include "virtual_load_test_memory.h"
#include <iostream>
#include <string>
using namespace virtual_load_test;
static void request(SStoreBufferGsim &d, bool valid, uint64_t address) {
    d.set_io$$upstream$$request$$valid(valid);
    d.set_io$$upstream$$request$$bits$$address(address); d.set_io$$upstream$$request$$bits$$data(0);
    d.set_io$$upstream$$request$$bits$$size(3); d.set_io$$upstream$$request$$bits$$mask(255);
    d.set_io$$upstream$$request$$bits$$write(0); d.set_io$$upstream$$request$$bits$$atomic(0);
    d.set_io$$upstream$$request$$bits$$atomicOp(0); d.set_io$$upstream$$request$$bits$$virtualized(0);
    d.set_io$$upstream$$request$$bits$$uncached(0); d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(0);
    d.set_io$$upstream$$request$$bits$$precheckedLoad(1); d.set_io$$upstream$$request$$bits$$translationEpoch(9);
}
static void fast(SStoreBufferGsim &d, bool valid) {
    d.set_io$$fastStore$$valid(valid); d.set_io$$fastStore$$bits$$address(4096);
    d.set_io$$fastStore$$bits$$data(0x8877665544332211ULL);
    d.set_io$$fastStore$$bits$$size(3); d.set_io$$fastStore$$bits$$mask(255);
    d.set_io$$fastStore$$bits$$write(1); d.set_io$$fastStore$$bits$$atomic(0);
    d.set_io$$fastStore$$bits$$atomicOp(0); d.set_io$$fastStore$$bits$$virtualized(0);
    d.set_io$$fastStore$$bits$$uncached(0); d.set_io$$fastStore$$bits$$prefetchNextAllowed(0);
    d.set_io$$fastStore$$bits$$precheckedLoad(0); d.set_io$$fastStore$$bits$$translationEpoch(0);
}
int main(int argc, char **argv) { try {
    const bool inject = argc > 1 && std::string(argv[1]) == "--inject-local";
    for (bool alias : {true, false}) {
        SStoreBufferGsim d; request(d, false, 4096); fast(d, false);
        d.set_io$$upstream$$response$$ready(1); d.set_io$$memory$$request$$ready(1);
        d.set_io$$memory$$response$$valid(0); d.set_io$$memory$$response$$bits$$data(0);
        d.set_io$$memory$$response$$bits$$error(0); d.set_io$$memory$$response$$bits$$pageFault(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        fast(d, true); d.step();
        require(d.get_io$$fastStore$$ready() && d.get_io$$memory$$request$$valid() &&
            d.get_io$$memory$$request$$bits$$write(), "store did not obtain physical ownership");
        fast(d, false); request(d, true, alias ? 4096 : 4104);
        bool issued = false;
        for (unsigned cycle = 0; cycle < 20; ++cycle) {
            d.step();
            require(!d.get_io$$forwarded() && !d.get_io$$upstream$$response$$valid() && !inject,
                "prechecked read bypassed physical reauthorization through local forwarding");
            if (!issued && d.get_io$$upstream$$request$$ready()) {
                require(!alias && !issued && d.get_io$$memory$$request$$valid() &&
                    d.get_io$$memory$$request$$bits$$precheckedLoad() &&
                    d.get_io$$memory$$request$$bits$$translationEpoch() == 9,
                    "buffer lost prechecked ownership/epoch");
                issued = true; request(d, false, 4104);
            }
        }
        d.set_io$$memory$$response$$valid(1); d.step();
        require(d.get_io$$memory$$response$$ready() && !d.get_io$$upstream$$response$$valid(),
            "buffered store response leaked to prechecked read");
        d.set_io$$memory$$response$$valid(0);
        if (alias) {
            for (unsigned n = 0; n < 10 && !issued; ++n) {
                d.step();
                if (d.get_io$$upstream$$request$$ready()) {
                    require(d.get_io$$memory$$request$$valid() &&
                        d.get_io$$memory$$request$$bits$$precheckedLoad(), "alias read did not route to adapter boundary");
                    issued = true;
                }
            }
            request(d, false, 4096);
        }
        require(issued, "prechecked read did not progress after older store drain");
        d.step(); d.set_io$$memory$$response$$valid(1); d.set_io$$memory$$response$$bits$$data(0x0123456789abcdefULL);
        d.step();
        require(d.get_io$$upstream$$response$$valid() && d.get_io$$upstream$$response$$bits$$data() == 0x0123456789abcdefULL,
            "prechecked read used buffered bytes instead of authorized downstream response");
    }
    std::cout << "VIRTUAL_PRECHECKED_STORE_BUFFER_PASS alias_blocked=1 disjoint_routed=1 no_local_bypass=1\n"; return 0;
} catch (const std::exception &e) { std::cerr << "VIRTUAL_PRECHECKED_STORE_BUFFER_FAIL " << e.what() << "\n"; return 1; } }
