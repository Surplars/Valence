#include "ResetPhases.h"
#include "gsim_model_storage.h"
#include <iostream>
#include <memory>
#include <stdexcept>
static void check(bool v,const char*m){if(!v)throw std::runtime_error(m);}
int main(){try{
 auto storage=std::make_unique<GsimModelStorage<SResetPhases>>();auto&d=storage->get();
 unsigned cycles=0;auto step=[&](){d.step();++cycles;};auto settle=[&](){for(unsigned i=0;i<8;++i)step();};
 auto audit=[&](unsigned c,unsigned qs,unsigned qa,const char*why){
   check(d.get_control()==c&&d.get_synchronous()==qs&&d.get_asynchronous()==qa&&
     d.get_syncLogic()==(qs^90)&&d.get_asyncLogic()==(qa^90),why);};
 d.set_root(1);d.set_nextControl(0);d.set_enable(1);d.set_data(42);settle();
 d.set_root(0);settle();
 audit(0,42,42,"PHASE_NONZERO_PRECONDITION");
 d.set_nextControl(1);d.set_data(59);step();
 audit(0,42,42,"PHASE_BEFORE_REGISTER_PROMOTION");
 step();
 audit(1,59,101,"SYNC_OLD_ASYNC_LIVE_CONTROL");
 step();
 audit(1,202,101,"SYNC_NEXT_EDGE_RESET");
 d.set_nextControl(0);step();
 audit(1,202,101,"PHASE_BEFORE_DEASSERT_PROMOTION");
 step();
 audit(0,202,101,"SYNC_DEASSERT_OLD_SNAPSHOT");
 step();
 audit(0,59,59,"PHASE_WRITES_AFTER_RELEASE");
 std::cout<<"RESET_PHASES_PASS cycles="<<cycles<<"\n";
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
