#define main unissued_original_test_main
#include "test_unissued.cpp"
#undef main
#include "window_observer.hpp"
#include "roi.hpp"
static unsigned rejected=0;
template<class F>void reject(F f){bool caught=false;try{f();}catch(const std::runtime_error&){caught=true;}need(caught,"capacity mutation escaped");++rejected;}
int main(){
 Guard g;g.n=capacity::robEntries;g.pendingValue=true;canonical_overlap::Sample c;auto s=readAccess(g,c);
 for(unsigned i=0;i<capacity::robEntries;++i){need(s.owners[i].token.index==i&&s.owners[i].token.tag==(1ULL<<48)+i,"full active-owner range");need(capacity::age(i,capacity::robEntries-1)==(i+1)%capacity::robEntries,"circular age");need(capacity::mask(i)==(uint64_t(1)<<i),"uint64 mask");}
 need(capacity::advance(capacity::robEntries-1,2)==1,"two-lane ROB wrap");reject([]{capacity::mask(capacity::robEntries);});reject([]{capacity::age(capacity::robEntries,0);});reject([]{capacity::age(0,capacity::robEntries);});
 for(unsigned i:{15u,16u,31u,32u,63u})if(i<capacity::robEntries){pfroi::Observer o(true,21);pfroi::Sample v;v.cycle=7;v.pc[0]=pfroi::beginPc[1];v.commits=1;v.head=i;v.satp=pfroi::sv39;v.privilege=1;o.accept(v,8,capacity::advance(i,1));}
 std::cout<<"CAPACITY_CONTROLS_PASS rob="<<capacity::robEntries<<" prf="<<capacity::physicalRegs<<" active_owner_reads="<<g.payloadReads<<" range_negative="<<rejected<<" max_generation="<<((1ULL<<48)+63)<<" DUT_executed=0\n";
}
