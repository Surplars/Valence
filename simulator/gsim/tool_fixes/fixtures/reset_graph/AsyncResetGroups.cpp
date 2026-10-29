#include "AsyncResetGroups.h"
#include "gsim_model_storage.h"
#include <cstdint>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string_view>
static void check(bool ok,const char *message){if(!ok)throw std::runtime_error(message);}
int main(int argc,char **argv){
  try {
    check(argc==1 || (argc==2&&std::string_view(argv[1])=="--mutate-held-observation"),"ARGUMENTS");
    const bool mutate=argc==2;
    auto storage=std::make_unique<GsimModelStorage<SAsyncResetGroups>>();auto &d=storage->get();
    unsigned cycles=0,heldChecks=0;
    auto step=[&](){d.step();check(++cycles<256,"CYCLE_BOUND");};
    auto settle=[&](unsigned n=8){while(n--)step();};
    d.set_arst(1);d.set_brst(1);d.set_srst(1);
    d.set_aEnable(0);d.set_bEnable(0);d.set_plainEnable(0);d.set_localHold(0);d.set_data(0);
    settle();
    check(d.get_directA()==17&&d.get_directB()==34&&d.get_sharedSync()==51&&
      d.get_syncOnly()==68&&d.get_derivedA()==85&&d.get_derivedB()==102&&
      d.get_registerReset()==119&&d.get_releaseBits()==7,"INITIAL_ASSERT");
    d.set_arst(0);d.set_brst(0);d.set_srst(0);settle();
    check(d.get_releaseBits()==0,"RELEASE_CHAIN_DRAIN");
    d.set_aEnable(1);d.set_bEnable(1);d.set_plainEnable(1);d.set_data(0xa6);settle();
    check(d.get_directA()==0xa6&&d.get_directB()==0xa6&&d.get_sharedSync()==0xa6&&
      d.get_syncOnly()==0xa6&&d.get_plain()==0xa6&&d.get_derivedA()==0xa6&&
      d.get_derivedB()==0xa6&&d.get_registerReset()==0xa6,"NONZERO_PRECONDITION");
    d.set_bEnable(0);d.set_plainEnable(0);
    // Root reset assertion after settled nonzero state, not constructor zeros.
    d.set_arst(1);
    for(unsigned i=0;i<5;++i){
      d.set_data(0x80+i);step();
      auto observed=d.get_directA();
      if(mutate&&i==2){std::cerr<<"ASYNC_RESET_MUTANT_REACHED\n";observed^=1;}
      check(observed==17&&d.get_sharedSync()==51&&d.get_derivedA()==85&&d.get_derivedB()==102&&
        d.get_registerReset()==119&&d.get_releaseBits()==7,"ASSERTED_HOLD_ORACLE");
      check(d.get_directB()==0xa6&&d.get_plain()==0xa6,"UNRELATED_GROUP_RESET");++heldChecks;
    }
    // Last held write must not survive as stale NEXT after reset deassertion.
    d.set_aEnable(0);d.set_arst(0);
    for(unsigned i=0;i<8;++i){step();
      check(d.get_directA()==17&&d.get_sharedSync()==51&&d.get_derivedA()==85&&
        d.get_derivedB()==102&&d.get_registerReset()==119,"HELD_WRITE_LEAK_ON_RELEASE");}
    check(d.get_releaseBits()==0,"SECOND_RELEASE_CHAIN_DRAIN");
    d.set_aEnable(1);d.set_data(0xc3);settle();d.set_aEnable(0);settle();
    check(d.get_directA()==0xc3&&d.get_derivedA()==0xc3&&d.get_registerReset()==0xc3,"REARM_WRITES");
    // Ordinary inputs stay stable across assert/hold/release: no data setter
    // may accidentally wake a reset-only cached super-node.
    d.set_arst(1);
    for(unsigned i=0;i<5;++i){step();check(d.get_directA()==17&&d.get_derivedA()==85&&
      d.get_derivedB()==102&&d.get_registerReset()==119,"STABLE_INPUT_REASSERT");++heldChecks;}
    d.set_arst(0);settle();
    d.set_brst(1);
    for(unsigned i=0;i<5;++i){step();check(d.get_directB()==34&&d.get_directA()==17,
      "INDEPENDENT_ASYNC_GROUP");++heldChecks;}
    d.set_brst(0);settle();check(d.get_directB()==34,"INDEPENDENT_RELEASE");
    // A register-derived reset can assert without either top-level async reset.
    d.set_aEnable(1);d.set_data(0xe7);settle();d.set_localHold(1);settle();
    for(unsigned i=0;i<5;++i){d.set_data(0x40+i);step();
      check(d.get_registerReset()==119,"REGISTER_DERIVED_HOLD");++heldChecks;}
    d.set_aEnable(0);d.set_localHold(0);settle();
    check(d.get_registerReset()==119,"REGISTER_DERIVED_HELD_WRITE_LEAK");
    d.set_srst(1);settle();check(d.get_syncOnly()==68&&d.get_plain()==0xa6,"SYNC_AND_UNRESET_BASELINE");
    d.set_srst(0);settle();check(d.get_syncOnly()==68&&d.get_plain()==0xa6,"SYNC_RELEASE_BASELINE");
    std::cout<<"ASYNC_RESET_GROUPS_PASS held_checks="<<heldChecks<<" cycles="<<cycles<<"\n";
  }catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}
}
