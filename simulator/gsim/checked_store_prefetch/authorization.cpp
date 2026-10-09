// Reconstructed qualification from public926 independent raw-PMP oracle.
#include "NextLineAuthorizationGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#ifndef STORE_PREFETCH
#define STORE_PREFETCH 0
#endif
using U128=unsigned __int128;
static void require(bool x,const char*m){if(!x)throw std::runtime_error(m);}
struct Test {
 SNextLineAuthorizationGsim d;
 std::array<unsigned,16> cfg{};std::array<uint64_t,16> pmp{};
 uint64_t address=0x80010000,number=0;unsigned privilege=1,size=3,mask=255;
 bool write=false,atomic=false,uncached=false,virt=false,fault=false,negative=false;
 bool pmpAllows(uint64_t start) const {
  for(unsigned i=0;i<16;++i){
   unsigned mode=(cfg[i]>>3)&3;if(!mode)continue;
   U128 lo=0,hi=0;
   if(mode==1){lo=i?U128(pmp[i-1])*4:0;hi=U128(pmp[i])*4;if(hi<=lo)continue;--hi;}
   if(mode==2){lo=U128(pmp[i])*4;hi=lo+3;}
   if(mode==3){unsigned ones=0;while(ones<54&&(pmp[i]&(1ULL<<ones)))++ones;U128 length=U128(1)<<(ones+3);lo=(U128(pmp[i])*4)&~(length-1);hi=lo+length-1;}
   // Byte enumeration independently implements first entry touching ANY byte.
   unsigned covered=0;for(unsigned b=0;b<64;++b)covered+=(U128(start)+b>=lo&&U128(start)+b<=hi);
   if(covered)return covered==64&&((privilege==3&&!(cfg[i]&128))||(cfg[i]&1));
  }
  return privilege==3;
 }
 bool expected(bool top)const {
  const U128 base=top?(U128(1)<<64)-8192:0x80010000ULL;
  const U128 limit=top?(U128(1)<<64):0x80030000ULL;
  U128 next=(U128(address)/64+1)*64;
  const bool shape=size<=3 && (address% (1ULL<<size))==0 &&
   mask==(((1U<<(1U<<size))-1U)<<(address%8));
  return !fault&&(!write||(STORE_PREFETCH&&shape))&&!atomic&&!uncached&&!virt&&U128(address)>=base&&
   U128(address)+(U128(1)<<size)<=limit&&next>=base&&next+64<=limit&&next<(U128(1)<<64)&&
   (next/4096)==U128(address)/4096&&pmpAllows(uint64_t(next));
 }
 void run(){
#define SET(i) d.set_io$$cfg##i(cfg[i]);d.set_io$$pmpAddress##i(pmp[i]);
  SET(0) SET(1) SET(2) SET(3) SET(4) SET(5) SET(6) SET(7)
  SET(8) SET(9) SET(10) SET(11) SET(12) SET(13) SET(14) SET(15)
#undef SET
  d.set_io$$request$$address(address);d.set_io$$request$$size(size);d.set_io$$request$$write(write);
  d.set_io$$request$$atomic(atomic);d.set_io$$request$$atomicOp(0);d.set_io$$request$$data(0);d.set_io$$request$$mask(mask);
  d.set_io$$request$$uncached(uncached);d.set_io$$request$$virtualized(virt);
  d.set_io$$request$$prefetchNextAllowed(1); // hostile upstream hint must confer no authority
  d.set_io$$privilege(privilege);d.set_io$$fault(fault);d.set_reset(0);d.step();
  bool observed=d.get_io$$allowed();if(negative&&!expected(false))observed=true;
  require(observed==expected(false),"independent whole-line permission oracle mismatch");
  require(bool(d.get_io$$topAllowed())==expected(true),"independent 65-bit aperture oracle mismatch");++number;
 }
};
int main(int argc,char**argv){try{
 Test t;t.negative=argc>1&&std::string(argv[1])=="--inject-permission";
 for(unsigned layout=0;layout<7;++layout){
  t.cfg.fill(0);t.pmp.fill(0);
  if(layout==1){t.cfg[0]=0x1f;t.pmp[0]=(1ULL<<54)-1;}
  if(layout==2){t.cfg[0]=0x18;t.pmp[0]=(1ULL<<54)-1;}
  if(layout==3){t.cfg[0]=0x98;t.pmp[0]=(1ULL<<54)-1;}
  if(layout==4){t.cfg[0]=0x10;t.pmp[0]=(0x80010080ULL+28)/4;t.cfg[1]=0x1f;t.pmp[1]=(1ULL<<54)-1;}
  if(layout==5){t.cfg[0]=0x09;t.pmp[0]=(0x80010080ULL+32)/4;}
  if(layout==6){t.cfg[0]=0x19;t.pmp[0]=(0x80010080ULL/4)|3;}
  for(bool write:{false,true})for(unsigned priv:{0U,1U,3U}){t.write=write;t.privilege=priv;
   for(unsigned off=0;off<4352;off+=8){t.address=0x80010000ULL+off;t.run();}
   for(uint64_t a:{0x8000ffc0ULL,0x8002ffc0ULL,0xffffffffffffef80ULL,0xffffffffffffff80ULL,0xffffffffffffffc0ULL,0xfffffffffffffff8ULL}){t.address=a;t.run();}
  }
 }
 t.cfg.fill(0);t.pmp.fill(0);t.cfg[0]=0x1f;t.pmp[0]=(1ULL<<54)-1;t.address=0x80010040;t.privilege=3;
 for(unsigned mode=0;mode<6;++mode){t.write=mode==0;t.atomic=mode==1;t.uncached=mode==2;t.virt=mode==3;t.fault=mode==4;t.run();}
 t.cfg.fill(0);t.pmp.fill(0);t.cfg[0]=0x1f;t.pmp[0]=(1ULL<<54)-1;t.privilege=1;
 t.atomic=t.uncached=t.virt=t.fault=false;t.write=true;
 for(unsigned size=0;size<4;++size)for(unsigned offset=0;offset<64;++offset)for(unsigned bad=0;bad<2;++bad){
  t.size=size;t.address=0x80010040+offset;t.mask=(((1U<<(1U<<size))-1U)<<(offset%8))&255;
  if(bad)t.mask^=1;t.run();
 }
 std::cout<<"NEXT_LINE_AUTH_PASS cases="<<t.number<<"\n";return 0;
 }catch(const std::exception&e){std::cerr<<"NEXT_LINE_AUTH_FAIL "<<e.what()<<"\n";return 1;}}
