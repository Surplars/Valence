// Independent circular scan; no DUT prefix/rank helper is reused.
#include "ThirdMemoryPreparationRankGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
int main(int argc,char**argv){try{
    bool inject=argc==2&&std::string(argv[1])=="--inject-rank";if(argc>2||(argc==2&&!inject))throw std::runtime_error("unknown argument");
    SThirdMemoryPreparationRankGsim d;d.activateAll();d.set_reset(true);d.step();d.set_reset(false);uint64_t tests=0;bool injected=false;
    for(unsigned head=0;head<16;++head)for(unsigned mask=0;mask<65536;++mask){
        std::vector<unsigned> rank;for(unsigned age=0;age<16;++age){unsigned n=(head+age)%16;if(mask&(1U<<n))rank.push_back(n);}
        bool issued=(mask&1)!=0;unsigned issuedIndex=(mask>>4)&15;
        // Alternate matching and nonmatching first-owner exclusions over the exhaustive domain.
        if((mask&3)==3&&!rank.empty())issuedIndex=rank[0];
        d.set_io$$eligible(mask);d.set_io$$head(head);d.set_io$$headMask((0xffffU<<head)&0xffffU);d.set_io$$issued(issued);d.set_io$$issuedIndex(issuedIndex);d.step();
        auto require=[&](bool ok,const char*m){if(!ok)throw std::runtime_error(std::string(m)+" head="+std::to_string(head)+" mask="+std::to_string(mask));};
        bool third=d.get_io$$thirdValid();unsigned owner=d.get_io$$thirdOwner();
        if(inject&&!injected&&rank.size()>=3&&head!=0){owner^=1U<<rank[2];injected=true;std::cerr<<"THIRD_RANK_INJECTION_REACHED sampled_third_owner\n";}
        require(third==(rank.size()>=3)&&bool(d.get_io$$decodedValid())==third,"independent third validity mismatch");
        require(owner==(rank.size()>=3?1U<<rank[2]:0)&&d.get_io$$decodedOwner()==(rank.size()>=3?1U<<rank[2]:0),"independent circular third owner mismatch");
        if(third)require(d.get_io$$thirdIndex()==rank[2]&&d.get_io$$decodedIndex()==rank[2],"independent third index mismatch");
        require(bool(d.get_io$$firstValid())==!rank.empty()&&bool(d.get_io$$secondValid())==(rank.size()>=2),"original first/second validity changed");
        require(d.get_io$$firstOwner()==(!rank.empty()?1U<<rank[0]:0)&&d.get_io$$secondOwner()==(rank.size()>=2?1U<<rank[1]:0),"original circular ranks changed");
        bool useSecond=issued&&!rank.empty()&&issuedIndex==rank[0];require(bool(d.get_io$$useSecond())==useSecond,"original late exclusion changed");
        bool selected=rank.size()>(useSecond?1U:0U);require(bool(d.get_io$$selectedValid())==selected,"original selection validity changed");
        if(selected)require(d.get_io$$selectedIndex()==rank[useSecond?1:0],"original selected owner changed");
        ++tests;
    }
    if(inject&&!injected)throw std::runtime_error("requested sampled rank mutation not reached");
    std::cout<<"THIRD_RANK_PASS exhaustive_masks_heads="<<tests<<" predecoded_modes=2 original_ranks_preserved=1\n";return 0;
}catch(const std::exception&e){std::cerr<<"THIRD_RANK_FAIL "<<e.what()<<'\n';return 1;}}
