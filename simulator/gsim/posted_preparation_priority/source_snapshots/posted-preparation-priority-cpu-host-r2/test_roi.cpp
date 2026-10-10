#include "roi.hpp"
#include "drain.hpp"
#include <sstream>
#include <iostream>
using namespace pfroi;
static Sample sample(uint64_t t,uint64_t pc,unsigned head,unsigned mode){Sample x;x.cycle=t;x.pc[0]=pc;x.commits=pc?1:0;x.head=head;x.satp=mode?sv39:0;x.privilege=1;return x;}
static unsigned negativeControls=0;
template<class F>static void rejects(F f){bool caught=false;try{f();}catch(const std::runtime_error&){caught=true;}require(caught,"negative escaped");++negativeControls;}
int main(){
 for(unsigned selected:{0,6,18,19,21}){
    Observer o(true,selected);uint64_t t=0;unsigned h=0,mode=selected==6||selected==21;
    auto add=[&](uint64_t pc=0,unsigned origin=0,unsigned events=0,std::array<uint64_t,7> axi={}){auto s=sample(t++,pc,h,mode);s.origin=origin;s.events=events;s.axi=axi;o.sample(s);if(pc)h=capacity::advance(h,1);};
    add();add(selected<18?readBeginPc:beginPc[selected%2],1,1,{1,8,0,1,8,0,0});add(0,4,2,{0,0,8,0,0,8,1});add(0,16,4);add(selected<18?readEndPc:endPc);
    if(selected>=18){add();add(tailPc);}add(casePc);add(donePc);add();
    std::ostringstream out;o.finish(out);auto& r=o.regions[selected];require(r.timed.cycles==3&&r.tail.cycles==(selected>=18?2:0),"half-open semantic ROI accounting");require(r.timed.axi==std::array<uint64_t,7>{1,8,8,1,8,8,1},"per-ROI AXI accounting");
    if(selected<18)require(r.tailOffer==r.endOffer&&r.tailAccepted==r.endAccepted,"READ fabricated tail");
 }
 rejects([]{Observer x(false,21);auto s=sample(0,0,0,1);s.origin=2;s.events=1;x.accept(s,1,0);});
 rejects([]{Observer x(true,21);x.accept(sample(0,endPc,0,1),1,1);});
 rejects([]{Observer x(true,21);x.accept(sample(0,beginPc[1],0,1),1,0);});
 rejects([]{Observer x(true,21);auto a=sample(0,beginPc[1],0,1);a.privilege=3;x.accept(a,1,1);});
 rejects([]{Observer x(true,19);x.accept(sample(0,beginPc[1],0,1),1,1);});
 rejects([]{Observer x(true,21);x.accept(sample(0,beginPc[1],0,0),1,1);});
 rejects([]{Observer x(true,6);x.accept(sample(0,readBeginPc,0,0),1,1);});
 rejects([]{Counts x;auto s=sample(0,0,0,1);s.origin=3;s.events=1;x.add(s);});
 rejects([]{Counts x;auto s=sample(0,0,0,1);s.origin=2;x.add(s);});
 rejects([]{Observer x(true,21);x.accept(sample(0,0,0,1),2,0);});
 rejects([]{Observer x(true,21);std::ostringstream out;x.finish(out);});
 for(unsigned invalid:{1,17,20,22,23,24})rejects([&]{Observer x(true,invalid);});
 rejects([]{Observer x(true,0);x.accept(sample(0,readEndPc,0,0),1,1);});
 rejects([]{Observer x(true,0);x.accept(sample(0,readBeginPc,0,0),1,0);});
 rejects([]{Observer x(true,0);auto s=sample(0,readBeginPc,0,0);s.privilege=3;x.accept(s,1,1);});
 rejects([]{Observer x(true,0);x.accept(sample(0,readBeginPc,0,1),1,1);});
 rejects([]{Observer x(true,0);x.accept(sample(0,readBeginPc,0,0),1,1);x.accept(sample(1,tailPc,1,0),2,2);x.accept(sample(2,casePc,2,0),3,3);});
 rejects([]{Observer x(true,0);x.accept(sample(0,readBeginPc,0,0),1,1);x.accept(sample(1,readBeginPc,1,0),2,2);});
 pfdrain::Snapshot d;require(d.empty(),"initial drain");for(unsigned i=0;i<d.value.size();i++){d.value[i]=1;require(!d.empty(),"drain poison escaped");d.value[i]=0;}
 std::cout<<"PASS_HOST_LOGIC_ONLY cases=0,6,18,19,21 semantic_read_no_flush=1 accepted_markers=1 negative_controls="<<negativeControls<<" drain_negative_controls=18 actual_model_execution=0\n";
}
