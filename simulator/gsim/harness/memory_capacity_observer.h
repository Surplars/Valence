// Passive scalar occupancy only. Does not enable the two-slot ownership ledgers.
#include "frontend_observer.h"
#include <array>
struct MemoryCapacityObserver : FrontendObserver {
    std::array<uint64_t, 5> liveAll{}, liveRoi{};
    static void sample(SBoardSocGsim &d, void *p) {
        auto &o = *static_cast<MemoryCapacityObserver *>(p);
        const auto live = d.get_memoryLiveSlots();
        if (live > 4) throw std::runtime_error("four-slot occupancy overflow");
        ++o.liveAll[live];
        const bool previouslyActive = o.active;
        FrontendObserver::sample(d, static_cast<FrontendObserver *>(&o));
        if (previouslyActive || o.active) ++o.liveRoi[live];
    }
    void report() {
        FrontendObserver::report();
        for (unsigned n = 0; n <= 4; ++n) {
            std::cout << "MEMORY_LIVE name=whole_run slots=" << n << " cycles=" << liveAll[n] << '\n';
            if (finished)
                std::cout << "MEMORY_LIVE name=coremark_roi slots=" << n << " cycles=" << liveRoi[n] << '\n';
        }
    }
};
