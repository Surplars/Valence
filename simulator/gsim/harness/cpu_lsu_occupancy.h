#pragma once
#include <stdexcept>
struct CpuLsuOccupancy {
    template<class D> static unsigned sample(D &d,unsigned expected) {
        const unsigned slots=d.get_backendSlotCount();
        if((slots!=2&&slots!=4)||slots!=expected)
            throw std::runtime_error("CPU LSU capacity differs from frozen board profile");
        const unsigned low=d.get_backendSlotState();
        unsigned live=(low&1)+((low>>1)&1);
        if(slots==4){
            const unsigned high=d.get_backendSlotStateHi();
            live+=(high&1)+((high>>1)&1);
            // Both views are actual slot.io.busy aliases in the four-slot wrapper.
            if(live!=d.get_memoryLiveSlots())
                throw std::runtime_error("CPU four-slot LSU occupancy aliases differ");
        }
        return live;
    }
};
