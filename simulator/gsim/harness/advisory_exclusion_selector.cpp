// Scan circular age independently. Raw execution ranks are never ordinary-filtered.
#include "AdvisoryExclusionSelectorGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
int main(int argc,char**argv) { try {
    bool inject=argc==2&&std::string(argv[1])=="--inject-rank",injected=false;
    if(argc!=1&&!inject)throw std::runtime_error("unknown argument");
    SAdvisoryExclusionSelectorGsim dut;dut.LOG_START=1;dut.activateAll();
    uint64_t cases=0,mixed=0,calibrated=0,masked=0;
    auto run=[&](unsigned raw,unsigned ordinary,unsigned exclude,unsigned head,bool issued,unsigned issueIndex) {
        std::vector<unsigned> age;
        for(unsigned delta=0;delta<16;++delta){unsigned i=(head+delta)%16;if(raw&(1U<<i))age.push_back(i);}
        unsigned first=age.size()>0?1U<<age[0]:0,second=age.size()>1?1U<<age[1]:0;
        unsigned third=age.size()>2?1U<<age[2]:0, expected=0,index=0;
        for(unsigned i:age)if((ordinary&(1U<<i))&&!(exclude&(1U<<i))&&!(first&(1U<<i))&&!(second&(1U<<i))){expected=1U<<i;index=i;break;}
        dut.set_reset(false);dut.set_io$$raw(raw);dut.set_io$$ordinary(ordinary);
        dut.set_io$$exclusion(exclude);dut.set_io$$head(head);dut.set_io$$issued(issued);dut.set_io$$issuedIndex(issueIndex);dut.step();
        unsigned actual=dut.get_io$$owner();
        if(inject&&!injected&&expected){actual^=expected;injected=true;std::cerr<<"ADVISORY_SELECTOR_INJECTION_REACHED sampled_owner\n";}
        auto require=[&](bool ok,const char*message){if(!ok)throw std::runtime_error(std::string(message)+" raw="+std::to_string(raw)+" ordinary="+std::to_string(ordinary)+" exclusion="+std::to_string(exclude)+" head="+std::to_string(head));};
        require(dut.get_io$$first()==first&&dut.get_io$$second()==second,"independent raw first/second mismatch");
        require(dut.get_io$$oldThird()==third,"independent disabled third mismatch");
        require(actual==expected&&dut.get_io$$decodedOwner()==expected,"independent circular uncovered owner mismatch");
        require(bool(dut.get_io$$valid())==bool(expected),"independent uncovered valid mismatch");
        if(expected)require(dut.get_io$$index()==index,"independent uncovered index mismatch");
        if(ordinary==65535&&!exclude){require(actual==third,"zero-mask allordinary calibration mismatch");++calibrated;}
        ++cases;mixed+=ordinary!=65535;masked+=exclude!=0;
    };
    // All 65536 raw subsets and all 16 heads: OFF exact and zero-mask allordinary.
    for(unsigned raw=0;raw<65536;++raw)for(unsigned head=0;head<16;++head)run(raw,65535,0,head,false,0);
    // Exhaustive independent ordinary/exclusion membership on every circular four-row window.
    for(unsigned head=0;head<16;++head)for(unsigned r=0;r<16;++r)for(unsigned o=0;o<16;++o)for(unsigned e=0;e<16;++e){
        unsigned raw=0,ordinary=0,exclude=0;for(unsigned b=0;b<4;++b){unsigned bit=1U<<((head+b)%16);if(r&(1U<<b))raw|=bit;if(o&(1U<<b))ordinary|=bit;if(e&(1U<<b))exclude|=bit;}
        run(raw,ordinary,exclude,head,true,(head+1)%16);
    }
    std::mt19937_64 random(20261025);
    for(unsigned n=0;n<100000;++n){unsigned raw=random()&65535,ordinary=random()&65535,exclude=random()&65535,head=random()%16,index=random()%16;run(raw,ordinary,exclude,head,n&1,index);}
    // Raw store/atomic ranks may consume the first two positions; never strip the first two ordinary loads.
    run(15,12,0,0,false,0);run(15,8,0,0,false,0);run(15,15,2,0,true,1);run(65535,65535,65535,15,true,15);
    if(inject&&!injected)throw std::runtime_error("requested mutation not reached");
    std::cout<<"ADVISORY_SELECTOR_PASS exhaustive_masks_heads=1048576 cases="<<cases<<" mixed="<<mixed<<" masked="<<masked<<" allordinary_calibration="<<calibrated<<"\n";
    return 0;
} catch(const std::exception&e){std::cerr<<"ADVISORY_SELECTOR_FAIL "<<e.what()<<'\n';return 1;} }
