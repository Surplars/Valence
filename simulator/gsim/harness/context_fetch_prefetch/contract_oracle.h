#pragma once
#include <array>
#include <cstdint>
#include <deque>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
namespace independent {
inline void require(bool ok,const std::string& why){if(!ok)throw std::runtime_error(why);}
constexpr uint64_t ram=0x80010000ULL,ram_end=ram+8192;
inline uint8_t byte(uint64_t a){const uint64_t x=a^(a>>11)^(a>>23)^0x91a7c653ULL;return uint8_t(x*73+(x>>7)*19+0x35);}
inline uint64_t bytes(uint64_t a,unsigned n){require(n<=8,"oracle byte width");uint64_t v=0;for(unsigned i=0;i<n;++i)v|=uint64_t(byte(a+i))<<(8*i);return v;}
struct Entry{unsigned cfg=0;uint64_t addr=0;};
using Pmp=std::array<Entry,16>;
struct Region{uint64_t low=0,high=0;bool active=false;};
inline Region region(const Pmp&p,unsigned i){auto e=p[i];switch((e.cfg>>3)&3){case 0:return {};case 1:{auto lo=i?p[i-1].addr*4:0,hi=e.addr*4;return {lo,hi,hi>lo};}case 2:return {e.addr*4,e.addr*4+4,true};default:{unsigned ones=0;while(ones<54&&((e.addr>>ones)&1))++ones;uint64_t n=1ULL<<(ones+3),lo=(e.addr*4)&~(n-1);return {lo,lo+n,true};}}}
// Byte-by-byte first-overlap PMP oracle. No DUT decoded range or eligible bit.
inline bool execute(const Pmp&p,uint64_t a,unsigned n,unsigned priv){if(n==0||a>UINT64_MAX-(n-1))return false;for(unsigned i=0;i<16;++i){auto r=region(p,i);unsigned hit=0;for(unsigned b=0;b<n;++b)hit+=r.active&&a+b>=r.low&&a+b<r.high;if(!hit)continue;return hit==n&&((priv==3&&!(p[i].cfg&128))||(p[i].cfg&4));}return priv==3;}
struct Owner{uint64_t pc=0,sequence=0;unsigned mask=3,privilege=3;bool identity=true;uint64_t ordinal=0;};
struct Payload{uint64_t address=0,data=0;unsigned opcode=4,param=0,size=6,source=0,mask=255;bool corrupt=false;bool operator==(const Payload&)const=default;};
// Authorization only. Host additionally tracks issue reservation, cancellation before issue,
// exact accepted source and final engine completion (last D alone is not completion).
struct Seed{Owner owner;uint64_t line;bool stale=false;};
struct Transfer{Payload a;unsigned beats=0;bool speculative=false;uint64_t ordinal=0;};
class Ledger{
 public:
 std::deque<Owner> demands;
 std::optional<Seed> credit;
 std::map<unsigned,Transfer> inflight;
 std::optional<Payload> held;
 uint64_t accepted=0,completed=0,spec_gets=0,demand_gets=0,dbeats=0;
 void demand(Owner o){o.ordinal=accepted++;demands.push_back(o);}
 // Called from host stimulus acceptance, not from DUT perf-prefetch outputs.
 bool authorizeSeed(const Owner&o,const Pmp&p,uint64_t cutoff,bool age,bool kill){
  const uint64_t line=o.pc&~63ULL;if(credit||kill||!age||!o.identity||o.sequence<cutoff||o.mask!=3||(o.pc&7)||line>UINT64_MAX-127)return false;
  const auto next=line+64;if((line>>12)!=(next>>12)||line<ram||next+64>ram_end||!execute(p,line,64,o.privilege)||!execute(p,next,64,o.privilege))return false;
  credit=Seed{o,next,false};return true;
 }
 void cancel(){if(credit)credit->stale=true;}
 void offer(bool valid,bool ready,const Payload&a){if(held)require(valid&&a==*held,"held TL A payload/source changed");held=valid&&!ready?std::optional<Payload>(a):std::nullopt;}
 // Directed scripts explicitly choose expected demand vs speculative transport;
 // classification never relies on DUT internal tag/perf/eligible outputs.
 void accept(const Payload&a,bool spec,uint64_t expectedAddress,unsigned expectedSize,uint64_t ordinal){
  require(a.opcode==4&&!a.param&&!a.corrupt,"unexpected I side effect/opcode");require(a.address==expectedAddress&&a.size==expectedSize,"I transport address/size mixed owner");
  require(a.size==2||a.size==3||a.size==6,"unsupported Get size");require(!(a.address&((1ULL<<a.size)-1)),"unaligned I Get");require(a.mask==(a.size==2?(15U<<(a.address&7)):255U),"I mask mismatch");
  require(!inflight.count(a.source),"I source reused before final D");
  if(spec){require(credit.has_value()&&credit->line==a.address,"I spec lacks independently authorized seed");require(a.size==6,"spec is not complete line");++spec_gets;}else ++demand_gets;
  inflight.emplace(a.source,Transfer{a,0,spec,ordinal});
 }
 void beat(unsigned source){auto it=inflight.find(source);require(it!=inflight.end(),"D has no accepted A owner");auto&t=it->second;++dbeats;if(++t.beats==(t.a.size==6?8:1)){inflight.erase(it);}}
 void response(uint64_t data,unsigned errors,unsigned pages,unsigned expectedErrors=0,unsigned expectedPages=0){require(errors==expectedErrors&&pages==expectedPages,"demand precise fault mismatch");require(!demands.empty(),"duplicate/unowned demand response");auto o=demands.front();for(unsigned i=0;i<2;++i)if((o.mask>>i)&1)if(!((errors|pages)>>i&1))require(uint32_t(data>>(32*i))==uint32_t(bytes(o.pc+4*i,4)),"demand byte oracle mismatch");demands.pop_front();++completed;}
 void drained()const{require(demands.empty()&&inflight.empty()&&!held,"unfinished demand/TL owner at drain");require(accepted==completed,"demand conservation");}
};
}
