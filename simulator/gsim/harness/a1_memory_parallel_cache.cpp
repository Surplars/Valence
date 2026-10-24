// Reuse the independent byte-memory/protocol oracle, not a frozen RTL model.
// Two response credits are intentional: never enqueue the legacy eight-credit
// stress sequence while CPU ready is held low.
#define COHERENT_READ_MSHR_HEADER "CommonA1MemoryCacheGsim.h"
#define SCoherentReadMshrGsim SCommonA1MemoryCacheGsim
#define COHERENT_READ_MSHR_EMBED
#define INDEPENDENT_DEMAND_ADMISSION
#define READ_MSHRS 2
#define WRITEBACK_ENTRIES 2
#define CACHE_LINES 512
#define CACHE_WAYS 2
#define CACHE_BASE 0x80200000ULL
#include "coherent_read_mshr.cpp"

int main(int argc, char **argv) { try {
    injectMismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    const uint64_t sameSet = 64ULL * CACHE_LINES / CACHE_WAYS;
    {
        Test t; t.blockCpu = true;
        unsigned grants = 0; uint64_t firstGrant = 0;
        t.afterStep = [&](Test &x, const Test::Edge &edge) {
            if (edge.dValid && !edge.releaseAck && x.d.get_io$$tl$$d$$ready()) {
                // D is a manager-driven input: the independent offered source,
                // paired with DUT READY, defines this real accepted grant beat.
                check(x.grant.has_value(), "accepted GrantData lacks a manager source owner");
                const unsigned source = x.acquires.at(*x.grant).source;
                if (!grants++) firstGrant = source;
            }
        };
        t.offer({base}, false); t.offer({base + sameSet}, false);
        t.until([&] { return t.acquires.size() == 2; }, "both actual A1 acquire owners must issue", 512);
        check(t.d.get_io$$mshrOccupancy() == 2, "actual cache geometry lost its two MSHRs");
        t.until([&] { return t.acquires.empty(); }, "source-reversed grants did not finish", 512);
        check(grants == 16 && firstGrant == 1 && t.returned == 0,
            "manager did not reverse two full grants while CPU replies were held");
        t.request = Request{base + 128}; const auto before = t.accepted;
        for (unsigned n = 0; n < 8; ++n) t.tick();
        check(t.accepted == before, "two held CPU replies failed to retain both response credits");
        t.blockCpu = false; t.drain();
        check(t.accepted == 3 && t.returned == 3, "ordered replies lost or duplicated accepted requests");
    }
    {
        Test t; t.offer({base}); t.blockCpu = true;
        t.offer({base + sameSet, true, 0x1122334455667788ULL}, false);
        t.offer({base}, false);
        check(t.accepted == 3 && t.returned == 1, "resident opposite way remained globally blocked");
        t.blockCpu = false; t.drain(); t.flush();
        check(t.backing.at(base + sameSet) == 0x1122334455667788ULL, "dirty store lost actual writeback");
    }
    {
        Test t; t.offer({base}); t.blockCpu = true;
        t.offer({base + 64}, false); t.offer({base, true, 0xaabbccddeeff0011ULL, 0x55}, false);
        check(t.accepted == 3 && t.returned == 1, "independent resident store lost response reservation");
        t.blockCpu = false; t.drain(); t.offer({base}); t.probe(base);
    }
    {
        Test t; t.blockCpu = true; t.denyLine = base;
        t.offer({base, true, 0xdeadbeef}, false); t.offer({base + sameSet}, false);
        t.blockCpu = false; t.drain(); t.denyLine = ~0ULL;
        t.offer({base}); t.flush();
        check(t.backing.at(base) == Test::initial(base), "denied refill performed a store");
    }
    {
        Test t; t.blockCpu = true; t.probeAfterAck = true;
        t.offer({base}, false);
        t.until([&] { return t.probeDone; }, "held CPU reply blocked required coherence probe", 512);
        t.blockCpu = false; t.drain(); t.offer({base});
        check(t.aCount == 2, "probe invalidation did not survive held response ownership");
    }
    std::cout << "A1_MEMORY_CACHE_PASS mshrs=2 responses=2 writebacks=2 reversed_grant_beats=16"
        << " ordered_cpu=1 held_credits=1 independent_way=1 denied_store=1 probe_drain=1\n";
    return 0;
} catch (const std::exception &e) { std::cerr << "A1_MEMORY_CACHE_FAIL " << e.what() << '\n'; return 1; } }
