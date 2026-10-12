#include "passive_supply.h"
// Diagnostic-policy negative controls. No generated DUT state is used here.
struct Probe {
    bool av=false,af=false;uint64_t ap=0x80400000ULL;
    std::array<unsigned,2> phases{},sources{1,0},dirs{0,256};
    std::array<uint64_t,2> addresses{0x80404000ULL,0x80408000ULL};
    std::array<bool,512> committed{};
    static void need(bool x){PassiveSupply::require(x,"admission invalid payload accessed");}
    bool reqValid(){return false;}bool reqFire(){return false;}bool independentReqFire(){return false;}
    bool cacheFire(){return false;}bool flush(){return false;}
    uint64_t reqPa(){need(false);return 0;}uint64_t reqMeta(){need(false);return 0;}
    bool hint(){need(false);return false;}bool ordinary(){need(false);return false;}
    bool historyValid(){need(false);return false;}uint64_t historyLine(){need(false);return 0;}
    bool candidate(){return false;}bool allocate(){return false;}
    bool candidateStore(){need(false);return false;}bool allocateStore(){need(false);return false;}
    bool pending(){return false;}bool live(){return false;}bool release(){return false;}
    bool readResident(){return false;}bool readConsume(){need(false);return false;}bool posted(){return true;}
    bool aValid(){return av;}bool aFire(){need(av);return af;}
    uint64_t aPa(){need(av);return ap;}unsigned aSource(){need(av);return 0;}
    unsigned homePhase(unsigned i){need(av&&i<2);return phases[i];}
    uint64_t homePa(unsigned i){need(av&&i<2&&phases[i]);return addresses[i];}
    unsigned homeSource(unsigned i){need(av&&i<2&&phases[i]);return sources[i];}
    unsigned homeDirectory(unsigned i){need(av&&i<2&&phases[i]);return dirs[i];}
    bool owned(unsigned i){need(av&&i<512);return committed[i];}
};
int main(int argc,char**argv){try{
    const std::string mode=argc==2?argv[1]:"";PassiveSupply gate;Probe p;
    auto idle=gate.capture(p);PassiveSupply::require(!idle.aPa&&!idle.aFire&&!idle.sameLine,"idle admission fields must be unknown");
    p.av=p.af=true;p.phases[0]=1;
    if(!MEMORY_SCHEDULE_OVERLAP){p.addresses[0]+=64;p.dirs[0]=1;}
    if(mode=="same-line"){p.addresses[0]=p.ap;p.dirs[0]=0;}
    if(mode=="source")p.sources[0]=0;
    if(mode=="full"){p.phases[0]=0;p.committed[0]=p.committed[256]=true;}
    if(mode=="slot-alias"){p.phases[1]=1;p.dirs[1]=p.dirs[0];}
    if(mode=="owned-slot")p.committed[p.dirs[0]]=true;
    auto accepted=gate.capture(p);gate.count(accepted);
    PassiveSupply::require(accepted.aFire.value()&&!accepted.sameLine.value()&&!accepted.directoryFull.value(),"disjoint admission classification");
    PassiveSupply::require(accepted.sameSet.value()==bool(MEMORY_SCHEDULE_OVERLAP),"explicit set policy");
    PassiveSupply::require(mode.empty(),"requested admission negative control failed to trigger");
    gate.report(0,0);std::cout<<"MEMORY_ADMISSION_PROBE_PASS mode="<<MEMORY_SCHEDULE_OVERLAP<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<"MEMORY_ADMISSION_PROBE_FAIL "<<e.what()<<'\n';return 1;}}
