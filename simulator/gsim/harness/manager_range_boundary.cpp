#include "ManagerRangeBoundaryGsim.h"
#include <array>
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <new>
#include <set>
#include <stdexcept>
#include <string>
#include <type_traits>
using U128 = unsigned __int128;
struct WindowGeometry { unsigned width, sizeBits, maxSize; uint64_t base, bytes; };
#include "manager_range_geometries.h"
static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
static uint64_t mask(unsigned width){return width==64?UINT64_MAX:(uint64_t(1)<<width)-1;}
static uint64_t cases=0,windows=0,hazards=0,malformed=0,negativeWitness=0;
static std::string mutation;
int main(int argc,char**argv){try{
    for(int i=1;i<argc;++i){std::string arg=argv[i];check(arg.starts_with("--mutate="),"unknown argument");mutation=arg.substr(9);}
    check(mutation.empty()||mutation=="page-only"||mutation=="beat-size"||mutation=="wrap-line-end"||mutation=="drop-owner-carry","unknown mutation");
    static_assert(std::is_standard_layout_v<SManagerRangeBoundaryGsim>);
    alignas(SManagerRangeBoundaryGsim) std::array<std::byte,sizeof(SManagerRangeBoundaryGsim)> storage{};
    auto* d=::new(static_cast<void*>(storage.data())) SManagerRangeBoundaryGsim();
    auto sample=[&](uint64_t address,unsigned size,uint64_t start,U128 end,bool active,bool write){
        d->set_address(address);d->set_size(size);d->set_ownerStart(start);
        d->set_ownerEnd((unsigned _BitInt(65))end);d->set_ownerActive(active);d->set_ownerWrite(write);d->step();++cases;
        const uint64_t flags=d->get_windowFlags();
        for(unsigned i=0;i<std::size(geometries);++i){
            const auto&g=geometries[i];const uint64_t a=address&mask(g.width);
            const unsigned s=size&((1U<<g.sizeBits)-1);const U128 bytes=U128(1)<<s;
            // Independent contract uses complete physical byte intervals. It
            // never uses DUT page decomposition or the AXI per-beat size.
            const bool expected=s<=g.maxSize&&(!g.bytes||(U128(a)>=g.base&&U128(a)+bytes<=U128(g.base)+g.bytes));
            bool observed=(flags>>i)&1;
            if(i%2==1&&g.width>12&&g.bytes&&(U128(g.base)+g.bytes)%4096==0){
                if(mutation=="page-only")observed=s<=g.maxSize&&a>=g.base&&U128(a)<U128(g.base)+g.bytes;
                if(mutation=="beat-size")observed=s<=g.maxSize&&a>=g.base&&U128(a)+(U128(1)<<std::min(s,3U))<=U128(g.base)+g.bytes;
            }
            if(observed!=expected){
                if(!mutation.empty()){++negativeWitness;std::cerr<<"ACTUAL_CORRUPTION count="<<negativeWitness<<" mode="<<mutation<<" target=observed_candidate_window\n";}
                std::cerr<<"window case="<<i<<" address="<<a<<" size="<<s<<" expected="<<expected<<" observed="<<observed<<"\n";
                throw std::runtime_error("independent complete-transfer window oracle mismatch");
            }
            ++windows;if((U128(a)&(bytes-1))!=0)++malformed;
        }
        unsigned j=0;const uint64_t h=d->get_hazardFlags();
        for(unsigned width:{32U,64U}){
            const uint64_t a=(address&mask(width))&~uint64_t(63),s=start&mask(width);
            const U128 e=end&((U128(1)<<(width+1))-1),lineEnd=U128(a)+64;
            const bool expected=active&&write&&U128(a)<e&&U128(s)<lineEnd;
            for(bool local:{false,true}){
                bool observed=(h>>j++)&1;
                if(local&&mutation=="wrap-line-end")observed=active&&write&&U128(a)<e&&s<(uint64_t(lineEnd)&mask(width));
                if(local&&mutation=="drop-owner-carry")observed=active&&write&&U128(a)<(e&mask(width))&&U128(s)<lineEnd;
                if(observed!=expected){
                    if(!mutation.empty()){++negativeWitness;std::cerr<<"ACTUAL_CORRUPTION count="<<negativeWitness<<" mode="<<mutation<<" target=observed_candidate_hazard\n";}
                    throw std::runtime_error("independent interval-overlap hazard oracle mismatch");
                }
                ++hazards;
            }
            const U128 retained=width==32?U128(d->get_lineEnd32()):U128(d->get_lineEnd64());
            check(retained==lineEnd,"actual retained exclusive line end lost carry");
        }
    };
    // Entire TL size encoding domain 0..63. Lower-field geometries consume
    // their declared low size bits, matching their actual input width.
    std::set<uint64_t> pages;
    for(auto g:geometries){
        const U128 limit=U128(g.base)+g.bytes;
        for(U128 edge:{U128(0),U128(g.base),limit,U128(mask(g.width))}){
            if(edge<=UINT64_MAX)pages.insert(uint64_t(edge)&~uint64_t(4095));
            if(edge>=4096&&edge-4096<=UINT64_MAX)pages.insert(uint64_t(edge-4096)&~uint64_t(4095));
        }
    }
    for(uint64_t page:pages)for(unsigned low=0;low<4096;++low)for(unsigned size=0;size<64;++size){
        const uint64_t address=page|low;
        sample(address,size,address&~uint64_t(7),U128(address&~uint64_t(7))+8,true,true);
    }
    // Arbitrary retained endpoints and disabled owner classes, including a
    // carried exclusive endpoint above the highest representable address.
    for(unsigned width:{32U,64U})for(uint64_t line:{uint64_t(0),uint64_t(64),mask(width)&~uint64_t(63)}){
        const U128 limit=U128(mask(width))+1;
        for(uint64_t start:{uint64_t(0),line,line|63,mask(width)})
            for(U128 end:{U128(0),U128(line),U128(line)+1,U128(line)+64,limit})
                for(unsigned enables=0;enables<4;++enables)sample(line,6,start,end,enables&1,enables&2);
    }
    check(mutation.empty(),"requested negative shortcut did not produce a witness");
    d->~SManagerRangeBoundaryGsim();
    std::cout<<"MANAGER_RANGE_BOUNDARY_PASS cases="<<cases<<" actual_windows="<<windows<<" actual_hazards="<<hazards
        <<" malformed_field_cases="<<malformed<<" sizeBits=3,4,5,6 addressWidths=32,64 rejected_constructor_width=12 state_claim=0\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"MANAGER_RANGE_BOUNDARY_FAIL "<<e.what()<<"\n";return 1;}}
