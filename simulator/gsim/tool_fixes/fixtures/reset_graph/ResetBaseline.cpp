#include "ResetBaseline.h"
#include "gsim_model_storage.h"
#include <iostream>
#include <memory>
#include <stdexcept>
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
int main(){try{
  auto storage=std::make_unique<GsimModelStorage<SResetBaseline>>();auto &d=storage->get();
  unsigned cycles=0;auto settle=[&](){for(unsigned i=0;i<8;++i){d.step();++cycles;}};
  d.set_reset(1);d.set_enable(0);d.set_data(0);settle();
  check(d.get_synchronous()==90,"SYNC_INITIAL_RESET");
  d.set_reset(0);d.set_enable(1);d.set_data(0xa7);settle();
  check(d.get_synchronous()==0xa7&&d.get_unreset()==0xa7,"BASELINE_NONZERO");
  d.set_reset(1);d.set_data(0xc4);settle();
  check(d.get_synchronous()==90&&d.get_unreset()==0xc4,"SYNC_HELD_WRITE");
  d.set_enable(0);d.set_reset(0);settle();
  check(d.get_synchronous()==90&&d.get_unreset()==0xc4,"SYNC_RELEASE_STALE_NEXT");
  d.set_reset(1);settle();d.set_reset(0);settle();
  check(d.get_synchronous()==90&&d.get_unreset()==0xc4,"SYNC_REASSERT_STABLE_INPUTS");
  std::cout<<"RESET_BASELINE_PASS cycles="<<cycles<<"\n";
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
