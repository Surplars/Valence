#include "window_observer.hpp"
#include <sstream>
#include <iostream>
using namespace robwindow;
int main(){
 const auto*p=std::getenv("ROB_WINDOW_TRACE");need(p&&*p,"test trace path required");
 Sample s;s.occupancy=2;s.freePhysical=1;s.rename.known=true;s.rename.dispatchReady=true;s.rename.offered={true,true};s.rename.writesRd={true,true};s.rename.fresh={true,true};s.rename.registerEnough={true,false};s.rename.accepted={true,false};
 unissued::Sample u;u.robCount=2;canonical_overlap::Sample c;Observer o;o.sample(s,u,c,1,true);o.sample(s,u,c,2,false);std::ostringstream out;o.finish(out);need(out.str().find("\"stalled_with_prf_shortage\":1")!=std::string::npos&&out.str().find("\"stalled_with_prf_empty\":0")!=std::string::npos,"partial rename PRF shortage lost");
 unsigned rejected=0;for(unsigned mutation=0;mutation<3;++mutation){auto bad=s;if(mutation==0)bad.rename.accepted[1]=true;if(mutation==1)bad.rename.registerEnough[1]=true;if(mutation==2)bad.rename.writesRd[1]=false;try{Observer x;x.sample(bad,u,c,1,true);}catch(const std::runtime_error&){++rejected;}}
 need(rejected==3,"rename pressure negative escaped");std::cout<<"PASS_RENAME_PRESSURE_HOST_ONLY free1_two_fresh_partial=1 prf_shortage=1 prf_empty=0 wrong_capacity_rejected=3 DUT_executed=0\n";
}
