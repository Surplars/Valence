#include "buffered_return_flow_observer.h"
#include <iostream>
#include <sstream>
#include <string>
using namespace buffered_return_flow;
static Frame empty() {
    Frame f; f.inputReady = true;
    for (unsigned i = 0; i < 16; ++i) f.viewIndices |= uint64_t(i) << (4 * i);
    return f;
}
int main(int argc, char **argv) {
    const std::string mode = argc == 2 ? argv[1] : "";
    try {
        Observer observer;
        Frame f = empty();
        f.allocations[0] = {true, 15, {UINT64_C(0x8000000000000001), 7, 42, 35, true}};
        f.allocations[1] = {true, 0, {UINT64_C(0xffffffffffffffff), 1, 2, 3, true}};
        if (mode == "dual") f.allocations[1].index = 15;
        observer.observeFrame(f);
        f = empty(); f.pending = f.memoryLive = 0x8001;
        f.rows[15] = {UINT64_C(0x8000000000000001), 7, 42, 35, true};
        f.rows[0] = {UINT64_C(0xffffffffffffffff), 1, 2, 3, true};
        if (mode == "index") f.viewIndices ^= UINT64_C(1) << 60;
        if (mode == "raw") f.rawIndices = UINT64_C(1) << 60;
        if (mode == "high-tag") f.rows[15].tag ^= UINT64_C(1) << 63;
        if (mode == "source") f.rows[15].source1 ^= 1;
        if (mode == "unwritten") f.pending |= 2;
        f.inputValid = f.outputValid = true; f.input = f.output = {0x123456789abcdef0, true, true};
        if (mode == "payload") f.output.pageFault = false;
        if (mode == "drop") f.outputValid = false;
        if (mode == "idle") f.adapterIdle = f.backendIdle = true;
        if (mode == "fp") f.fpEpoch = f.integerBusy = true;
        observer.observeFrame(f); // empty + blocked captures exactly once
        f.inputValid = false; f.outputValid = true; f.occupancy = 1; f.outputReady = true;
        observer.observeFrame(f); // pop saved fault
        f = empty(); f.inputValid = f.outputValid = f.outputReady = true;
        f.input = f.output = {0xfeedbeef, false, false};
        observer.observeFrame(f); // direct bypass
        f = empty(); f.inputValid = f.outputValid = true; f.input = f.output = {7, false, false};
        observer.observeFrame(f);
        f.occupancy = 1; f.input = {8, true, false}; f.output = {7, false, false};
        observer.observeFrame(f);
        f.occupancy = 2; f.inputReady = false; f.outputReady = true; f.input = {9, false, true};
        if (mode == "credit") f.inputReady = true;
        observer.observeFrame(f); // full pop has no producer credit
        f.occupancy = 1; f.inputValid = false; f.inputReady = true; f.output = {8, true, false};
        observer.observeFrame(f);
        f = empty(); observer.observeFrame(f);
        f = empty(); f.startValid = true; f.startSlots = 4; f.startToken = {9, UINT64_C(0x8000000000000023)};
        observer.observeFrame(f);
        f = empty(); f.liveSlots = 4; f.slotReplyAccepts = 4;
        if (mode == "slot-unowned") f.slotReplyAccepts = 1;
        if (mode == "slot-overwrite") { f.startValid = true; f.startSlots = 4; }
        if (mode == "slot-early-complete") { f.completeValid = true; f.completeSlots = 4; f.completeToken = {9, UINT64_C(0x8000000000000023)}; }
        observer.observeFrame(f);
        f.slotReplyAccepts = mode == "slot-duplicate" ? 4 : 0;
        if (mode == "slot-duplicate") observer.observeFrame(f);
        f.completeValid = true; f.completeSlots = 4; f.completeToken = {9, UINT64_C(0x8000000000000023)};
        if (mode == "slot-tag") f.completeToken.tag ^= UINT64_C(1) << 63;
        observer.observeFrame(f);
        f = empty(); f.startValid = true; f.startSlots = 1; f.startToken = {3, 123}; f.startForwarded = true;
        observer.observeFrame(f);
        f = empty(); f.liveSlots = 1; f.completeValid = true; f.completeSlots = 1; f.completeToken = {3, 123};
        observer.observeFrame(f); // forwarded completion has no memory response acceptance
        f = empty(); observer.observeFrame(f);
        observer.report(std::cout, "synthetic");
        if (!mode.empty()) throw std::runtime_error("NEGATIVE_NOT_TRIGGERED");
        std::cout << "PASS_SYNTHETIC_OBSERVER_ONLY\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
