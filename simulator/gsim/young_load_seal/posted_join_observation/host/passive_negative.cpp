#include "passive_supply.h"
struct MockProbe {
    bool rv=false,rf=false,cf=false,av=false,af=false,hv=false;
    uint64_t pa=0x80400000,ap=0x80400000,hl=0;
    unsigned as=0;std::array<unsigned,2> phases{},sources{};
    std::array<uint64_t,2> addresses{0x80404000,0x81404000};
    static void guard(bool v){PassiveSupply::require(v,"passive invalid payload accessed");}
    bool reqValid(){return rv;}bool reqFire(){return rf;}bool independentReqFire(){return rf;}
    bool cacheFire(){return cf;}bool flush(){return false;}
    uint64_t reqPa(){guard(rv);return pa;}uint64_t reqMeta(){guard(rv);return 0;}
    bool hint(){guard(rv);return true;}bool ordinary(){guard(cf);return true;}
    bool historyValid(){guard(cf);return hv;}uint64_t historyLine(){guard(cf&&hv);return hl;}
    bool candidate(){return false;}bool candidateStore(){guard(false);return false;}
    bool allocate(){return false;}bool allocateStore(){guard(false);return false;}
    bool pending(){return false;}bool live(){return false;}bool release(){return false;}
    bool readResident(){return false;}bool readConsume(){guard(false);return false;}bool posted(){return true;}
    bool aValid(){return av;}bool aFire(){guard(av);return af;}
    uint64_t aPa(){guard(av);return ap;}unsigned aSource(){guard(av);return as;}
    unsigned homePhase(unsigned i){guard(av&&i<2);return phases[i];}
    uint64_t homePa(unsigned i){guard(av&&i<2&&phases[i]!=0);return addresses[i];}
    unsigned homeSource(unsigned i){guard(av&&i<2&&phases[i]!=0);return sources[i];}
    bool owned(unsigned i){guard(av&&i<512);return false;}
};
int main(int argc,char **argv){try{
    const std::string mode=argc>1?argv[1]:"";PassiveSupply gate;MockProbe p;
    auto idle=gate.capture(p);
    PassiveSupply::require(!idle.aFire&&!idle.aPa&&!idle.sameSet&&!idle.sourceBusy&&!idle.directoryFull,"passive idle A fields must be UNKNOWN");
    if(mode=="--invalid-payload")p.aPa();
    if(mode=="--sum")gate.report(1,0);
    if(mode=="--history"){
        gate.historyValid=true;gate.historyLine=p.pa>>6;p.rv=p.rf=p.cf=p.hv=true;p.hl=(p.pa>>6)+1;gate.capture(p);
    }
    p.av=true;p.phases[0]=1;
    if(mode=="--phase")p.phases[0]=5;
    if(mode=="--pa")p.ap|=1;
    if(mode=="--source")p.as=2;
    auto blocked=gate.capture(p);gate.count(blocked);
    PassiveSupply::require(*blocked.sameSet&&*blocked.sourceBusy&&!*blocked.directoryFull,"passive home blocker derivation");
    PassiveSupply::require(gate.homeBlockedMasks[3]==1,"passive home bitmask exclusivity");
    for(unsigned mask=0;mask<32;++mask){
        PassiveSupply::Sample s;s.reqValid=s.reqFire=s.cacheFire=true;s.pa=p.pa;s.meta=0;s.hint=s.ordinary=s.sequential=true;
        s.pending=mask&1;s.live=mask&2;s.release=mask&4;s.ownResident=mask&8;s.posted=!(mask&16);
        s.candidate=s.candidateRead=mask==0;
        if(mode=="--bucket"&&mask==1)s.candidateRead=true;
        gate.count(s);
    }
    for(auto n:gate.opportunityMasks)PassiveSupply::require(n==1,"passive formation bucket is not exclusive");
    gate.report(1,0);std::cout<<"PASSIVE_MOCK_VALID_GUARDS_AND_EXCLUSIVE_MASKS_PASS\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"PASSIVE_MOCK_FAIL "<<e.what()<<"\n";return 1;}}
