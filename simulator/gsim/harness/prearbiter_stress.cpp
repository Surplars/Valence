#include "PrearbiterBoundaryGsim.h"
#include <array>
#include <deque>
#include <set>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string_view>

#ifndef PREARBITER_BOUNDARY
#define PREARBITER_BOUNDARY 0
#endif

#ifndef LINE_DISPATCH_FLOW
#define LINE_DISPATCH_FLOW 0
#endif

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint64_t lineWord(uint64_t address, unsigned beat) {
    return 0x243f6a8885a308d3ULL ^ (address * 0x100000001b3ULL) ^
           (uint64_t(beat + 1) * 0x0102040810204081ULL);
}

static void drive(SPrearbiterBoundaryGsim &dut, bool request, uint64_t address, unsigned tag,
                  bool aReady, bool responseReady, bool dValid = false, unsigned source = 0,
                  bool denied = false) {
    dut.set_io$$contender$$valid(0);
    dut.set_io$$contenderReply$$ready(1);
    dut.set_io$$request$$valid(request);
    dut.set_io$$request$$bits$$address(address);
    dut.set_io$$request$$bits$$tag(tag);
    dut.set_io$$word0(lineWord(address, 0));
    dut.set_io$$word1(lineWord(address, 1));
    dut.set_io$$word2(lineWord(address, 2));
    dut.set_io$$word3(lineWord(address, 3));
    dut.set_io$$word4(lineWord(address, 4));
    dut.set_io$$word5(lineWord(address, 5));
    dut.set_io$$word6(lineWord(address, 6));
    dut.set_io$$word7(lineWord(address, 7));
    dut.set_io$$response$$ready(responseReady);
    dut.set_io$$tl$$a$$ready(aReady);
    dut.set_io$$tl$$d$$valid(dValid);
    dut.set_io$$tl$$d$$bits$$opcode(0); // AccessAck
    dut.set_io$$tl$$d$$bits$$param(0);
    dut.set_io$$tl$$d$$bits$$size(6);
    dut.set_io$$tl$$d$$bits$$source(source);
    dut.set_io$$tl$$d$$bits$$sink(0);
    dut.set_io$$tl$$d$$bits$$denied(denied);
    dut.set_io$$tl$$d$$bits$$data(0);
    dut.set_io$$tl$$d$$bits$$corrupt(0);
    dut.set_io$$tl$$b$$valid(0);
    dut.set_io$$tl$$c$$ready(1);
    dut.set_io$$tl$$e$$ready(1);
}


int main() { try {
 SPrearbiterBoundaryGsim dut;
 uint32_t rng=0x31415926;
 auto random=[&]() { rng^=rng<<13; rng^=rng>>17; rng^=rng<<5; return rng; };
 const uint64_t base=0x80010000ULL;
 unsigned totalCycles=0;
 for(unsigned epoch=0;epoch<7;++epoch) {
  drive(dut,false,0,0,false,false); dut.set_reset(1);dut.step();dut.step();dut.set_reset(0);
  unsigned requests=0,beats=0,scalarSent=0,scalarDone=0,responses=0,stalls=0;
  bool scalarLive=false; std::deque<unsigned> acks; std::set<unsigned> responseTags;
  std::array<unsigned,4> sources{}; std::set<unsigned> live;
  bool held=false; uint64_t heldAddress=0,heldData=0; unsigned heldSource=0,heldOpcode=0;
  for(unsigned cycle=0;cycle<2000;++cycle) {
   // Epoch 0 fills the A boundary then reset intentionally cancels all state.
   bool ready=epoch==0 ? false : epoch==1 ? true : (random()%5 !=0 && cycle%31<24);
   bool rr=epoch==1 || random()%4!=0;
   bool dv=!acks.empty(); unsigned ds=dv?acks.front():0;
   drive(dut,requests<4,base+requests*64,0x30+requests,ready,rr,dv,ds,ds>=8 && (ds&3)==2);
   bool contender=scalarSent<8 && !scalarLive;
   dut.set_io$$contender$$valid(contender);
   dut.set_io$$contender$$bits$$opcode(4);dut.set_io$$contender$$bits$$param(0);
   dut.set_io$$contender$$bits$$size(3);dut.set_io$$contender$$bits$$source(0);
   dut.set_io$$contender$$bits$$address(0x90000000ULL+8*scalarSent);
   dut.set_io$$contender$$bits$$mask(255);dut.set_io$$contender$$bits$$data(0);
   dut.set_io$$contender$$bits$$corrupt(0);dut.set_io$$contenderReply$$ready(rr);
   if(dv && ds<8) dut.set_io$$tl$$d$$bits$$opcode(1);
   dut.set_io$$tl$$d$$bits$$size(ds<8?3:6);
   dut.step(); ++totalCycles;
   if(requests<4 && dut.get_io$$request$$ready()) ++requests;
   if(contender && dut.get_io$$contender$$ready()) {scalarLive=true; ++scalarSent;}
   if(dv && dut.get_io$$tl$$d$$ready()) {acks.pop_front(); if(ds<8) {scalarLive=false;++scalarDone;} else live.erase(ds);}
   if(dut.get_io$$response$$valid() && rr) {
    unsigned tag=dut.get_io$$response$$bits$$tag();
    check(tag>=0x30 && tag<0x34 && responseTags.insert(tag).second,"duplicate or foreign completion tag");
    check(bool(dut.get_io$$response$$bits$$error())==((sources[tag-0x30]&3)==2),"denied response ownership mismatch");
    ++responses;
   }
   if(dut.get_io$$tl$$a$$valid()) {
    auto a=dut.get_io$$tl$$a$$bits$$address(), data=dut.get_io$$tl$$a$$bits$$data();
    unsigned source=dut.get_io$$tl$$a$$bits$$source(),opcode=dut.get_io$$tl$$a$$bits$$opcode();
    if(held) check(a==heldAddress && data==heldData && source==heldSource && opcode==heldOpcode,"stalled A payload changed");
    if(source>=8) {
     unsigned index=beats/8,beat=beats%8;
     check(index<4 && a==base+64*index && data==lineWord(a,beat) && opcode==0 &&
       dut.get_io$$tl$$a$$bits$$size()==6 && dut.get_io$$tl$$a$$bits$$mask()==255,"writer burst data/order metadata mismatch");
     if(beat==0 && ready) {check(live.insert(source).second,"writer source reused before D");sources[index]=source;}
     if(beat) check(source==sources[index],"source changed inside burst");
     if(ready) {++beats; if(beat==7) acks.push_back(source);}
    } else {
     check(beats%8==0,"scalar interleaved into writer burst");
     check(source==0 && opcode==4 && a==0x90000000ULL+8*scalarDone,"scalar request metadata mismatch");
     if(ready) acks.push_back(source);
    }
    held=!ready; heldAddress=a;heldData=data;heldSource=source;heldOpcode=opcode;
    if(held) ++stalls;
   } else {check(!held,"stalled A valid withdrawn");}
   if(epoch==0 && cycle==15) break;
   if(epoch==5 && beats>=10) break; // Cancel an active, partly accepted burst, then restart cleanly.
   if(epoch && requests==4 && beats==32 && responses==4 && scalarDone==8) {
    check(live.empty() && acks.empty(),"ownership not released");
    std::cout<<"PREARBITER_STRESS epoch="<<epoch<<" cycles="<<cycle+1<<" writer_beats="<<beats<<" scalar="<<scalarDone<<" stalls="<<stalls<<"\n";
    break;
   }
   check(cycle<1999,"stress failed to drain");
  }
 }
 std::cout<<"PREARBITER_STRESS_PASS resetCancel randomStalls burstOwner denied sourceReuse cycles="<<totalCycles<<"\n";
 return 0;
 } catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
