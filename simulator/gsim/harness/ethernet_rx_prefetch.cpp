#include "EthernetRxPrefetchGsim.h"
#include "gmii_reference.h"
#include <algorithm>
#include <array>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void ck(bool v,const char*msg){if(!v)throw std::runtime_error(msg);}
static constexpr uint64_t ram=0x80200000,regs=0x10002000;
struct Frame {std::vector<uint8_t> bytes,wire; unsigned eof=0,assigned=0,writes=0,acks=0,status=0,dataBytes=0; bool dataDone=false,complete=false;};
struct Reply {unsigned due,accepted,seq; uint64_t address,data; unsigned mask;};
struct Test {
 SEthernetRxPrefetchGsim d;
 std::vector<Frame> frames;
 std::array<uint8_t,65536> mem{};
 std::array<int,4> owner{{-1,-1,-1,-1}};
 std::deque<unsigned> wireEnded,acceptedFrames;
 std::deque<Reply> replies;
 using Offer=std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool>;
 std::optional<Offer> held;
 unsigned cycles=0,start=0,end=0,source=0,pos=0,gap=0,statusPos=0;
 unsigned latency,length,count,law; static constexpr unsigned warmup=16; unsigned measuredStart=0,fixedCompleted=0,fixedBytes=0,primaryCompleted=0,primaryAccepted=0,primaryDropped=0; bool fixedCaptured=false; std::vector<unsigned> offerLat,ackLat,completionLat; bool axis,sourceOn=false;
 unsigned accepted=0,dropped=0,completed=0,writes=0,acks=0,goodBytes=0,readyStalls=0,creditStalls=0,emptyStalls=0,descriptorStalls=0;
 unsigned offerAge=0,maxOffer=0,maxResponse=0,maxCompletion=0;uint64_t sumOffer=0,sumResponse=0,sumCompletion=0;
 std::array<unsigned,5> macOcc{},dmaOcc{},outstanding{};
 std::array<unsigned,3> macPrefOcc{};
 std::string mutation;
 Test(unsigned n,unsigned total,unsigned lat,unsigned pattern,bool ax,std::string mut):latency(lat),length(n),count(total+warmup),law(pattern),axis(ax),mutation(mut){
  mem.fill(0xa5);
  for(unsigned i=0;i<count;++i){Frame f;f.bytes=ethernetBody(length,i+391);f.wire=ethernetWire(f.bytes,false);frames.push_back(f);}
  S(control$$request$$valid,0);S(control$$response$$ready,0);S(control$$request$$bits$$address,regs);
  S(control$$request$$bits$$data,0);S(control$$request$$bits$$write,0);S(control$$request$$bits$$size,3);S(control$$request$$bits$$byteEnable,255);
  S(memory$$request$$ready,0);S(memory$$response$$valid,0);S(memory$$response$$bits$$data,0);S(memory$$response$$bits$$error,0);
  S(gmiiData,0);S(gmiiValid,0);S(gmiiError,0);
  S(rxData$$valid,0);S(rxData$$bits$$data,0);S(rxData$$bits$$keep,15);S(rxData$$bits$$last,0);
  S(rxStatus$$valid,0);S(rxStatus$$bits$$data,0);S(rxStatus$$bits$$keep,15);S(rxStatus$$bits$$last,0);
  d.set_reset(1);d.step();d.step();d.set_reset(0);tick();
 }
 unsigned slot(uint64_t addr){ck(addr>=ram+256&&addr<ram+256+8192,"descriptor address outside owned slots");return unsigned(addr-ram-256)/2048;}
 bool serviceReady(){if(law==0)return true;if(law==1)return cycles%17>=7;return ((cycles*1103515245U+12345U)>>16)%4!=0;}
 bool serviceReply(){if(law<2)return true;return cycles%23>=9;}
 void tick(){
  const bool ready=serviceReady(),reply=!replies.empty()&&replies.front().due<=cycles&&serviceReply();
  S(memory$$request$$ready,ready);S(memory$$response$$valid,reply);S(memory$$response$$bits$$data,0);S(memory$$response$$bits$$error,0);
  bool wireDrive=sourceOn&&source<count&&!axis&&gap==0;
  S(gmiiValid,wireDrive);S(gmiiData,wireDrive?frames[source].wire[pos]:0);
  bool dataDrive=sourceOn&&source<count&&axis&&statusPos==0;
  bool statusDrive=sourceOn&&source<count&&axis&&statusPos>0;
  uint32_t data=0;unsigned bytes=0;
  if(dataDrive){bytes=std::min(4U,length-pos);for(unsigned b=0;b<bytes;++b)data|=uint32_t(frames[source].bytes[pos+b])<<(8*b);}
  S(rxData$$valid,dataDrive);S(rxData$$bits$$data,data);S(rxData$$bits$$keep,(1U<<bytes)-1);S(rxData$$bits$$last,dataDrive&&pos+bytes==length);
  S(rxStatus$$valid,statusDrive);S(rxStatus$$bits$$data,statusPos==1?0x50000000U:statusPos==4?64U:statusPos==6?length:0U);S(rxStatus$$bits$$last,statusPos==6);
  if(sourceOn&&source==warmup&&pos==0&&statusPos==0&&gap==0&&!measuredStart){measuredStart=cycles;macOcc.fill(0);macPrefOcc.fill(0);dmaOcc.fill(0);outstanding.fill(0);readyStalls=creditStalls=emptyStalls=descriptorStalls=0;}
  d.step();++cycles;
  // Source schedule never waits for descriptors, memory, or MMIO when using GMII.
  if(wireDrive){if(++pos==frames[source].wire.size()){frames[source].eof=cycles;wireEnded.push_back(source);pos=0;gap=12;++source;if(source==count)end=cycles+12;}}
  else if(!axis&&gap)--gap;
  if(G(accepted)||G(dropped)){
   ck(!wireEnded.empty(),"MAC verdict without independently ended frame");unsigned seq=wireEnded.front();wireEnded.pop_front();
   if(G(accepted)){acceptedFrames.push_back(seq);++accepted;if(seq>=warmup)++primaryAccepted;}else {++dropped;if(seq>=warmup)++primaryDropped;}
  }
  if(G(dataFire)){
   unsigned s=slot(G(activeAddress));
   if(owner[s]<0){
    unsigned seq;
    if(axis){seq=source;++accepted;if(seq>=warmup)++primaryAccepted;frames[seq].eof=cycles;}
    else {ck(!acceptedFrames.empty(),"DMA data before MAC validated frame");seq=acceptedFrames.front();acceptedFrames.pop_front();}
    owner[s]=int(seq);frames[seq].assigned=cycles;
   }
   auto&f=frames[owner[s]];
   unsigned take=std::min(4U,length-f.dataBytes);ck(G(dataKeep)==((1U<<take)-1),"DMA data keep ledger mismatch");
   for(unsigned b=0;b<take;++b)ck(uint8_t(G(dataWord)>>(8*b))==f.bytes[f.dataBytes+b],"MAC stream byte ledger mismatch");
   f.dataBytes+=take;ck(bool(G(dataLast))==(f.dataBytes==length),"DMA data last ledger mismatch");
   if(G(dataLast))f.dataDone=true;
  }
  if(G(statusFire)){
   unsigned s=slot(G(activeAddress));ck(owner[s]>=0,"status without frame owner");auto&f=frames[owner[s]];
   ck(f.dataDone,"status before frame boundary");++f.status;
   ck(f.status<=6&&bool(G(statusLast))==(f.status==6),"six-status boundary ledger mismatch");
   uint32_t expected=f.status==1?0x50000000U:f.status==4?64U:f.status==6?length:0U;
   ck(G(statusKeep)==15&&G(statusWord)==expected,"status content ledger mismatch");
  }
  if(axis&&dataDrive&&G(rxData$$ready)){pos+=bytes;if(pos==length){statusPos=1;frames[source].eof=cycles;}}
  else if(axis&&statusDrive&&G(rxStatus$$ready)){if(statusPos==6){++source;pos=0;statusPos=0;if(source==count)end=cycles;}else ++statusPos;}
  if(reply&&G(memory$$response$$ready)){
   auto r=replies.front();replies.pop_front();auto&f=frames[r.seq];
   for(unsigned b=0;b<8;++b)if(r.mask&(1U<<b))mem.at(r.address-ram+b)=uint8_t(r.data>>(8*b));
   ++f.acks;++acks;if(r.seq>=warmup)ackLat.push_back(cycles-r.accepted);sumResponse+=cycles-r.accepted;maxResponse=std::max(maxResponse,cycles-r.accepted);
  }
  Offer offer={uint64_t(G(memory$$request$$bits$$address)),uint64_t(G(memory$$request$$bits$$data)),unsigned(G(memory$$request$$bits$$byteEnable)),unsigned(G(memory$$request$$bits$$size)),bool(G(memory$$request$$bits$$write))};
  if(held)ck(G(memory$$request$$valid)&&offer==*held,"memory offer lost or changed under backpressure");
  if(G(memory$$request$$valid)&&!ready){held=offer;++readyStalls;++offerAge;}else held.reset();
  if(G(memory$$request$$valid)&&ready){
   auto [address,value,mask,size,write]=offer;ck(write&&size==3&&!(address&7),"unexpected non-write or unaligned request");
   unsigned s=slot(address);ck(owner[s]>=0,"write without posted generation");unsigned seq=owner[s];auto&f=frames[seq];
   ck(f.dataDone&&f.status==6&&f.eof>0,"write before its own frame and status validation");
   ck(!f.complete,"write after generation completion");
   unsigned off=unsigned(address-(ram+256+2048*s));ck(off==f.writes*8&&off<length,"duplicate missing or out-of-order write");
   unsigned remain=std::min(8U,length-off);ck(mask==((1U<<remain)-1),"tail mask oracle mismatch");
   if(mutation=="byte"&&seq==0&&off==0)value^=1;
   for(unsigned b=0;b<remain;++b)ck(uint8_t(value>>(8*b))==f.bytes[off+b],"independent frame byte oracle mismatch");
   replies.push_back({cycles+latency,cycles,seq,address,value,mask});++f.writes;++writes;
   if(seq>=warmup)offerLat.push_back(offerAge);sumOffer+=offerAge;maxOffer=std::max(maxOffer,offerAge);offerAge=0;
  }
  if(G(completion)){
   unsigned s=slot(G(activeAddress));ck(owner[s]>=0,"completion without generation owner");auto&f=frames[owner[s]];
   if(mutation=="early"&&completed==0)++f.writes;
   ck(f.acks==f.writes&&f.writes==(length+7)/8,"completion before all write acknowledgements");
   if(mutation=="duplicate"&&completed==0)f.complete=true;
   ck(!f.complete,"duplicate generation completion");ck(!G(failed),"unexpected failed completion");
   for(unsigned b=0;b<length;++b)ck(mem[256+2048*s+b]==f.bytes[b],"committed frame byte oracle mismatch");
   for(unsigned b=length;b<2048;++b)ck(mem[256+2048*s+b]==0xa5,"tail sentinel overwritten");
   f.complete=true;++completed;goodBytes+=length;if(unsigned(owner[s])>=warmup){++primaryCompleted;completionLat.push_back(cycles-f.eof);}sumCompletion+=cycles-f.eof;maxCompletion=std::max(maxCompletion,cycles-f.eof);
  }
  if(sourceOn){
   ++macOcc.at(G(macOccupied));++macPrefOcc.at(G(macPrefetchOccupied));++dmaOcc.at(G(dmaPrefetchOccupied));++outstanding.at(G(outstanding));
   creditStalls+=G(creditStall);emptyStalls+=G(storeEmpty);descriptorStalls+=G(dmaState)==0&&G(pending)==0&&(axis?dataDrive:bool(G(macOccupied)));
  }
  if(end&&cycles>=end&&!fixedCaptured){fixedCompleted=primaryCompleted;fixedBytes=primaryCompleted*length;fixedCaptured=true;}
  ck(replies.size()<=4,"memory credit limit exceeded");
 }
 uint64_t access(unsigned off,bool write=false,uint64_t value=0){
  S(control$$request$$bits$$address,regs+off);S(control$$request$$bits$$write,write);S(control$$request$$bits$$data,value);S(control$$request$$valid,1);
  unsigned deadline=cycles+100000;do{tick();ck(cycles<deadline,"MMIO request timeout");}while(!G(control$$request$$ready));
  S(control$$request$$valid,0);do{tick();ck(cycles<deadline,"MMIO reply timeout");}while(!G(control$$response$$valid));
  ck(!G(control$$response$$bits$$error),"MMIO error");auto result=G(control$$response$$bits$$data);S(control$$response$$ready,1);tick();S(control$$response$$ready,0);return result;
 }
 void post(unsigned s){access(160,true,ram+256+2048*s);access(168,true,2048);access(176,true,1);}
 void run(){
  access(184,true,1);for(unsigned s=0;s<4;++s)post(s);start=cycles;sourceOn=true;
  unsigned reclaimed=0;const unsigned deadline=cycles+count*(length+100)*100+100000;
  while(source<count||!wireEnded.empty()||completed<accepted||!acceptedFrames.empty()||!replies.empty()||reclaimed<completed){
   ck(cycles<deadline,"continuous source drain timeout");
   auto state=access(192);
   if((state>>8)&255){
    uint64_t addr=access(200),meta=access(208);unsigned s=slot(addr);
    ck(owner[s]>=0&&frames[owner[s]].complete,"MMIO completion before response ledger");
    ck(meta==length,"MMIO completed byte/error metadata mismatch");
    access(216,true,1);owner[s]=-1;++reclaimed;
    for(unsigned b=0;b<2048;++b)mem[256+2048*s+b]=0xa5;
    post(s);
   }
  }
  ck(source==count&&accepted+dropped==count&&completed==accepted,"offered accepted dropped completion conservation");
  ck(!held&&replies.empty()&&acceptedFrames.empty(),"residual write or frame ownership");
  for(unsigned s=0;s<4;++s)ck(owner[s]<0,"residual descriptor generation");
  while(cycles<end)tick();
  ck(G(macOccupied)==0&&G(macPrefetchOccupied)==0&&G(dmaPrefetchOccupied)==0&&G(outstanding)==0&&!G(macPending)&&!G(dmaPending),"final hardware storage or write obligations not drained");
  ck(G(owned)==4&&G(completed)==0&&G(pending)==3&&G(dmaState)==1,"final posted ownership state mismatch");
  for(unsigned b=0;b<256;++b)ck(mem[b]==0xa5,"leading buffer sentinel overwritten");
  for(unsigned b=256+8192;b<mem.size();++b)ck(mem[b]==0xa5,"trailing buffer sentinel overwritten");
  ck(primaryAccepted+primaryDropped==count-warmup&&primaryCompleted==primaryAccepted,"primary window frame conservation");
  const unsigned final=cycles;const double hz=axis?100000000.:125000000.;
  std::cout<<"RX_PREFETCH_PASS axis="<<axis<<" length="<<length<<" warmup="<<warmup<<" offered="<<count-warmup<<" total_offered="<<count<<" accepted="<<accepted<<" dropped="<<dropped<<" completed="<<completed
   <<" writes="<<writes<<" acks="<<acks<<" good_bytes="<<goodBytes<<" ack_latency="<<latency<<" law="<<law<<" start="<<start<<" source_end="<<end<<" end="<<final
   <<" measured_start="<<measuredStart<<" primary_accepted="<<primaryAccepted<<" primary_dropped="<<primaryDropped<<" primary_completed="<<primaryCompleted<<" fixed_completed="<<fixedCompleted<<" fixed_good_bytes="<<fixedBytes<<" fixed_fps="<<fixedCompleted*hz/(end-measuredStart)<<" fixed_mbps="<<fixedBytes*8.*hz/(end-measuredStart)/1e6<<" offered_window_cycles="<<end-measuredStart<<" total_cycles="<<final-start<<" drain_cycles="<<final-end
   <<" fps="<<primaryCompleted*hz/(final-measuredStart)<<" mbps="<<primaryCompleted*length*8.*hz/(final-measuredStart)/1e6<<" mibps="<<primaryCompleted*length*hz/(final-measuredStart)/1048576.
   <<" ready_stalls="<<readyStalls<<" credit_stalls="<<creditStalls<<" empty_stalls="<<emptyStalls<<" descriptor_stalls="<<descriptorStalls
   <<" max_offer_wait="<<maxOffer<<" max_ack_wait="<<maxResponse<<" max_completion_wait="<<maxCompletion
   <<" sum_offer_wait="<<sumOffer<<" sum_ack_wait="<<sumResponse<<" sum_completion_wait="<<sumCompletion;
  auto quantile=[](std::vector<unsigned> v,double p){if(v.empty())return 0U;std::sort(v.begin(),v.end());return v[std::min(v.size()-1,size_t(p*(v.size()-1)))];};
  for(auto pair:{std::make_pair("offer",&offerLat),std::make_pair("ack",&ackLat),std::make_pair("completion",&completionLat)})std::cout<<" "<<pair.first<<"_p50="<<quantile(*pair.second,.5)<<" "<<pair.first<<"_p95="<<quantile(*pair.second,.95)<<" "<<pair.first<<"_max="<<quantile(*pair.second,1.);
  auto hist=[](const char*name,const auto&a){std::cout<<" "<<name<<"=";for(unsigned i=0;i<a.size();++i)std::cout<<(i?",":"")<<a[i];};
  hist("mac_occupancy",macOcc);hist("mac_prefetch_occupancy",macPrefOcc);hist("dma_prefetch_occupancy",dmaOcc);hist("write_outstanding",outstanding);std::cout<<"\n";
 }
};
int main(int argc,char**argv){try{ck(argc>=6,"usage length frames latency law axis [mutation]");Test t(std::stoul(argv[1]),std::stoul(argv[2]),std::stoul(argv[3]),std::stoul(argv[4]),std::stoul(argv[5]),argc>6?argv[6]:"");t.run();return 0;}catch(const std::exception&e){std::cerr<<"RX_PREFETCH_FAIL "<<e.what()<<"\n";return 1;}}
