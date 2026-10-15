#include "ProofControlCapacityGsim.h"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>
static void check(bool b,const char*s){if(!b)throw std::runtime_error(s);}
int main()try{
 SProofControlCapacityGsim d;std::memset(&d,0,sizeof d);d.LOG_START=1;d.activateAll();
 std::vector<unsigned> handles;
 auto tick=[&](){d.step();if(d.get_io$$memory$$request$$valid() /* request.ready is driven constantly high below */)
  handles.push_back(d.get_io$$memory$$request$$bits$$returnHandle());};
 d.set_io$$memory$$request$$ready(1);d.set_io$$completeReady(0);d.set_reset(1);tick();tick();d.set_reset(0);tick();tick();
 for(unsigned i=0;i<4;++i){
  d.set_io$$start$$valid(1);d.set_io$$start$$bits$$token$$index(i);d.set_io$$start$$bits$$token$$tag(i+1);
  d.set_io$$start$$bits$$address(0x80200000+64*i);d.set_io$$start$$bits$$physicalAddress(0x80200000+64*i);
  d.set_io$$start$$bits$$size(3);d.set_io$$start$$bits$$virtualized(1);d.set_io$$start$$bits$$precheckedLoad(1);
  tick();check(d.get_io$$start$$ready(),"real parallel LSU rejected initial empty-slot load");
 }
 d.set_io$$start$$valid(0);tick();for(unsigned n=0;n<15&&handles.size()<4;++n)tick();
 check(handles.size()==4 && d.get_io$$live()==15,"capacity fixture did not fill four actual LSU owners");
 d.set_io$$memory$$response$$valid(1);d.set_io$$memory$$response$$bits$$returnHandle(handles[0]);
 d.set_io$$memory$$response$$bits$$data(0x123456789abcdefULL);tick();
 check(d.get_io$$memory$$response$$ready(),"actual selected response was not accepted");d.set_io$$memory$$response$$valid(0);
 for(unsigned n=0;n<10&&!d.get_io$$completeValid();++n)tick();
 check(d.get_io$$completeValid()&&d.get_io$$capacity()&&!d.get_io$$start$$ready(),
   "generic completion-backpressure capacity-without-capture counterexample missing");
 const unsigned selected=d.get_io$$slot();
 d.set_io$$completeReady(1);d.set_io$$start$$valid(1);d.set_io$$start$$bits$$token$$index(4);d.set_io$$start$$bits$$token$$tag(5);
 tick();check(d.get_io$$start$$ready() && d.get_io$$slot()==selected && d.get_io$$actualSlot()==selected,
   "always-ready completing-slot replacement lost exact selected slot");
 std::cout<<"C1_CAPACITY_COUNTEREXAMPLE_AND_REPLACEMENT_PASS slot="<<selected<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<"C1_CAPACITY_FAIL "<<e.what()<<'\n';return 1;}
