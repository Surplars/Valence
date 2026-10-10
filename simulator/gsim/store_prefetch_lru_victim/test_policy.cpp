#include "policy_oracle.h"
#include <iostream>
using namespace lru_victim_oracle;
int main() {
    try {
        constexpr uint64_t x = 0x1000080010080ULL, y = x + 16384, p = x + 32768;
        unsigned checked = 0;
        // Rows specify first/second validity, dirtiness, conventional oldest,
        // and independently written OFF/ON store / read victim expectations.
        struct Row { unsigned valid, dirty, oldest, off, on, read; bool admitRead; };
        const Row rows[] = {
            {0,0,0,0,0,0,true}, {0,0,1,0,0,0,true},
            {1,0,1,1,1,1,true}, {1,1,1,1,1,1,true},
            {2,0,0,0,0,0,true}, {2,2,0,0,0,0,true},
            {3,0,0,0,0,0,true}, {3,0,1,0,1,0,true},
            {3,1,0,1,0,1,true}, {3,1,1,1,1,1,true},
            {3,2,0,0,0,0,true}, {3,2,1,0,1,0,true},
            {3,3,0,0,0,0,false}, {3,3,1,1,1,1,false}
        };
        for (bool on : {false, true}) for (const auto& row : rows) {
            Policy model(256, on);
            for (unsigned way=0; way<2; ++way) if (row.valid & (1U<<way))
                model.install(way ? y : x, way, row.dirty & (1U<<way), false, false, false);
            if (row.valid == 3) model.hit(row.oldest ? x : y, false);
            for (bool store : {false, true}) {
                const auto c = model.choose(p, true, store);
                const unsigned expected = store ? (on ? row.on : row.off) : row.read;
                require(c.way == expected && c.slot == expected*256+2, "independent victim table mismatch");
                require(c.admissible == (store || row.admitRead), "read-origin dirty admission changed");
                require(!c.victim.valid || c.victim.address == (expected ? y : x), "full-PA victim truncated");
                ++checked;
            }
        }
        for (bool on : {false, true}) {
            Policy model(256, on);
            model.install(x,0,true,false,false,false); model.install(y,1,false,false,false,false);
            require(model.state(p).oldest==0, "new ordinary source did not make dirty destination oldest");
            const auto chosen=model.choose(p,true,true);
            model.capture(chosen.victim.address,chosen.victim.dirty);
            model.install(p,chosen.way,false,true,true,false);
            require(bool(model.find(y))==on, "mixed dirty-old/clean-new source retention mismatch");
            require(model.state(p).oldest==1-chosen.way, "store PF MRU insertion changed");
            const auto before=model.state(p);
            model.install(x,model.choose(x,false,false).way,true,false,false,true);
            require(model.state(p).oldest==before.oldest, "failed refill changed LRU");
            for(unsigned way=0;way<2;++way)
                require(model.state(p).ways[way].address==before.ways[way].address &&
                        model.state(p).ways[way].valid==before.ways[way].valid &&
                        model.state(p).ways[way].dirty==before.ways[way].dirty, "failed refill changed residency");
            model.invalidate(p); require(!model.find(p), "probe did not invalidate full physical line");
            model.install(p,chosen.way,false,true,false,false);
            require(model.state(p).oldest==chosen.way,"read PF insertion changed");
            checked+=8;
            Policy one(256,on,1);
            one.install(x,0,true,false,false,false);
            require(one.choose(p,true,true).way==0 && !one.choose(p,true,false).admissible,
                    "one-way policy/admission changed");
            ++checked;
        }
        std::cout << "STORE_PREFETCH_LRU_HOST_PASS checks=" << checked << " full_pa=1 one_way=1 fault_no_touch=1\n";
    } catch (const std::exception& e) {
        std::cerr << "STORE_PREFETCH_LRU_HOST_FAIL " << e.what() << '\n'; return 1;
    }
}
