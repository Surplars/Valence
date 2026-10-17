#include "I1FlowResponseQueueFixture.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef I1_RESPONSE_ENTRIES
#define I1_RESPONSE_ENTRIES 2
#endif
static void need(bool good, const char *why) {
    if (!good) throw std::runtime_error(why);
}
struct Word { uint64_t data; bool error, page; };
int main(int argc, char **argv) { try {
    SI1FlowResponseQueueFixture d;
    const bool wrong = argc > 1 && std::string_view(argv[1]) == "--wrong-data";
    std::mt19937_64 random{0x4341434845524554ULL};
    std::deque<Word> fifo;
    std::optional<Word> offer;
    unsigned accepted=0, consumed=0, flow=0, stalls=0, full=0, turnover=0, resets=0;
    auto reset = [&] {
        d.set_reset(1); d.set_io$$enq$$valid(0); d.set_io$$deq$$ready(0);
        d.set_io$$enq$$bits$$data(0); d.set_io$$enq$$bits$$error(0);
        d.set_io$$enq$$bits$$pageFault(0); d.step(); d.step(); d.set_reset(0);
        fifo.clear(); offer.reset(); ++resets;
    };
    auto tick = [&](bool produce, bool ready) {
        if (!offer && produce) offer=Word{random(),bool(random()&1),bool(random()&1)};
        const Word input=offer.value_or(Word{random(),bool(random()&1),bool(random()&1)});
        const bool valid=offer.has_value(), empty=fifo.empty();
        const bool credit=fifo.size()<I1_RESPONSE_ENTRIES;
        const bool outValid=!empty || valid;
        const Word output=empty ? input : fifo.front();
        d.set_io$$enq$$valid(valid); d.set_io$$deq$$ready(ready);
        d.set_io$$enq$$bits$$data(input.data); d.set_io$$enq$$bits$$error(input.error);
        d.set_io$$enq$$bits$$pageFault(input.page); d.step();
        need(bool(d.get_io$$enq$$ready())==credit &&
            bool(d.get_io$$deq$$valid())==outValid && d.get_io$$count()==fifo.size(),
            "independent flow response occupancy/credit oracle");
        if (outValid)
            need(d.get_io$$deq$$bits$$data()==(output.data ^ uint64_t(wrong)) &&
                bool(d.get_io$$deq$$bits$$error())==output.error &&
                bool(d.get_io$$deq$$bits$$pageFault())==output.page,
                "independent flow response byte/status oracle");
        const bool push=valid && credit, pop=outValid && ready;
        flow+=empty && push && pop; stalls+=outValid && !ready;
        full+=!credit; turnover+=push && pop && !empty;
        if (pop) { if (!empty) fifo.pop_front(); ++consumed; }
        if (push) {
            if (!(empty && pop)) fifo.push_back(input);
            offer.reset(); ++accepted;
        }
    };
    reset();
    for (unsigned cycle=0; cycle<30000; ++cycle) {
        if (cycle && cycle%1997==0) { reset(); continue; }
        const unsigned phase=cycle%149;
        tick(phase<70 || (phase>100 && (random()&1)),
            phase>=48 && (phase>105 || (random()&3)!=0));
    }
    for (unsigned cycle=0; cycle<I1_RESPONSE_ENTRIES+3; ++cycle) tick(false,true);
    need(fifo.empty() && !offer && accepted && consumed && flow && stalls && full && turnover && resets==16,
        "missing flow response reset/full/turnover coverage");
    std::cout << "I1_FLOW_RESPONSE_QUEUE_PASS entries=" << I1_RESPONSE_ENTRIES
        << " cycles=30000 resets=" << resets << " accepted=" << accepted
        << " consumed=" << consumed << " flow=" << flow
        << " retained_credit_order_error_page_status_backpressure=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
