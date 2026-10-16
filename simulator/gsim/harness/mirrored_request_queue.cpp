#include "MirroredRequestQueueGsim.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
#ifndef QUEUE_DEPTH
#define QUEUE_DEPTH 4
#endif
int main(int argc,char**argv){
 SMirroredRequestQueueGsim d; std::deque<uint64_t> q; uint64_t rng=0x573983ab710fULL, serial=1;
 bool corrupt=argc>1&&std::string(argv[1])=="--corrupt-sidecar";
 auto step=[&](bool push,bool pop,bool reset){
  d.set_reset(reset); d.set_io$$push(push && !reset); d.set_io$$pop(pop && !reset);d.set_io$$seed(serial);d.set_io$$corrupt(corrupt);
  d.step();
  if(!reset){
   if(bool(d.get_io$$ready())!=(q.size()<QUEUE_DEPTH)||bool(d.get_io$$valid())!=!q.empty()||d.get_io$$count()!=q.size())throw std::runtime_error("independent queue occupancy mismatch serial="+std::to_string(serial)+" expected="+std::to_string(q.size())+" ready="+std::to_string(d.get_io$$ready())+" valid="+std::to_string(d.get_io$$valid())+" count="+std::to_string(d.get_io$$count()));
   if(!q.empty()&&d.get_io$$data()!=q.front())throw std::runtime_error("independent queue owner mismatch");
   bool accept=push&&q.size()<QUEUE_DEPTH;bool retire=pop&&!q.empty();
   if(retire)q.pop_front();if(accept)q.push_back(serial);
  }else q.clear();
  ++serial;
 };
 step(false,false,true); step(false,false,true);
 for(int k=0;k<QUEUE_DEPTH;k++)step(true,false,false);
 for(int k=0;k<5;k++)step(true,false,false); // held full owner
 step(true,true,false); // full pop must NOT borrow enqueue credit
 for(int k=0;k<QUEUE_DEPTH*4;k++)step(true,true,false);
 for(int k=0;k<QUEUE_DEPTH+1;k++)step(false,true,false);
 for(int k=0;k<20000;k++){rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;step(rng&1,(rng>>1)&1,k%997==0);}
 for(int k=0;k<QUEUE_DEPTH+1;k++)step(false,true,false);
 if(corrupt)throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
 std::cout<<"MIRRORED_REQUEST_QUEUE_PASS depth="<<QUEUE_DEPTH<<" random=20000"<<std::endl;
}
