#include "StorePrefetchHistoryGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
struct Step {uint64_t line;bool accepted,permission,available,clear,expected;};
int main(int argc,char**argv){try{
 const bool negative=argc==2&&std::string(argv[1])=="--inject-candidate";
 if(argc>2||(argc==2&&!negative))throw std::runtime_error("unknown history option");
 const std::vector<Step> program={
  {10,1,1,1,0,0},{10,1,1,1,0,0},{11,1,1,0,0,0},{11,1,1,1,0,1},
  {11,1,0,1,0,0},{11,0,1,1,0,0},{11,1,1,1,0,1},{50,1,1,1,0,0},
  {50,1,1,1,0,0},{51,1,0,1,0,0},{51,1,1,1,0,1},{51,1,1,1,1,0},
  {52,1,1,1,0,0},{53,1,1,1,0,1},{54,0,1,1,0,0},{54,1,1,1,0,1},
  {55,1,1,0,0,0},{55,1,1,1,0,1},{0,1,1,1,0,0},{0,1,1,1,0,0},
  {1,1,1,1,1,0},{1,1,1,1,0,0},{2,1,1,1,0,1}};
 SStorePrefetchHistoryGsim d;d.set_io$$acceptedStore(0);d.set_io$$address(0);d.set_io$$currentlyAllowed(0);
 d.set_io$$candidateAvailable(0);d.set_io$$clear(0);d.set_reset(1);d.step();d.step();d.set_reset(0);
 unsigned events=0,index=0;
 for(const auto&s:program){
  d.set_io$$acceptedStore(s.accepted);d.set_io$$address(s.line*64);d.set_io$$currentlyAllowed(s.permission);
  d.set_io$$candidateAvailable(s.available);d.set_io$$clear(s.clear);d.step();
  bool observed=d.get_io$$candidate();if(negative&&index==3)observed=!observed;
  if(observed!=s.expected)throw std::runtime_error("independent authored history candidate mismatch index="+std::to_string(index));
  events+=observed;++index;
 }
 std::cout<<"CHECKED_STORE_HISTORY_PASS cycles="<<index<<" candidates="<<events<<"\n";
}catch(const std::exception&e){std::cerr<<"CHECKED_STORE_HISTORY_FAIL "<<e.what()<<"\n";return 1;}}
