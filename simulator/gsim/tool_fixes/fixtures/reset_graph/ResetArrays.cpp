#include "ResetArrays.h"
#include "gsim_model_storage.h"
#include <array>
#include <iostream>
#include <memory>
#include <stdexcept>
static void check(bool v,const char*m){if(!v)throw std::runtime_error(m);}
int main(){try{
 auto storage=std::make_unique<GsimModelStorage<SResetArrays>>();auto&d=storage->get();
 unsigned cycles=0,checks=0;auto step=[&](){d.step();check(++cycles<256,"ARRAY_CYCLE_BOUND");};
 auto settle=[&](){for(unsigned i=0;i<4;++i)step();};
 const std::array<unsigned,3> reset{17,34,51};std::array<unsigned,3> expected=reset;
 auto audit=[&](){d.set_enable(0);for(unsigned i=0;i<3;++i){d.set_index(i);settle();
   check(d.get_value()==expected[i],"ARRAY_ELEMENT_ORACLE");++checks;}};
 d.set_reset(1);d.set_enable(0);d.set_index(0);d.set_data(0);settle();audit();
 d.set_reset(0);
 for(unsigned i=0;i<3;++i){d.set_enable(1);d.set_index(i);d.set_data(0xa0+i);settle();expected[i]=0xa0+i;}
 audit();d.set_reset(1);d.set_enable(1);
 for(unsigned i=0;i<9;++i){d.set_index(i%3);d.set_data(0xe0+i);step();
   check(d.get_value()==reset[i%3],"ARRAY_HELD_WRITE_RESET_PRIORITY");++checks;}
 d.set_enable(0);d.set_reset(0);expected=reset;settle();audit();
 d.set_index(1);d.set_enable(1);d.set_data(0x7b);settle();expected[1]=0x7b;audit();
 d.set_reset(1);expected=reset;settle();audit();
 std::cout<<"RESET_ARRAYS_PASS checks="<<checks<<" cycles="<<cycles<<"\n";
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
