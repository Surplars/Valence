#include "I1VpuMemoryReplyFixture.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
using Model=SI1VpuMemoryReplyFixture;
using Wide=unsigned _BitInt(128);
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
struct Case {uint32_t instruction;uint64_t type;unsigned vl,start;bool illegal;};
int main(int argc,char**) {try {
    const Case cases[]={{0x02006087,0x10,0,0,false},{0x020060a7,0x10,0,0,false},
        {0x00006087,0x10,0,0,false},{0x02003087,0x10,0,0,true},
        {0x02006087,(1ULL<<63)|0x10,0,0,true},{0x02006087,0x10,4,4,false}};
    unsigned owners=0,heldCycles=0,commits=0;
    for(const auto &c:cases)for(unsigned stall:{0U,13U,37U}) {
        Model d;
        const Wide token=(Wide(0xa153+owners)<<64)|(0x123456789abc0000ULL+owners);
        d.set_reset(1);d.set_io$$command$$valid(0);d.set_io$$stop(0);
        d.set_io$$context$$ready(1);d.set_io$$contextResult$$valid(0);d.set_io$$contextResult$$bits(0);
        d.set_io$$memoryRequest$$ready(1);d.set_io$$memoryResponse$$valid(0);
        d.set_io$$commit$$ready(0);d.set_io$$completion$$ready(0);d.step();d.step();d.set_reset(0);
        d.set_io$$vl(c.vl);d.set_io$$vtype(c.type);d.set_io$$vstart(c.start);
        d.set_io$$command$$bits$$token(token);d.set_io$$command$$bits$$instruction(c.instruction);
        d.set_io$$command$$bits$$scalar(0x80000000);d.set_io$$command$$bits$$scalar2(0);d.set_io$$command$$bits$$avl(0);
        bool sent=false,seen=false,done=false;unsigned held=0,progress=0;
        for(unsigned cycle=0;cycle<160&&!done;++cycle) {
            if(sent) {d.set_io$$command$$bits$$instruction(0xffffffff);d.set_io$$command$$bits$$token(~token);}
            const bool ready=stall==0||(seen&&held>=stall);
            d.set_io$$command$$valid(!sent);d.set_io$$completion$$ready(ready);
            d.set_io$$commit$$ready(cycle%5!=2);d.set_io$$stop(seen&&!ready&&(held%3==1));d.step();
            check(!d.get_io$$context$$valid()&&!d.get_io$$memoryRequest$$valid(),"empty/illegal LSU touched RF or memory");
            check(!d.get_io$$trim$$valid(),"empty/illegal LSU trimmed VL");
            if(!sent&&d.get_io$$command$$ready())sent=true;
            if(d.get_io$$commit$$valid()&&cycle%5!=2) {
                check(d.get_io$$commit$$bits()==0,"independent empty-range vstart commit oracle");++progress;
            }
            if(d.get_io$$completion$$valid()) {
                seen=true;
                check(sent&&d.get_io$$busy()&&!d.get_io$$command$$ready(),"LSU reply lost owner or admitted overlap");
                const Wide expected=token^(argc>1?Wide(1)<<79:Wide(0));
                check(d.get_io$$completion$$bits$$token()==expected&&
                      d.get_io$$completion$$bits$$instruction()==c.instruction&&
                      bool(d.get_io$$completion$$bits$$illegal())==c.illegal&&
                      !d.get_io$$completion$$bits$$writesScalar()&&d.get_io$$completion$$bits$$scalar()==0,
                      "independent LSU native completion oracle");
                check(!d.get_io$$status$$fault()&&!d.get_io$$status$$interrupted()&&
                      d.get_io$$status$$cause()==0&&d.get_io$$status$$address()==0&&d.get_io$$status$$element()==0,
                      "independent LSU stable status oracle");
                if(!ready){++held;++heldCycles;}else done=true;
            }
        }
        check(done&&progress==unsigned(!c.illegal),"bounded LSU completion/progress owner oracle");
        d.set_io$$command$$valid(0);d.set_io$$completion$$ready(0);d.set_io$$stop(0);d.step();
        check(!d.get_io$$busy()&&d.get_io$$command$$ready()&&!d.get_io$$completion$$valid(),
              "LSU inserted an extra post-completion admission cycle");
        ++owners;commits+=progress;
    }
    std::cout<<"I1_VPU_MEMORY_REPLY_PASS owners="<<owners<<" stalled_completion_cycles="<<heldCycles
             <<" progress_commits="<<commits<<" token80_status_stop_no_overlap_no_extra_cycle=PASS\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
