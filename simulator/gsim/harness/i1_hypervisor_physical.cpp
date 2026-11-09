#include "I1HypervisorPhysicalFixture.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
using Model = SI1HypervisorPhysicalFixture;
static void check(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
struct Case { uint64_t address; unsigned size; bool vector, write, physical, busError; };
int main(int argc, char **) { try {
    const bool inject = argc > 1;
    std::vector<Case> cases;
    for (unsigned size=0; size<4; ++size) for (bool vector:{false,true}) for (bool write:{false,true})
        cases.push_back({0x80001000,size,vector,write,true,false});
    for (bool write:{false,true}) {
        cases.push_back({1ULL<<36,3,false,write,false,false});
        // CPU execute diagnoses misalignment before issuing an operation.
        // The MMU/PMP interval contract itself permits unaligned requests;
        // these must retain the slow authorization owner, not direct bypass.
        cases.push_back({0x80001001,3,false,write,true,false});
        cases.push_back({0x10080000,3,true,write,false,false});
        cases.push_back({0x90000000,3,true,write,false,false});
        cases.push_back({0x10080000,3,false,write,true,false});
        cases.push_back({0x80001000,3,false,write,true,true});
    }
    unsigned completed=0;
    for (const auto &c:cases) for (unsigned stall:{0U,5U}) {
        Model d;
        d.set_reset(1);d.set_io$$address(c.address);d.set_io$$size(c.size);
        d.set_io$$vector(c.vector);d.set_io$$write(c.write);d.set_io$$requestValid(0);
        d.set_io$$physicalReady(0);d.set_io$$returnValid(0);d.set_io$$returnData(0x123456789abcdef0ULL);
        d.set_io$$returnError(c.busError);d.set_io$$replyReady(0);d.step();d.step();d.set_reset(0);
        bool sent=false,returned=false,done=false;unsigned physical=0,due=1000,acceptedAt=1000;
        const bool unaligned=(c.address & ((1ULL<<c.size)-1))!=0;
        for (unsigned cycle=0;cycle<100 && !done;++cycle) {
            const bool ready=cycle>=stall, returning=physical && cycle>=due && !returned;
            const bool replyReady=cycle>=stall+8;
            d.set_io$$requestValid(!sent);d.set_io$$physicalReady(ready);
            d.set_io$$returnValid(returning);d.set_io$$replyReady(replyReady);d.step();
            check(!d.get_io$$walkSeen(),"Bare physical access unexpectedly walked a page table");
            if (!sent && d.get_io$$requestReady()) { sent=true;acceptedAt=cycle; }
            if (d.get_io$$physicalValid()) {
                check(c.physical,"rejected Bare access reached physical memory");
                if (unaligned) check(cycle>acceptedAt,"unaligned request bypassed the slow range owner");
                check(d.get_io$$physicalAddress()==c.address && bool(d.get_io$$physicalWrite())==c.write,
                    "independent physical address/write oracle");
                if (ready) { check(physical++==0,"duplicate physical owner");due=cycle+2; }
            }
            if (returning && d.get_io$$returnReady()) returned=true;
            if (d.get_io$$replyValid()) {
                check(sent,"physical reply without accepted native owner");
                check(bool(d.get_io$$replyError())==(!c.physical || c.busError) &&
                    !d.get_io$$replyPageFault() && !d.get_io$$replyGuestFault(),
                    "independent Bare physical fault classification oracle");
                if (c.physical && !c.busError && !c.write)
                    check(d.get_io$$replyData()==(0x123456789abcdef0ULL ^ uint64_t(inject)),
                        "independent physical data oracle");
                done=replyReady;
            }
        }
        check(done && physical==unsigned(c.physical),"bounded Bare physical completion/owner oracle");
        d.set_io$$requestValid(0);d.set_io$$returnValid(0);d.step();
        check(!d.get_io$$owner(),"Bare physical owner remained after completion");++completed;
    }
    std::cout<<"I1_HYPERVISOR_BARE_PHYSICAL_PASS cases="<<completed
        <<" range_unaligned_slow_owner_vector_MMIO_backpressure_real_error=PASS\n";return 0;
} catch(const std::exception &error) { std::cerr<<error.what()<<'\n';return 1; } }
