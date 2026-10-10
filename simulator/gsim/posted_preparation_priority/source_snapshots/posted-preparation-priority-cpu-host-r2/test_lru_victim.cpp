#include <cstdint>
static constexpr uint64_t ramBase=0x80200000ULL;
#define STORE_PF_LRU_VICTIM_ON 1
#include "lru_victim_observer.hpp"
#include <functional>
#include <iostream>
using namespace lru_victim;
unsigned rejected=0;
void reject(std::function<void()>f,const char*why){try{f();}catch(const std::runtime_error&e){need(std::string(e.what()).find(why)!=std::string::npos,"LRU wrong negative reason");++rejected;return;}throw std::runtime_error("LRU negative escaped");}
struct Access {bool live=false;unsigned bit=0;unsigned replacement(unsigned)const{need(live,"LRU forbidden inactive getter");return bit;}};
struct PayloadAccess {bool live=false;mutable unsigned reads=0;uint64_t data()const{need(live,"inactive subtype getter");++reads;return 42;}uint64_t corrupt()const{need(live,"inactive subtype getter");++reads;return 0;}};
int main(){try{
 for(bool c:{false,true})for(unsigned op=0;op<8;++op){PayloadAccess p;p.live=c?(op==5||op==7):(op==1||op==5);auto x=guardedPayload(p,op,c);need(p.reads==(p.live?2U:0U)&&x.data==(p.live?42U:0U),"TL subtype valid-before-payload");}
 PayloadAccess bad;reject([&]{guardedPayload(bad,7,true);},"inactive subtype getter");reject([&]{guardedPayload(bad,5,false);},"inactive subtype getter");
 admission::Sample s;Access a;need(!candidate(s,a).valid,"LRU idle guard");s.reset=true;s.cv=true;need(!candidate(s,a).valid,"LRU reset guard");
 s={};s.cv=true;s.cs=true;s.ca=0x80208080;s.pi=2;s.wayValid={true,true};s.wayDirty={true,false};s.wayTag={0x80200080ULL>>14,0x80204080ULL>>14};a.live=true;
 auto c=candidate(s,a);validate(c,true);need(c.wayPa[0]==0x80200080&&c.wayPa[1]==0x80204080&&expectedWay(c,true)==0&&expectedWay(c,false)==1,"LRU exact PA/dirty LRU fixture");
 auto old=c;old.index=258;validate(old,false);reject([&]{validate(old,true);},"victim selection");reject([&]{validate(c,false);},"victim selection");
 c.store=false;c.index=258;validate(c,true);c.store=true;c.lru=1;validate(c,true);
 c.wayValid[0]=false;c.wayDirty[0]=false;c.wayPa[0]=0;c.index=2;validate(c,true);
 auto x=c;x.wayPa[0]=64;reject([&]{validate(x,true);},"invalid way payload");x=c;x.wayPa[1]+=64;reject([&]{validate(x,true);},"full PA/set");x=c;x.index=3;reject([&]{validate(x,true);},"geometry");
 x={};x.address=64;reject([&]{validate(x,true);},"invalid candidate payload");
 std::cout<<"LRU_VICTIM_HOST_PASS negatives="<<rejected<<" inactive_getters_guarded=1 actual_dut=0\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
