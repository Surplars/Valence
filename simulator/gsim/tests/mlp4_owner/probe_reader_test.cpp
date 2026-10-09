#include "mock_board.h"
#define DATA_PATH_OWNERSHIP_PROBES
#include "backend_observer.h"
#include "performance_observer.h"
#include <sstream>
static void must(bool b,const char *message){if(!b)throw std::runtime_error(message);}
int main(){try{
    SBoardSocGsim d;
#ifndef MOCK_LEGACY
    d.backendSlotCount=BACKEND_OWNER_COUNT;
#endif
    d.backendSlot0Tag=0x8000000100000001ULL;d.backendSlot1Tag=0xf000000100000001ULL;
    d.backendSlotIndices=0x0e07;
    d.backendSlotState=3|(1<<2)|(2<<4)|(1<<6)|(1<<9);
#if BACKEND_OWNER_COUNT == 4
    d.backendSlot2Tag=0x8000000200000001ULL;d.backendSlot3Tag=0xf000000200000001ULL;
    d.backendSlotIndicesHi=0x0d06;
    d.backendSlotStateHi=3|(3<<2)|(1<<4)|(1<<7)|(1<<8);
    d.backendReturnSlot=3;
#endif
    auto s=BackendObserver::read(d);
    must(s.slots[0]==BackendToken{0x8000000100000001ULL,7},"lower slot0 full token");
    must(s.slots[1]==BackendToken{0xf000000100000001ULL,14},"lower slot1 full token");
    must(s.phase[0]==1&&s.phase[1]==2&&s.parallel[0]&&!s.parallel[1]&&!s.cancelled[0]&&s.cancelled[1],"legacy pair bit layout");
#if BACKEND_OWNER_COUNT == 4
    must(s.slots[2]==BackendToken{0x8000000200000001ULL,6},"upper slot2 full token");
    must(s.slots[3]==BackendToken{0xf000000200000001ULL,13},"upper slot3 full token");
    must(s.phase[2]==3&&s.phase[3]==1&&!s.parallel[2]&&s.parallel[3]&&s.cancelled[2]&&!s.cancelled[3],"upper pair bit layout");
    must(s.returnSlot==3,"upper return slot was truncated");
#endif
    must(s.liveCount()==BACKEND_OWNER_COUNT,"live owner count truncation");
#ifndef MOCK_LEGACY
    d.backendSlotCount=BACKEND_OWNER_COUNT==4?2:4;
    bool rejected=false;try{(void)BackendObserver::read(d);}catch(const std::runtime_error &e){rejected=std::string(e.what()).find("compiled owner count")!=std::string::npos;}
    must(rejected,"mismatched probe count silently passed");
    d.backendSlotCount=BACKEND_OWNER_COUNT;
#if BACKEND_OWNER_COUNT == 2
    d.backendSlotStateHi=1;
    rejected=false;try{(void)BackendObserver::read(d);}catch(const std::runtime_error &e){rejected=std::string(e.what()).find("hidden upper")!=std::string::npos;}
    must(rejected,"hidden upper owner escaped two-owner reader");
#endif
#endif
    // No hardware required: verify stable default histogram/report schema.
    BackendObserver o;o.finished=true;
    std::ostringstream output;auto *old=std::cout.rdbuf(output.rdbuf());o.report();std::cout.rdbuf(old);
    for(unsigned i=0;i<=BACKEND_OWNER_COUNT;++i)
        must(output.str().find("free_slots_"+std::to_string(i)+"=0")!=std::string::npos,"free slot histogram missing owner count");
    if(BACKEND_OWNER_COUNT==2)must(output.str().find("free_slots_3=")==std::string::npos,"legacy report schema changed");
    std::cout<<"PASS passive probe reader owner_count="<<BACKEND_OWNER_COUNT<<" lower/upper full64 tags and exact pair ABI\n";
}catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}}
