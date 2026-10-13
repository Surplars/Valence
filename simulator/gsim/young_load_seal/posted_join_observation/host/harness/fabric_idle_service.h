#pragma once
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
// Explicit synchronous endpoint model, six CPU cycles per consumed mailbox.
// This is not a claim of native CDC latency or physical media qualification.
struct FabricIdleService {
 static constexpr uint64_t latency=6;
 using Payload=std::array<uint64_t,5>;
 static void require(bool v,const char *message){if(!v)throw std::runtime_error(message);}
 struct Mailbox {
  bool busy=false,ready=false,held=false;uint64_t due=0,accepted=0,acked=0,heldCycles=0;
  Payload payload{},heldPayload{};
  void acknowledge(uint64_t cycle){require(busy && cycle>=due,"fabric service premature/unowned ACK");busy=false;++acked;}
  void accept(uint64_t cycle,const Payload &p){require(!busy,"fabric service duplicate mailbox owner");busy=true;due=cycle+latency;payload=p;++accepted;}
  void drive(uint64_t cycle,bool reset,bool canAck=true){if(!reset&&busy&&cycle>=due&&canAck)acknowledge(cycle);ready=!reset&&!busy;}
  void sample(uint64_t cycle,bool valid,const Payload &p){
   if(held)require(valid&&p==heldPayload,"fabric service held payload changed");
   if(valid&&ready)accept(cycle,p);
   held=valid&&!ready;if(held){heldPayload=p;++heldCycles;}
  }
 };
 std::array<Mailbox,5> boxes{};
 bool inReset=true,lastRxIdle=false,ingressReset=true,ingressReady=false;
 uint64_t ingressDue=0,cycles=0;
 template<class D> void drive(D &d,uint64_t cycle){
  d.set_service$$uart$$request$$ready(0);
  d.set_service$$uart$$response$$valid(0);
  d.set_service$$uart$$response$$bits$$data(0);
  d.set_service$$uart$$response$$bits$$error(0);
  d.set_service$$cmu$$request$$ready(0);
  d.set_service$$cmu$$response$$valid(0);
  d.set_service$$cmu$$response$$bits$$data(0);
  d.set_service$$cmu$$response$$bits$$error(0);
  d.set_service$$cmuIrq(0);
  d.set_service$$uartTx(1);
  d.set_service$$uartIrq(0);
  d.set_service$$uartQuiesce(0);
  d.set_service$$uartIsolate(0);
  d.set_service$$uartIdle(1);
  d.set_service$$jtagDmi$$request$$valid(0);
  d.set_service$$jtagDmi$$request$$bits$$op(0);
  d.set_service$$jtagDmi$$request$$bits$$address(0);
  d.set_service$$jtagDmi$$request$$bits$$data(0);
  d.set_service$$jtagDmi$$response$$ready(1);
  d.set_service$$jtagLinkUp(1);
  d.set_service$$gmac$$txFrame$$ready(0);
  d.set_service$$gmac$$rxFrame$$valid(0);
  d.set_service$$gmac$$rxFrame$$bits$$data(0);
  d.set_service$$gmac$$rxFrame$$bits$$keep(0);
  d.set_service$$gmac$$rxFrame$$bits$$last(0);
  d.set_service$$gmac$$rxFrame$$bits$$bad(0);
  d.set_service$$gmac$$txConfigIdle(1);
  d.set_service$$gmac$$rxConfigIdle(1);
  d.set_service$$gmac$$txRateIdle(1);
  d.set_service$$gmac$$rxRateIdle(1);
  d.set_service$$gmac$$rxStopIdle(1);
  d.set_service$$gmac$$txFrameSourceIdle(1);
  d.set_service$$gmac$$rxFrameDestinationIdle(1);
  d.set_service$$gmac$$txWireDrained(1);
  d.set_service$$gmac$$ingressEmpty(1);
  d.set_service$$gmac$$txStatsIdle(1);
  d.set_service$$gmac$$rxStatsIdle(1);
  d.set_service$$gmac$$rxDiagnosticsIdle(1);
  d.set_service$$gmac$$mdioIn(1);
  d.set_service$$gmac$$txMediaBusy(0);
  d.set_service$$gmac$$rxMediaBusy(0);
  d.set_service$$gmac$$ingressReady(0);
  d.set_service$$gmac$$rxClockPresent(0);
  d.set_service$$gmac$$receiverWake(0);
  d.set_service$$gmac$$txQuiesce(0);
  d.set_service$$gmac$$txIsolate(0);
  d.set_service$$gmac$$rxQuiesce(0);
  d.set_service$$gmac$$txFrames(0);
  d.set_service$$gmac$$txRejected(0);
  d.set_service$$gmac$$txBytes(0);
  d.set_service$$gmac$$rxFrames(0);
  d.set_service$$gmac$$rxDrops(0);
  d.set_service$$gmac$$rxBadFcs(0);
  d.set_service$$gmac$$rxBytes(0);
  d.set_service$$gmac$$diagnostic0(0);
  d.set_service$$gmac$$diagnostic1(0);
  d.set_service$$gmac$$diagnostic2(0);
  d.set_service$$gmac$$diagnostic3(0);
  d.set_service$$gmac$$diagnostic4(0);
  d.set_service$$gmac$$diagnostic5(0);
  d.set_service$$gmac$$diagnostic6(0);
  d.set_service$$gmac$$diagnostic7(0);
  d.set_service$$gmac$$diagnostic8(0);
  d.set_service$$gmac$$diagnostic9(0);
  d.set_service$$gmac$$diagnostic10(0);
  d.set_service$$gmac$$diagnostic11(0);
  d.set_service$$gmac$$diagnostic12(0);
  d.set_service$$gmac$$diagnostic13(0);
  for(unsigned i=0;i<5;++i)boxes[i].drive(cycle,inReset,i!=4||!boxes[i].payload[0]||lastRxIdle);
  ingressReady=!inReset&&!ingressReset&&cycle>=ingressDue;
  d.set_service$$gmac$$ingressReady(ingressReady);
  d.set_service$$gmac$$txConfig$$ready(boxes[0].ready);
  d.set_service$$gmac$$txConfigIdle(!boxes[0].busy);
  d.set_service$$gmac$$rxConfig$$ready(boxes[1].ready);
  d.set_service$$gmac$$rxConfigIdle(!boxes[1].busy);
  d.set_service$$gmac$$txRate$$ready(boxes[2].ready);
  d.set_service$$gmac$$txRateIdle(!boxes[2].busy);
  d.set_service$$gmac$$rxRate$$ready(boxes[3].ready);
  d.set_service$$gmac$$rxRateIdle(!boxes[3].busy);
  d.set_service$$gmac$$rxStop$$ready(boxes[4].ready);
  d.set_service$$gmac$$rxStopIdle(!boxes[4].busy);
 }
 template<class D> void sample(D &d,uint64_t cycle,bool checkIdle=true){
  ++cycles;
  if(d.get_service$$peripheralReset()){
   // No request is accepted while reset is asserted; drop no live owner.
   for(const auto &b:boxes)require(!b.busy,"fabric peripheral reset abandoned mailbox owner");
   inReset=true;lastRxIdle=false;ingressReset=true;ingressDue=0;return;
  }
  inReset=false;lastRxIdle=d.get_service$$gmac$$rxIdle();
  const bool nextIngressReset=d.get_service$$gmac$$ingressReset();
  if(nextIngressReset){ingressReset=true;ingressReady=false;ingressDue=0;}
  else {if(ingressReset)ingressDue=cycle+latency;ingressReset=false;}
  if(checkIdle)require(!d.get_service$$uart$$request$$valid(),"unexpected idle fabric activity: uart$$request$$valid");
  if(checkIdle)require(!d.get_service$$cmu$$request$$valid(),"unexpected idle fabric activity: cmu$$request$$valid");
  if(checkIdle)require(!d.get_service$$gmacMmioValid(),"unexpected idle fabric activity: gmacMmioValid");
  if(checkIdle)require(!d.get_service$$memoryDmaActive(),"unexpected idle fabric activity: memoryDmaActive");
  if(checkIdle)require(!d.get_service$$packetDmaActive(),"unexpected idle fabric activity: packetDmaActive");
  if(checkIdle)require(!d.get_service$$packetDmaIrq(),"unexpected idle fabric activity: packetDmaIrq");
  if(checkIdle)require(!d.get_service$$packetRequestFire(),"unexpected idle fabric activity: packetRequestFire");
  if(checkIdle)require(!d.get_service$$packetResponseFire(),"unexpected idle fabric activity: packetResponseFire");
  if(checkIdle)require(!d.get_service$$scalarDmaFire(),"unexpected idle fabric activity: scalarDmaFire");
  if(checkIdle)require(!d.get_service$$lineDmaFire(),"unexpected idle fabric activity: lineDmaFire");
  if(checkIdle)require(!d.get_service$$jtagRequestFire(),"unexpected idle fabric activity: jtagRequestFire");
  if(checkIdle)require(!d.get_service$$jtagResponseFire(),"unexpected idle fabric activity: jtagResponseFire");
  if(checkIdle)require(!d.get_service$$jtagDmi$$response$$valid(),"unexpected idle fabric activity: jtagDmi$$response$$valid");
  if(checkIdle)require(!d.get_service$$gmac$$txFrame$$valid(),"unexpected idle fabric activity: gmac$$txFrame$$valid");
  const bool v0=d.get_service$$gmac$$txConfig$$valid();Payload p0{};
  if(v0)p0={d.get_service$$gmac$$txConfig$$bits$$macAddress(),d.get_service$$gmac$$txConfig$$bits$$txEnable(),d.get_service$$gmac$$txConfig$$bits$$rxEnable(),d.get_service$$gmac$$txConfig$$bits$$promiscuous(),d.get_service$$gmac$$txConfig$$bits$$broadcastEnable()};
  boxes[0].sample(cycle,v0,p0);
  const bool v1=d.get_service$$gmac$$rxConfig$$valid();Payload p1{};
  if(v1)p1={d.get_service$$gmac$$rxConfig$$bits$$macAddress(),d.get_service$$gmac$$rxConfig$$bits$$txEnable(),d.get_service$$gmac$$rxConfig$$bits$$rxEnable(),d.get_service$$gmac$$rxConfig$$bits$$promiscuous(),d.get_service$$gmac$$rxConfig$$bits$$broadcastEnable()};
  boxes[1].sample(cycle,v1,p1);
  const bool v2=d.get_service$$gmac$$txRate$$valid();Payload p2{};
  if(v2)p2[0]=d.get_service$$gmac$$txRate$$bits();
  boxes[2].sample(cycle,v2,p2);
  const bool v3=d.get_service$$gmac$$rxRate$$valid();Payload p3{};
  if(v3)p3[0]=d.get_service$$gmac$$rxRate$$bits();
  boxes[3].sample(cycle,v3,p3);
  const bool v4=d.get_service$$gmac$$rxStop$$valid();Payload p4{};
  if(v4)p4[0]=d.get_service$$gmac$$rxStop$$bits();
  boxes[4].sample(cycle,v4,p4);
  require((v0&&boxes[0].ready)==(v1&&boxes[1].ready),"fabric config image was not accepted atomically");
  if(v0&&boxes[0].ready)require(p0==p1,"fabric TX/RX config images differ");
 }
 void finish() const {
  for(const auto &b:boxes)require(!b.busy&&b.accepted==b.acked,"fabric idle mailbox owner not drained");
  std::cout<<"FABRIC_IDLE_PASS service_latency="<<latency<<" samples="<<cycles;
  for(unsigned i=0;i<boxes.size();++i)std::cout<<" mailbox"<<i<<"_accepted="<<boxes[i].accepted<<" mailbox"<<i<<"_acked="<<boxes[i].acked<<" mailbox"<<i<<"_held_cycles="<<boxes[i].heldCycles;
  std::cout<<" unexpected_mmio_dma_jtag_frame=0\n";
 }
};
