#include "EthernetHomeRxGsim.h"
#include "gmii_reference.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <functional>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
static void check(bool v, const char* message) { if (!v) throw std::runtime_error(message); }
#define DMA_RAM_BYTES (2ULL * 1024 * 1024 * 1024)
#include "dma_coherent_ddr.h"
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static constexpr uint64_t ram = 0x80200000ULL, regs = 0x10002000ULL;
static constexpr unsigned slotBase = 256, slotStride = 2048;
struct Frame {
    std::vector<uint8_t> bytes, wire;
    unsigned eof=0, assigned=0, writes=0, responses=0, successful=0, errors=0, bCount=0, lastB=0;
    unsigned status=0, dataBytes=0, completionCycle=0, descriptorSlot=0;
    uint64_t descriptorGeneration=0;
    bool dataDone=false, complete=false, failed=false;
};
struct Descriptor { unsigned slot; uint64_t generation; };
struct CompletedDescriptor { Descriptor descriptor; unsigned frame; };
struct PacketWrite {
    unsigned accepted, seq, offset, mask, responseCycle=0, bCycle=0, axiId=0;
    uint64_t address, data, axiSerial=0;
    bool aw=false, w=false, bError=false, responseError=false;
};
struct StageStats {
    unsigned occupied=0,peak=0,requests=0,responses=0,offers=0,ready=0,blocked=0,responseBlocked=0;
    std::array<unsigned,9> histogram{};
    void observe(bool valid,bool canAccept,bool request,bool responseValid,bool responseReady,bool response,bool measured){
        check(occupied+unsigned(request)>=unsigned(response),"stage response before accepted request");
        occupied+=unsigned(request);occupied-=unsigned(response);peak=std::max(peak,occupied);
        check(occupied<=8,"stage owner overflow");
        if(measured){requests+=request;responses+=response;offers+=valid;ready+=canAccept;blocked+=valid&&!canAccept;responseBlocked+=responseValid&&!responseReady;++histogram.at(occupied);}
    }
};
struct Test {
    SEthernetHomeRxGsim d;
    DmaDdr ddr;
    // Independent architectural expectations include dirty cache contents. DDR
    // backing is updated at AXI W by DmaDdr, including transactions that get SLVERR.
    std::vector<uint8_t> expected;
    std::vector<Frame> frames;
    std::vector<PacketWrite> packetWrites;
    std::deque<unsigned> responseQueue, wireEnded, acceptedFrames;
    std::map<uint64_t,unsigned> axiOwners;
    std::array<int,4> owner{{-1,-1,-1,-1}};
    std::array<bool,4> descriptorOwned{};
    std::array<uint64_t,4> descriptorGenerations{};
    std::deque<Descriptor> postedDescriptors;
    std::deque<CompletedDescriptor> completedDescriptors;
    std::optional<unsigned> activeFrame;
    uint64_t stagedPostAddress=0;
    unsigned descriptorPosts=0,descriptorPops=0;
    using Offer = std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool>;
    std::optional<Offer> held;
    unsigned cycles=0,start=0,end=0,source=0,pos=0,gap=0,length,count,warmup,latency;
    unsigned measuredStart=0,fixedCompleted=0,fixedBytes=0,primaryCompleted=0,primaryAccepted=0,primaryDropped=0;
    unsigned accepted=0,dropped=0,completed=0,errors=0,writes=0,responses=0,successfulResponses=0,goodBytes=0;
    unsigned readyStalls=0,creditStalls=0,emptyStalls=0,descriptorStalls=0,offerAge=0;
    unsigned probes=0,dirtyBeats=0,heldBCycles=0,heldOfferCycles=0,heldAfterStop=0,stopped=0;
    unsigned packetAw=0,packetB=0,packetBErrors=0,homeRequests=0,homeResponses=0,tlA=0,tlD=0;
    unsigned measuredOffers=0,measuredRequests=0,measuredResponses=0,packetPeak=0;
    std::array<unsigned,16> axiIds{};std::array<unsigned,32> tlSources{};
    std::array<StageStats,8> stages{};
    std::array<unsigned,3> bufferHistogram{};
    unsigned bufferOccupancy=0,bufferPeak=0;
    std::array<unsigned,7> localOwnerPeaks{};
    unsigned lineReads=0,lineReadResponses=0;
    std::vector<unsigned> offerLat,ackLat,completionLat;
    std::array<unsigned,5> macOcc{},dmaOcc{},outstanding{};
    std::array<unsigned,3> macPrefOcc{};
    bool sourceOn=false,fixedCaptured=false,holdB=false,expectFailure=false,collectStats=false;
    std::string mutation;
    Test(unsigned n,unsigned total,unsigned lat,unsigned warm,std::string mut=""):
        expected(1024*1024,0xa5),length(n),count(total+warm),warmup(warm),latency(lat),mutation(mut) {
        std::fill(ddr.memory.begin(),ddr.memory.end(),0xa5); std::fill(ddr.high.begin(),ddr.high.end(),0xa5);
        ddr.readDelay=lat; ddr.bDelay=lat;
        for(unsigned i=0;i<count;++i) addFrame(i);
        S(control$$request$$valid,0); S(control$$response$$ready,0);
        S(control$$request$$bits$$address,regs); S(control$$request$$bits$$data,0);
        S(control$$request$$bits$$write,0); S(control$$request$$bits$$size,3); S(control$$request$$bits$$byteEnable,255);
        S(gmiiData,0); S(gmiiValid,0); S(gmiiError,0); S(flushRequest,0); S(holdLineHome,0);
        S(cpu$$request$$bits$$returnHandle,0);S(cpu$$request$$bits$$precheckedLoad,0);S(cpu$$request$$bits$$translationEpoch,0);
        S(cpu$$request$$valid,0); S(cpu$$response$$ready,0); S(cpu$$request$$bits$$address,ram);
        S(cpu$$request$$bits$$data,0); S(cpu$$request$$bits$$write,0); S(cpu$$request$$bits$$mask,255);
        S(cpu$$request$$bits$$size,3); S(cpu$$request$$bits$$atomic,0); S(cpu$$request$$bits$$atomicOp,0);
        S(cpu$$request$$bits$$virtualized,0); S(cpu$$request$$bits$$uncached,0); S(cpu$$request$$bits$$prefetchNextAllowed,0);
        d.set_reset(1); tick(); tick(); d.set_reset(0); tick();
    }
    void addFrame(unsigned seq) {
        Frame f; f.bytes=ethernetBody(length,seq+391);
        check(length>=22,"full generation identity requires at least22 body bytes");
        for(unsigned b=0;b<8;++b)f.bytes[14+b]=uint8_t(uint64_t(seq)>>(8*b));
        f.wire=ethernetWire(f.bytes,false);
        // Replayed complete old frames retain their valid FCS, while the oracle
        // keeps the new generation. Replaying each frame after256 avoids relying
        // on one particular wire frame being admitted by a congested real home.
        if(mutation=="stale256"&&seq>=256)f.wire=frames.at(seq-256).wire;
        frames.push_back(f);
    }
    unsigned slot(uint64_t address) const {
        check(address>=ram+slotBase&&address<ram+slotBase+4*slotStride,"descriptor address outside owned slots");
        return unsigned(address-ram-slotBase)/slotStride;
    }
    static unsigned offset(unsigned s) { return slotBase+s*slotStride; }
    uint64_t word(unsigned a) const { uint64_t v=0;for(unsigned b=0;b<8;++b)v|=uint64_t(expected.at(a+b))<<(8*b);return v; }
    bool axiEmpty() const { return ddr.reads.empty()&&ddr.writes.empty()&&ddr.replies.empty()&&!ddr.heldR&&!ddr.heldB; }
    void until(const std::function<bool()>& done,const char* reason,unsigned limit=1000000) {
        unsigned deadline=cycles+limit;while(!done()){tick();check(cycles<deadline,reason);}
    }
    void tick() {
        // Hold only not-yet-offered packet B responses. Never withdraw AXI VALID.
        if(holdB)for(auto& b:ddr.replies)if(axiOwners.count(b.serial)){
            check(!ddr.heldB||*ddr.heldB!=b.serial,"packet B hold started after VALID");b.due=cycles+3;++heldBCycles;
        }
        const bool wireDrive=sourceOn&&source<count&&gap==0;
        S(gmiiValid,wireDrive);S(gmiiData,wireDrive?frames[source].wire[pos]:0);
        if(sourceOn&&source==warmup&&pos==0&&gap==0&&!measuredStart){
            measuredStart=cycles;collectStats=true;macOcc.fill(0);macPrefOcc.fill(0);dmaOcc.fill(0);outstanding.fill(0);
            readyStalls=creditStalls=emptyStalls=descriptorStalls=0;
        }
        ddr.drive(d,cycles);d.step();
        // AXI events are inspected before sample removes their independent owners.
        std::optional<unsigned> corruptAddress;
        if(G(ddrAxi$$aw$$valid)&&ddr.awReady&&G(ddrAxi$$aw$$bits$$len)==0){
            uint64_t address=ram+G(ddrAxi$$aw$$bits$$addr);unsigned index=packetWrites.size();
            for(unsigned i:responseQueue)if(!packetWrites[i].aw&&packetWrites[i].address==address){index=i;break;}
            check(index<packetWrites.size(),"AXI scalar AW without accepted packet owner");auto& r=packetWrites[index];
            r.aw=true;r.axiId=G(ddrAxi$$aw$$bits$$id);r.axiSerial=ddr.serial;
            // DmaDdr samples AR first, which can allocate the next serial.
            if(G(ddrAxi$$ar$$valid)&&ddr.arReady)++r.axiSerial;
            axiOwners.emplace(r.axiSerial,index);++packetAw;++axiIds.at(r.axiId);
        }
        if(G(ddrAxi$$w$$valid)&&ddr.wReady){
            check(!ddr.writes.empty(),"AXI W missing independent AW owner");const auto& w=ddr.writes.front();
            auto it=axiOwners.find(w.serial);if(it!=axiOwners.end()){
                auto& r=packetWrites[it->second];check(w.count==1&&w.address==r.address-ram,"packet AXI geometry changed");
                check(G(ddrAxi$$w$$bits$$strb)==r.mask&&G(ddrAxi$$w$$bits$$data)==r.data,"packet AXI data/mask owner mismatch");
                check(!r.w,"duplicate packet AXI W");r.w=true;
                if(mutation=="byte"&&r.seq==0&&r.offset==0)corruptAddress=w.address;
            }
        }
        if(ddr.bValid&&G(ddrAxi$$b$$ready)){
            auto b=DmaDdr::selected(ddr.replies,ddr.heldB);check(b!=ddr.replies.end(),"AXI B missing independent owner");
            auto it=axiOwners.find(b->serial);if(it!=axiOwners.end()){
                auto& r=packetWrites[it->second];check(r.w&&!r.bCycle&&r.axiId==b->id,"packet AXI B owner mismatch");
                r.bCycle=cycles+1;r.bError=b->error;auto& f=frames[r.seq];++f.bCount;f.lastB=cycles+1;
                ++packetB;packetBErrors+=b->error;axiOwners.erase(it);
            }
        }
        ddr.sample(d);++cycles;if(corruptAddress)ddr.byte(*corruptAddress)^=1;
        const unsigned requestBits=G(stageRequestFire),responseBits=G(stageResponseFire);
        const std::array<unsigned,7> locals{unsigned(G(arbiterOwners)),unsigned(G(debugArbiterOwners)),unsigned(G(adapterOwners)),unsigned(G(atomicOwners)),unsigned(G(systemArbiterOwners)),unsigned(G(bufferOccupied)),unsigned(G(orderedOwners))};
        // Generated top outputs sample pre-edge ownership, while the host ledger
        // below includes this edge's accepted requests/responses.
        check(locals[0]==stages[1].occupied&&locals[1]==stages[2].occupied&&locals[2]==stages[3].occupied&&locals[3]==stages[4].occupied&&locals[4]==stages[5].occupied&&locals[5]==bufferOccupancy&&locals[6]==stages[7].occupied,"local owner count disagrees with independent stage ledger");
        for(unsigned i=0;i<7;++i)localOwnerPeaks[i]=std::max(localOwnerPeaks[i],locals[i]);
        for(unsigned i=0;i<8;++i)stages[i].observe((G(stageRequestOffer)>>i)&1,(G(stageRequestReady)>>i)&1,(requestBits>>i)&1,
            (G(stageResponseOffer)>>i)&1,(G(stageResponseReady)>>i)&1,(responseBits>>i)&1,collectStats);
        const unsigned enq=(requestBits>>5)&1,deq=(requestBits>>6)&1;
        check(bufferOccupancy+enq>=deq,"request-buffer dequeue without enqueue owner");bufferOccupancy+=enq;bufferOccupancy-=deq;
        check(bufferOccupancy<=2,"request-buffer capacity exceeded");bufferPeak=std::max(bufferPeak,bufferOccupancy);
        if(collectStats)++bufferHistogram.at(bufferOccupancy);
        check(!G(copyRequestOffer)&&!G(lineRequestOffer)&&!G(active),"copy engine violated idle request VALID contract");
        check(!G(dmaResponseFire)&&!G(lineResponseFire),"idle copy engine received memory response");
        lineReads+=G(lineReadFire);lineReadResponses+=G(lineReadResponseFire);check(lineReadResponses<=lineReads,"line-read response without request");
        probes+=G(probeFire);dirtyBeats+=G(probeReplyFire)&&G(probeReplyData);
        homeRequests+=G(homeRequestFire);homeResponses+=G(homeResponseFire);
        if(G(memoryAFire)){++tlA;++tlSources.at(G(memoryASource));}tlD+=G(memoryDFire);
        // Source schedule is strictly wire time: no descriptor/MMIO/memory pacing.
        if(wireDrive){if(++pos==frames[source].wire.size()){
            frames[source].eof=cycles;wireEnded.push_back(source);pos=0;gap=12;++source;if(source==count)end=cycles+12;
        }}else if(gap)--gap;
        if(G(accepted)||G(dropped)){
            check(!wireEnded.empty(),"MAC verdict without independently ended frame");unsigned seq=wireEnded.front();wireEnded.pop_front();
            if(G(accepted)){acceptedFrames.push_back(seq);++accepted;if(seq>=warmup)++primaryAccepted;}
            else{++dropped;if(seq>=warmup)++primaryDropped;}
        }
        if(G(dataFire)){
            if(!activeFrame){
                check(!postedDescriptors.empty(),"data without independently accepted POST");
                if(mutation=="post-order"&&completed==0){check(postedDescriptors.size()>=2,"post-order witness missing");std::swap(postedDescriptors[0],postedDescriptors[1]);}
                const Descriptor desc=postedDescriptors.front();
                check(G(activeAddress)==ram+offset(desc.slot),"accepted POST order/address mismatch");
                check(descriptorOwned[desc.slot]&&descriptorGenerations[desc.slot]==desc.generation&&owner[desc.slot]<0,"descriptor generation owner mismatch");
                check(!acceptedFrames.empty(),"DMA data before MAC validated frame");unsigned seq=acceptedFrames.front();acceptedFrames.pop_front();
                postedDescriptors.pop_front();activeFrame=seq;owner[desc.slot]=int(seq);auto& frame=frames[seq];
                frame.assigned=cycles;frame.descriptorSlot=desc.slot;frame.descriptorGeneration=desc.generation;
            }
            unsigned s=frames[*activeFrame].descriptorSlot;
            check(G(activeAddress)==ram+offset(s)&&owner[s]==int(*activeFrame),"active descriptor address/owner changed");
            auto& f=frames[owner[s]];unsigned take=std::min(4U,length-f.dataBytes);
            check(G(dataKeep)==((1U<<take)-1),"DMA data keep ledger mismatch");
            for(unsigned b=0;b<take;++b){
                bool equal=uint8_t(G(dataWord)>>(8*b))==f.bytes[f.dataBytes+b];
                if(!equal&&mutation=="stale256")std::cerr<<"STALE256_WITNESS accepted_generation="<<owner[s]<<" replay_generation="<<owner[s]-256<<" byte_offset="<<f.dataBytes+b<<"\n";
                check(equal,"MAC stream byte ledger mismatch");
            }
            f.dataBytes+=take;check(bool(G(dataLast))==(f.dataBytes==length),"DMA data last ledger mismatch");if(G(dataLast))f.dataDone=true;
        }
        if(G(statusFire)){
            check(activeFrame.has_value(),"status without frame owner");auto& f=frames[*activeFrame];
            check(G(activeAddress)==ram+offset(f.descriptorSlot),"status descriptor address changed");
            check(f.dataDone,"status before frame boundary");++f.status;
            check(f.status<=6&&bool(G(statusLast))==(f.status==6),"six-status boundary ledger mismatch");
            uint32_t expectedStatus=f.status==1?0x50000000U:f.status==4?64U:f.status==6?length:0U;
            check(G(statusKeep)==15&&G(statusWord)==expectedStatus,"status content ledger mismatch");
        }
        if(G(packetResponseFire)){
            check(!responseQueue.empty(),"packet response without accepted request owner");auto& r=packetWrites[responseQueue.front()];responseQueue.pop_front();
            check(r.bCycle&&r.bCycle<=cycles,"packet response before relevant AXI B");
            check(bool(G(packetResponseError))==r.bError,"packet response/AXI B error mismatch");
            r.responseCycle=cycles;r.responseError=G(packetResponseError);auto& f=frames[r.seq];++f.responses;++responses;
            if(r.responseError)++f.errors;else{++f.successful;++successfulResponses;}
            if(r.seq>=warmup)ackLat.push_back(cycles-r.accepted);
        }
        Offer offer={uint64_t(G(packetRequestAddress)),uint64_t(G(packetRequestData)),unsigned(G(packetRequestMask)),unsigned(G(packetRequestSize)),bool(G(packetRequestWrite))};
        if(held)check(G(packetRequestOffer)&&offer==*held,"memory offer lost or changed under backpressure");
        if(G(packetRequestOffer)&&!G(packetRequestReady)){held=offer;++offerAge;++heldOfferCycles;heldAfterStop+=bool(stopped);if(collectStats)++readyStalls;}else held.reset();
        if(G(packetRequestFire)){
            auto[address,value,mask,size,write]=offer;check(write&&size==3&&!(address&7),"unexpected non-write or unaligned request");
            check(activeFrame.has_value(),"write without posted generation");unsigned seq=*activeFrame;auto& f=frames[seq];unsigned s=f.descriptorSlot;
            check(descriptorOwned[s]&&descriptorGenerations[s]==f.descriptorGeneration&&owner[s]==int(seq),"descriptor generation owner mismatch");
            check(f.dataDone&&f.status==6&&f.eof>0,"write before its own frame and status validation");check(!f.complete,"write after generation completion");
            unsigned off=unsigned(address-(ram+offset(s)));check(off==f.writes*8&&off<length,"duplicate missing or out-of-order write");
            unsigned remain=std::min(8U,length-off);check(mask==((1U<<remain)-1),"tail mask oracle mismatch");
            for(unsigned b=0;b<remain;++b){check(uint8_t(value>>(8*b))==f.bytes[off+b],"independent frame byte oracle mismatch");expected.at(offset(s)+off+b)=f.bytes[off+b];}
            PacketWrite r{};r.accepted=cycles;r.seq=seq;r.offset=off;r.address=address;r.data=value;r.mask=mask;
            responseQueue.push_back(packetWrites.size());packetWrites.push_back(r);++f.writes;++writes;
            if(seq>=warmup)offerLat.push_back(offerAge);offerAge=0;
        }
        if(G(completion)){
            check(activeFrame.has_value(),"completion without generation owner");unsigned seq=*activeFrame;auto& f=frames[seq];unsigned s=f.descriptorSlot;
            check(G(activeAddress)==ram+offset(s),"completion descriptor address mismatch");
            if(mutation=="descriptor-generation"&&completed==0)++f.descriptorGeneration;
            check(descriptorOwned[s]&&descriptorGenerations[s]==f.descriptorGeneration&&owner[s]==int(seq),"descriptor generation owner mismatch");
            if(mutation=="early"&&completed==0)++f.writes;
            check(f.responses==f.writes,"completion before all write acknowledgements");
            if(mutation=="before-b"&&completed==0)++f.writes;
            check(f.bCount==f.writes&&(!f.writes||f.lastB<=cycles),"completion before relevant AXI B");
            if(mutation=="duplicate"&&completed==0)f.complete=true;
            check(!f.complete,"duplicate generation completion");f.failed=G(failed);check(f.failed==expectFailure,"unexpected completion failure state");
            if(!f.failed)check(f.writes==(length+7)/8&&f.successful==f.writes&&!f.errors,"good completion missing successful packet responses");
            for(unsigned b=0;b<slotStride;++b)check(ddr.byte(offset(s)+b)==expected.at(offset(s)+b),"committed frame/tail byte oracle mismatch");
            f.complete=true;f.completionCycle=cycles;++completed;errors+=f.failed;
            completedDescriptors.push_back({{s,f.descriptorGeneration},seq});activeFrame.reset();
            if(!f.failed){goodBytes+=length;if(unsigned(owner[s])>=warmup){++primaryCompleted;completionLat.push_back(cycles-f.eof);}}
        }
        if(collectStats){
            measuredOffers+=G(packetRequestOffer);measuredRequests+=G(packetRequestFire);measuredResponses+=G(packetResponseFire);
            ++macOcc.at(G(macOccupied));++macPrefOcc.at(G(macPrefetchOccupied));++dmaOcc.at(G(dmaPrefetchOccupied));++outstanding.at(G(outstanding));
            creditStalls+=G(creditStall);emptyStalls+=G(storeEmpty);descriptorStalls+=G(dmaState)==0&&G(pending)==0&&G(macOccupied);
        }
        if(end&&cycles>=end&&!fixedCaptured){fixedCompleted=primaryCompleted;fixedBytes=primaryCompleted*length;fixedCaptured=true;}
        packetPeak=std::max(packetPeak,unsigned(responseQueue.size()));check(responseQueue.size()<=4,"memory credit limit exceeded");
    }
    uint64_t access(unsigned off,bool write=false,uint64_t value=0,bool expectedError=false){
        S(control$$request$$bits$$address,regs+off);S(control$$request$$bits$$write,write);S(control$$request$$bits$$data,value);S(control$$request$$valid,1);
        unsigned deadline=cycles+100000;do{tick();check(cycles<deadline,"MMIO request timeout");}while(!G(control$$request$$ready));
        if(write&&!expectedError){
            if(off==160)stagedPostAddress=value;
            if(off==176&&value==1){
                unsigned s=slot(stagedPostAddress);check(stagedPostAddress==ram+offset(s),"POST address must exactly name slot");
                check(!descriptorOwned[s]&&owner[s]<0,"POST reused owned descriptor generation");
                descriptorOwned[s]=true;postedDescriptors.push_back({s,++descriptorGenerations[s]});++descriptorPosts;
                check(descriptorPosts-descriptorPops<=4,"independent POST ownership overflow");
            }
        }
        S(control$$request$$valid,0);do{tick();check(cycles<deadline,"MMIO reply timeout");}while(!G(control$$response$$valid));
        check(bool(G(control$$response$$bits$$error))==expectedError,"MMIO error mismatch");auto result=G(control$$response$$bits$$data);
        S(control$$response$$ready,1);tick();S(control$$response$$ready,0);return result;
    }
    void post(unsigned s){access(160,true,ram+offset(s));access(168,true,slotStride);access(176,true,1);}
    void cpu(unsigned a,bool write=false,uint64_t value=0){
        auto result=write?0:word(a);S(cpu$$request$$bits$$address,ram+a);S(cpu$$request$$bits$$write,write);S(cpu$$request$$bits$$data,value);S(cpu$$request$$valid,1);
        do{tick();}while(!G(cpu$$request$$ready));S(cpu$$request$$valid,0);
        until([&]{return G(cpu$$response$$valid);},"CPU cache response timeout");
        check(!G(cpu$$response$$bits$$error)&&!G(cpu$$response$$bits$$pageFault)&&G(cpu$$response$$bits$$returnHandle)==0&&G(cpu$$response$$bits$$data)==result,"CPU independent cache byte oracle mismatch");
        S(cpu$$response$$ready,1);tick();S(cpu$$response$$ready,0);
        if(write)for(unsigned b=0;b<8;++b)expected.at(a+b)=uint8_t(value>>(8*b));
    }
    void reclaim(bool repost){
        check(!completedDescriptors.empty(),"POP without independent completion FIFO");
        const auto expectedCompletion=completedDescriptors.front();const unsigned s=expectedCompletion.descriptor.slot;
        uint64_t addr=access(200),meta=access(208);
        if(mutation=="pop-address"&&descriptorPops==0)addr=ram+offset((s+1)%4);
        check(addr==ram+offset(s),"completion POP order/address mismatch");
        check(owner[s]==int(expectedCompletion.frame)&&descriptorOwned[s]&&descriptorGenerations[s]==expectedCompletion.descriptor.generation,"POP descriptor generation mismatch");
        auto& f=frames[expectedCompletion.frame];
        check(f.complete,"MMIO completion before response ledger");check(meta==(length|(f.failed?65536:0)),"MMIO completed byte/error metadata mismatch");
        access(216,true,1);completedDescriptors.pop_front();owner[s]=-1;descriptorOwned[s]=false;++descriptorPops;
        if(repost){for(unsigned b=0;b<slotStride;++b)ddr.byte(offset(s)+b)=expected.at(offset(s)+b)=0xa5;post(s);}
    }
    void checkDrain(bool rearmed){
        while(cycles<end)tick();until([&]{return axiEmpty();},"final AXI owner drain timeout");
        check(!held&&responseQueue.empty()&&acceptedFrames.empty()&&axiOwners.empty(),"residual packet/AXI/frame ownership");
        check(!activeFrame&&completedDescriptors.empty(),"residual active/completed descriptor FIFO");
        check(postedDescriptors.size()==(rearmed?4U:0U)&&descriptorPosts-descriptorPops==postedDescriptors.size(),"final independent POST FIFO ownership mismatch");
        std::array<bool,4> pendingSlots{};
        for(const auto& desc:postedDescriptors){check(!pendingSlots[desc.slot]&&descriptorOwned[desc.slot]&&descriptorGenerations[desc.slot]==desc.generation,"final posted descriptor generation mismatch");pendingSlots[desc.slot]=true;}
        for(unsigned s=0;s<4;++s)check(owner[s]<0&&descriptorOwned[s]==rearmed&&pendingSlots[s]==rearmed,"residual descriptor generation");
        check(G(macOccupied)==0&&G(macPrefetchOccupied)==0&&G(dmaPrefetchOccupied)==0&&G(outstanding)==0&&!G(macPending)&&!G(dmaPending),"final hardware storage or writes not drained");
        if(rearmed)check(G(owned)==4&&G(completed)==0&&G(pending)==3&&G(dmaState)==1,"final posted ownership state mismatch");
        else check(G(owned)==0&&G(completed)==0&&G(pending)==0,"final empty ownership state mismatch");
        check(ddr.memory==expected,"full-memory independent sentinel/byte oracle mismatch");
        check(lineReads==lineReadResponses,"final line-read owners not drained");
        check(packetAw==writes&&packetB==writes&&responses==writes,"final request AXI B response conservation");
        for(const auto& stage:stages)check(stage.occupied==0,"final stage response owner not drained");check(bufferOccupancy==0,"final request-buffer owner not drained");
    }
    void run(){
        access(184,true,1);for(unsigned s=0;s<4;++s)post(s);start=cycles;sourceOn=true;
        unsigned reclaimed=0;const unsigned deadline=cycles+count*(length+100)*200+100000;
        while(source<count||!wireEnded.empty()||completed<accepted||!acceptedFrames.empty()||!responseQueue.empty()||reclaimed<completed){
            check(cycles<deadline,"continuous source drain timeout");auto state=access(192);
            if((state>>8)&255){reclaim(true);++reclaimed;}
        }
        check(source==count&&accepted+dropped==count&&completed==accepted,"offered accepted dropped completion conservation");checkDrain(true);
        check(primaryAccepted+primaryDropped==count-warmup&&primaryCompleted==primaryAccepted,"primary window frame conservation");
        check(primaryAccepted>0&&primaryCompleted>0&&!ackLat.empty()&&writes>0&&responses>0,"vacuous primary accepted/write coverage");
        const double hz=125000000.;
        std::cout<<"ETHERNET_HOME_PASS profile=selected-combined-timing-repair-memory generation_identity_bits=64 common_hz=125000000 length="<<length<<" warmup="<<warmup<<" offered="<<count-warmup
            <<" total_offered="<<count<<" accepted="<<accepted<<" dropped="<<dropped<<" completed="<<completed<<" errors="<<errors<<" good_bytes="<<goodBytes
            <<" descriptor_posts="<<descriptorPosts<<" descriptor_pops="<<descriptorPops<<" packet_peak="<<packetPeak<<" writes="<<writes<<" responses="<<responses<<" successful_responses="<<successfulResponses<<" packet_aw="<<packetAw<<" packet_b="<<packetB
            <<" axi_ar="<<ddr.arCount<<" axi_aw="<<ddr.awCount<<" axi_b="<<ddr.bCount<<" backing_w_bytes="<<ddr.wBytes<<" latency="<<latency
            <<" start="<<start<<" measured_start="<<measuredStart<<" source_end="<<end<<" end="<<cycles<<" primary_accepted="<<primaryAccepted
            <<" primary_dropped="<<primaryDropped<<" primary_completed="<<primaryCompleted<<" fixed_completed="<<fixedCompleted<<" fixed_good_bytes="<<fixedBytes
            <<" fixed_fps="<<fixedCompleted*hz/(end-measuredStart)<<" fixed_mbps="<<fixedBytes*8.*hz/(end-measuredStart)/1e6
            <<" offered_window_cycles="<<end-measuredStart<<" primary_interval_cycles="<<cycles-measuredStart<<" drain_cycles="<<cycles-end
            <<" fps="<<primaryCompleted*hz/(cycles-measuredStart)<<" mbps="<<primaryCompleted*length*8.*hz/(cycles-measuredStart)/1e6
            <<" mibps="<<primaryCompleted*length*hz/(cycles-measuredStart)/1048576.<<" ready_stalls="<<readyStalls<<" credit_stalls="<<creditStalls
            <<" empty_stalls="<<emptyStalls<<" descriptor_stalls="<<descriptorStalls<<" probes="<<probes<<" dirty_probe_beats="<<dirtyBeats
            <<" measured_offers="<<measuredOffers<<" measured_requests="<<measuredRequests<<" measured_responses="<<measuredResponses
            <<" request_duty="<<double(measuredRequests)/(cycles-measuredStart)<<" response_duty="<<double(measuredResponses)/(cycles-measuredStart)
            <<" line_reads="<<lineReads<<" line_read_responses="<<lineReadResponses<<" home_requests="<<homeRequests<<" home_responses="<<homeResponses<<" tl_a="<<tlA<<" tl_d="<<tlD;
        auto q=[](std::vector<unsigned> v,double p){if(v.empty())return 0U;std::sort(v.begin(),v.end());return v[std::min(v.size()-1,size_t(p*(v.size()-1)))];};
        for(auto pair:{std::make_pair("offer",&offerLat),std::make_pair("ack",&ackLat),std::make_pair("completion",&completionLat)})
            std::cout<<" "<<pair.first<<"_p50="<<q(*pair.second,.5)<<" "<<pair.first<<"_p95="<<q(*pair.second,.95)<<" "<<pair.first<<"_max="<<q(*pair.second,1.);
        auto hist=[](const char* name,const auto& a){std::cout<<" "<<name<<"=";for(unsigned i=0;i<a.size();++i)std::cout<<(i?",":"")<<a[i];};
        hist("mac_occupancy",macOcc);hist("mac_prefetch_occupancy",macPrefOcc);hist("dma_prefetch_occupancy",dmaOcc);hist("write_outstanding",outstanding);
        hist("axi_write_ids",axiIds);hist("tl_a_sources",tlSources);hist("buffer_occupancy",bufferHistogram);hist("local_owner_peaks",localOwnerPeaks);
        std::cout<<" buffer_peak="<<bufferPeak<<" axi_peak_reads="<<ddr.peakR<<" axi_peak_writes="<<ddr.peakW;
        for(unsigned i=0;i<stages.size();++i){const auto& st=stages[i];std::string prefix="stage"+std::to_string(i);
            std::cout<<" "<<prefix<<"_requests="<<st.requests<<" "<<prefix<<"_responses="<<st.responses<<" "<<prefix<<"_offers="<<st.offers
                <<" "<<prefix<<"_ready="<<st.ready<<" "<<prefix<<"_blocked="<<st.blocked<<" "<<prefix<<"_response_blocked="<<st.responseBlocked<<" "<<prefix<<"_peak="<<st.peak;
            hist((prefix+"_occupancy").c_str(),st.histogram);
        }std::cout<<"\n";
    }
    void safety(const std::string& scenario){
        if(scenario=="dirty"){
            cpu(slotBase,true,0x0123456789abcdefULL);cpu(slotBase+72,true,0xfedcba9876543210ULL);
            check(ddr.word(slotBase)!=word(slotBase)&&ddr.word(slotBase+72)!=word(slotBase+72),"missing dirty destination cache witness");
        }
        bool stop=scenario.starts_with("stop-");expectFailure=stop||scenario=="error";
        if(scenario=="error")ddr.denyWrite=slotBase+16;
        if(scenario=="stop-held")holdB=true;
        access(184,true,1);post(0);start=cycles;sourceOn=true;
        if(stop){
            if(scenario=="stop-collect")until([&]{return owner[0]>=0&&!frames[0].dataDone;},"collect STOP witness missing");
            else if(scenario=="stop-held")until([&]{return held&&heldBCycles>0;},"held offer STOP witness missing");
            else {
                until([&]{return frames[0].writes==(length+7)/8;},"fully issued STOP witness missing");
                holdB=true;until([&]{return heldBCycles>0;},"response-drain STOP witness missing");
            }
            stopped=cycles;access(144,true,1);access(176,true,1,true);access(184,true,0,true);
            if(holdB){for(unsigned i=0;i<40;++i)tick();check(completed==0&&packetB<writes,"STOP completed before held AXI B");holdB=false;}
        }
        until([&]{return completed==1;},"short coherent case completion timeout");
        if(scenario=="stop-collect")check(frames[0].writes==0,"collect STOP emitted packet writes");
        if(scenario=="stop-held")check(heldAfterStop>0,"held offer did not survive STOP");
        if(scenario=="stop-held")check(frames[0].writes>0&&frames[0].writes<(length+7)/8,"STOP failed to stop prefix issuing");
        if(scenario=="stop-drain")check(frames[0].writes==(length+7)/8&&frames[0].responses==frames[0].writes,"response-drain STOP lost issued writes");
        if(scenario=="error")check(frames[0].errors==1&&packetBErrors==1&&goodBytes==0,"error success-accounting contract failed");
        reclaim(false);access(184,true,0);sourceOn=false;checkDrain(false);
        if(scenario=="dirty"){
            check(probes>=2&&dirtyBeats>=16,"real coherent dirty-probe coverage absent");
            for(unsigned a=slotBase;a<slotBase+80;a+=8)cpu(a);
            S(flushRequest,1);until([&]{return G(flushDone);},"dirty final cache/home flush timeout");S(flushRequest,0);tick();checkDrain(false);
        }
        // Every failed-generation case restarts in the same model without reset.
        if(expectFailure){
            expectFailure=false;ddr.denyWrite.reset();stopped=0;addFrame(count);++count;end=0;gap=0;fixedCaptured=false;
            access(184,true,1);post(1);sourceOn=true;
            until([&]{return completed==2;},"fresh generation restart timeout");reclaim(false);access(184,true,0);sourceOn=false;checkDrain(false);
            check(!frames[1].failed&&frames[1].successful==(length+7)/8,"restart generation did not complete cleanly");
        }
        std::cout<<"ETHERNET_HOME_SAFETY_PASS case="<<scenario<<" cycles="<<cycles<<" completed="<<completed<<" failed="<<errors
            <<" descriptor_posts="<<descriptorPosts<<" descriptor_pops="<<descriptorPops<<" packet_peak="<<packetPeak<<" writes="<<writes<<" responses="<<responses<<" successful_responses="<<successfulResponses<<" packet_b="<<packetB<<" b_errors="<<packetBErrors
            <<" good_bytes="<<goodBytes<<" held_b_cycles="<<heldBCycles<<" held_offer_cycles="<<heldOfferCycles<<" held_after_stop="<<heldAfterStop
            <<" probes="<<probes<<" dirty_probe_beats="<<dirtyBeats<<" copy_request_valid=0\n";
    }
};
int main(int argc,char** argv){
    try{
        check(argc>=2,"usage: primary length frames latency [mutation] | safety case [mutation]");std::string mode=argv[1];
        if(mode=="primary"){
            check(argc>=5,"primary requires length frames latency");Test t(std::stoul(argv[2]),std::stoul(argv[3]),std::stoul(argv[4]),16,argc>5?argv[5]:"");t.run();
        }else{
            check(mode=="safety"&&argc>=3,"unknown scenario");std::string scenario=argv[2];
            check(scenario=="dirty"||scenario=="stop-collect"||scenario=="stop-held"||scenario=="stop-drain"||scenario=="error","unknown safety case");
            Test t(scenario=="dirty"?67:1514,1,32,0,argc>3?argv[3]:"");t.safety(scenario);
        }
        return 0;
    }catch(const std::exception& e){std::cerr<<"ETHERNET_HOME_FAIL "<<e.what()<<"\n";return 1;}
}
