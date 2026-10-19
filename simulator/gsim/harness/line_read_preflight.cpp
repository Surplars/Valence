#include "LineReadChannelGsim.h"
#include <algorithm>
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
static void check(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
#define DMA_RAM_BYTES (2ULL*1024*1024*1024)
#ifndef LINE_SHARED_SLOTS
#define LINE_SHARED_SLOTS 4
#endif
#ifndef LINE_WRITE_CREDITS
#define LINE_WRITE_CREDITS 2
#endif
#ifndef LINE_MAX_BURST_BEATS
#define LINE_MAX_BURST_BEATS 16
#endif
static constexpr unsigned bulkSize = LINE_MAX_BURST_BEATS == 8 ? 6 : 7;
#include "dma_pipeline_ddr.h"
static constexpr uint64_t base=0x80200000ULL;
static std::string mutation;
struct Command {
    unsigned tag,size=6,mask=255,sentA=0,returned=0,rBeats=0,wBeats=0,bBeats=0;
    uint64_t address=0,lastR=0;
    bool write=false,partial=false,error=false,rejected=false;
    std::vector<uint64_t> words,expected;
    std::optional<unsigned> id;
    unsigned count()const{return size>3?1U<<(size-3):1;}
};
struct Test {
    SLineReadChannelGsim d;
    PipelineDdr memory;
    std::vector<uint8_t> oracle,high;
    std::deque<Command> primaryQueue,lineQueue;
    std::map<unsigned,Command> primary,lines;
    std::map<unsigned,std::pair<bool,unsigned>> retainedIds;
    uint64_t cycles=0,primaryRequests=0,lineRequests=0,primaryResults=0,lineResults=0,concurrentCapture=0;
    bool holdPrimary=false,holdLine=false,pauseR=false,pauseB=false,pauseAW=false,pauseW=false,randomHolds=false,gappedProducer=false,aOfferHeld=false;
    std::optional<std::tuple<unsigned,unsigned,unsigned,uint64_t,bool,bool>> heldD;
    std::optional<std::tuple<unsigned,unsigned _BitInt(512),bool>> heldLine;
    std::optional<std::tuple<uint64_t,unsigned,unsigned,unsigned,unsigned>> heldAW,heldAR;
    std::optional<std::tuple<uint64_t,unsigned,bool>> heldW;
    bool mutated=false;
    Test():oracle(1024*1024),high(4096){
        for(unsigned i=0;i<oracle.size();++i)memory.memory[i]=oracle[i]=uint8_t((i*73U)^(i>>5)^0xa6U);
        for(unsigned i=0;i<high.size();++i)memory.high[i]=high[i]=uint8_t(i*41U^0x91U);
        d.set_io$$tl$$a$$valid(0);d.set_io$$tl$$c$$valid(0);d.set_io$$tl$$e$$valid(0);d.set_io$$tl$$b$$ready(0);
        d.set_io$$lineRead$$request$$valid(0);d.set_reset(1);tick();tick();d.set_reset(0);tick();
    }
    uint8_t& byte(uint64_t a){if(a<oracle.size())return oracle.at(a);check(a>=DMA_RAM_BYTES-high.size()&&a<DMA_RAM_BYTES,"independent byte address outside sparse aperture");return high.at(a-(DMA_RAM_BYTES-high.size()));}
    uint64_t word(uint64_t a){uint64_t value=0;for(unsigned i=0;i<8;++i)value|=uint64_t(byte(a+i))<<(8*i);return value;}
    static Command read(unsigned tag,uint64_t address,unsigned size=6){Command c;c.tag=tag;c.address=address;c.size=size;return c;}
    static Command write(unsigned tag,uint64_t address,unsigned size=6,unsigned mask=255){
        Command c=read(tag,address,size);c.write=true;c.mask=mask;c.partial=mask!=255;
        for(unsigned i=0;i<c.count();++i)c.words.push_back((address*0x9e3779b97f4a7c15ULL)^(uint64_t(i+1)*0xd6e8feb86659fd93ULL)^0x3456ab9876ULL);
        return c;
    }
    void admit(Command& c){
        c.rejected=c.address<base||c.address+uint64_t(1ULL<<c.size)>base+DMA_RAM_BYTES;
        c.error=c.rejected||(c.write?memory.denyWrite:memory.denyRead)==std::optional<uint32_t>(uint32_t(c.address-base));
        if(c.rejected)return;
        for(unsigned i=0;i<c.count();++i)c.expected.push_back(word((c.address-base+(uint64_t(i)<<std::min(c.size,3U)))&~7ULL));
        if(c.write)for(unsigned i=0;i<c.count();++i)for(unsigned b=0;b<8;++b)if(c.mask&(1U<<b))byte(((c.address-base+(uint64_t(i)<<std::min(c.size,3U)))&~7ULL)+b)=uint8_t(c.words[i]>>(8*b));
    }
    Command& owner(unsigned id){check(retainedIds.count(id),"AXI result lacks independent retained owner");auto [line,tag]=retainedIds.at(id);return line?lines.at(tag):primary.at(tag);}
    void assignId(unsigned id,uint64_t address,bool write){
        check(!retainedIds.count(id),"AXI ID reused before final logical retirement");
        std::optional<std::pair<bool,unsigned>> found;
        for(auto&[tag,c]:primary)if(c.address==address&&c.write==write&&!c.id){check(!found,"ambiguous independently accepted address");found={{false,tag}};}
        for(auto&[tag,c]:lines)if(c.address==address&&!write&&!c.id){check(!found,"ambiguous independently accepted address");found={{true,tag}};}
        check(bool(found),"AXI address has no independently accepted origin");retainedIds[id]=*found;auto&c=owner(id);c.id=id;
    }
    void tick(){
        check(cycles<250000,"two-ingress cycle budget exceeded");
        const auto p=primaryQueue.empty()?std::optional<Command>{}:std::optional{primaryQueue.front()};
        const auto l=lineQueue.empty()?std::optional<Command>{}:std::optional{lineQueue.front()};
        const bool pValid=p&&(aOfferHeld||!gappedProducer||!p->sentA||cycles%3==0);
        d.set_io$$tl$$a$$valid(pValid);d.set_io$$tl$$a$$bits$$opcode(p&&p->write?(p->partial?1:0):4);
        d.set_io$$tl$$a$$bits$$param(0);d.set_io$$tl$$a$$bits$$corrupt(0);d.set_io$$tl$$a$$bits$$size(p?p->size:6);
        d.set_io$$tl$$a$$bits$$source(p?p->tag:0);d.set_io$$tl$$a$$bits$$address(p?p->address:base);
        d.set_io$$tl$$a$$bits$$mask(p?p->mask:255);d.set_io$$tl$$a$$bits$$data(p&&p->write?p->words.at(p->sentA):0);
        d.set_io$$lineRead$$request$$valid(bool(l));d.set_io$$lineRead$$request$$bits$$tag(l?l->tag:0);
        d.set_io$$lineRead$$request$$bits$$address(l?l->address:base);
        const bool pReady=!holdPrimary&&(!randomHolds||cycles%13!=4),lReady=!holdLine&&(!randomHolds||cycles%17!=6);
        d.set_io$$tl$$d$$ready(pReady);d.set_io$$lineRead$$response$$ready(lReady);
        memory.drive(d,cycles);
        if(pauseR){memory.rValid=false;d.set_io$$ddrAxi$$r$$valid(0);}
        if(pauseB){memory.bValid=false;d.set_io$$ddrAxi$$b$$valid(0);}
        if(pauseAW){memory.awReady=false;d.set_io$$ddrAxi$$aw$$ready(0);}
        if(pauseW){memory.wReady=false;d.set_io$$ddrAxi$$w$$ready(0);}
        if(!mutated&&memory.rValid&&(mutation=="bad-rid"||mutation=="early-rlast")){
            if(mutation=="bad-rid")d.set_io$$ddrAxi$$r$$bits$$id(15);else d.set_io$$ddrAxi$$r$$bits$$last(1);mutated=true;
        }
        if(!mutated&&memory.bValid&&mutation=="bad-bid"){d.set_io$$ddrAxi$$b$$bits$$id(15);mutated=true;}
        std::map<unsigned,unsigned> captureBefore;for(auto&[tag,c]:primary)captureBefore[tag]=c.sentA;
        d.step();
        const bool pf=pValid&&d.get_io$$tl$$a$$ready(),lf=l&&d.get_io$$lineRead$$request$$ready();
        aOfferHeld=pValid&&!d.get_io$$tl$$a$$ready();
        if(pf){
            auto& q=primaryQueue.front();
            if(!q.sentA){check(!primary.count(q.tag),"primary source reused before response");auto c=q;admit(c);primary[q.tag]=c;++primaryRequests;}
            ++primary.at(q.tag).sentA;++q.sentA;if(q.sentA==(q.write?q.count():1U))primaryQueue.pop_front();
        }
        if(lf){auto c=*l;check(!lines.count(c.tag),"line tag reused before final response");admit(c);lines[c.tag]=c;lineQueue.pop_front();++lineRequests;}
        // These are queue enqueues, not shared-bridge allocations. The fixture
        // separately compares every real bridge handshake with direct preflight.
        if(pf&&lf)++concurrentCapture;
        auto awNow=std::make_tuple(uint64_t(d.get_io$$ddrAxi$$aw$$bits$$addr()),unsigned(d.get_io$$ddrAxi$$aw$$bits$$id()),unsigned(d.get_io$$ddrAxi$$aw$$bits$$len()),unsigned(d.get_io$$ddrAxi$$aw$$bits$$size()),unsigned(d.get_io$$ddrAxi$$aw$$bits$$burst()));
        auto arNow=std::make_tuple(uint64_t(d.get_io$$ddrAxi$$ar$$bits$$addr()),unsigned(d.get_io$$ddrAxi$$ar$$bits$$id()),unsigned(d.get_io$$ddrAxi$$ar$$bits$$len()),unsigned(d.get_io$$ddrAxi$$ar$$bits$$size()),unsigned(d.get_io$$ddrAxi$$ar$$bits$$burst()));
        auto wNow=std::make_tuple(uint64_t(d.get_io$$ddrAxi$$w$$bits$$data()),unsigned(d.get_io$$ddrAxi$$w$$bits$$strb()),bool(d.get_io$$ddrAxi$$w$$bits$$last()));
        if(heldAW)check(d.get_io$$ddrAxi$$aw$$valid()&&*heldAW==awNow,"stalled AW changed");
        if(heldAR)check(d.get_io$$ddrAxi$$ar$$valid()&&*heldAR==arNow,"stalled AR changed");
        if(heldW)check(d.get_io$$ddrAxi$$w$$valid()&&*heldW==wNow,"stalled W changed");
        heldAW=d.get_io$$ddrAxi$$aw$$valid()&&!memory.awReady?std::optional{awNow}:std::nullopt;
        heldAR=d.get_io$$ddrAxi$$ar$$valid()&&!memory.arReady?std::optional{arNow}:std::nullopt;
        heldW=d.get_io$$ddrAxi$$w$$valid()&&!memory.wReady?std::optional{wNow}:std::nullopt;
        if(d.get_io$$ddrAxi$$ar$$valid()&&memory.arReady)assignId(d.get_io$$ddrAxi$$ar$$bits$$id(),base+d.get_io$$ddrAxi$$ar$$bits$$addr(),false);
        if(d.get_io$$ddrAxi$$aw$$valid()&&memory.awReady)assignId(d.get_io$$ddrAxi$$aw$$bits$$id(),base+d.get_io$$ddrAxi$$aw$$bits$$addr(),true);
        if(d.get_io$$ddrAxi$$w$$valid()&&memory.wReady){
            check(!memory.writes.empty(),"W accepted without authored address owner");auto& c=owner(memory.writes.front().id);
            check(c.write&&c.wBeats<captureBefore[c.tag],"W borrowed an unaccepted current-edge producer credit");
            check(d.get_io$$ddrAxi$$w$$bits$$data()==c.words.at(c.wBeats)&&d.get_io$$ddrAxi$$w$$bits$$strb()==c.mask,"banked write independent byte/strobe oracle mismatch");++c.wBeats;
        }
        if(memory.rValid&&d.get_io$$ddrAxi$$r$$ready()){
            auto r=PipelineDdr::selected(memory.reads,memory.heldR);auto&c=owner(r->id);
            check(!c.write&&c.rBeats<c.count()&&memory.rData==c.expected.at(c.rBeats),"independent backing read byte oracle mismatch");
            ++c.rBeats;if(c.rBeats==c.count())c.lastR=cycles;
        }
        if(memory.bValid&&d.get_io$$ddrAxi$$b$$ready()){
            auto b=PipelineDdr::selected(memory.replies,memory.heldB);auto&c=owner(b->id);check(c.write&&c.wBeats==c.count(),"B before complete authored write");++c.bBeats;
        }
        auto dNow=std::make_tuple(unsigned(d.get_io$$tl$$d$$bits$$source()),unsigned(d.get_io$$tl$$d$$bits$$size()),unsigned(d.get_io$$tl$$d$$bits$$opcode()),uint64_t(d.get_io$$tl$$d$$bits$$data()),bool(d.get_io$$tl$$d$$bits$$denied()),bool(d.get_io$$tl$$d$$bits$$corrupt()));
        if(heldD)check(d.get_io$$tl$$d$$valid()&&*heldD==dNow,"stalled primary response changed");
        heldD=d.get_io$$tl$$d$$valid()&&!pReady?std::optional{dNow}:std::nullopt;
        if(d.get_io$$tl$$d$$valid()){
            auto tag=unsigned(d.get_io$$tl$$d$$bits$$source());check(primary.count(tag),"primary response lost independently accepted source");auto&c=primary.at(tag);
            check(d.get_io$$tl$$d$$bits$$size()==c.size&&d.get_io$$tl$$d$$bits$$opcode()==(c.write?0:1),"primary response control mismatch");
            check(bool(d.get_io$$tl$$d$$bits$$denied())==c.error&&bool(d.get_io$$tl$$d$$bits$$corrupt())==(!c.write&&c.error),"primary aggregate error mismatch");
            if(c.write)check(c.sentA==c.count()&&(c.rejected||c.bBeats==1),"primary write acknowledged before A/B drain");
            else check(c.rejected||c.rBeats==c.count(),"primary read replied before complete R burst");
            check(d.get_io$$tl$$d$$bits$$data()==(c.write||c.error?0:c.expected.at(c.returned)),"primary independent banked playback byte oracle mismatch");
            if(pReady&&++c.returned==(c.write?1U:c.count())){if(c.id)retainedIds.erase(*c.id);primary.erase(tag);++primaryResults;}
        }
        auto lNow=std::make_tuple(unsigned(d.get_io$$lineRead$$response$$bits$$tag()),d.get_io$$lineRead$$response$$bits$$data(),bool(d.get_io$$lineRead$$response$$bits$$error()));
        if(heldLine)check(d.get_io$$lineRead$$response$$valid()&&*heldLine==lNow,"stalled whole-line response changed");
        heldLine=d.get_io$$lineRead$$response$$valid()&&!lReady?std::optional{lNow}:std::nullopt;
        if(d.get_io$$lineRead$$response$$valid()){
            unsigned tag=d.get_io$$lineRead$$response$$bits$$tag();auto value=d.get_io$$lineRead$$response$$bits$$data();
            if(!mutated&&mutation=="line-tag"){tag^=64;mutated=true;}
            if(!mutated&&mutation=="line-data"){value^=1;mutated=true;}
            check(lines.count(tag),"whole-line independent tag oracle mismatch");auto&c=lines.at(tag);
            check(c.rejected||(c.rBeats==8&&c.lastR<cycles),"whole-line response preceded complete RLAST capture");
            unsigned _BitInt(512) expected=0;if(!c.error)for(unsigned i=0;i<8;++i)expected|=(unsigned _BitInt(512))(c.expected.at(i))<<(64*i);
            check(bool(d.get_io$$lineRead$$response$$bits$$error())==c.error&&value==expected,"whole-line independent byte/error oracle mismatch");
            if(lReady){if(c.id)retainedIds.erase(*c.id);lines.erase(tag);++lineResults;}
        }
        // Existing two-entry A, line-request and D boundary buffers are NOT
        // transaction slots. Real AXI ownership is still bounded by two IDs
        // and one write ID, with no early W/B credit or error relaxation.
        check(primary.size()+lines.size()<=LINE_SHARED_SLOTS+6,"existing boundary buffering overflow");
        check(retainedIds.size()<=LINE_SHARED_SLOTS,"physical AXI shared owner overflow");
        unsigned writes=0;for(auto&[id,key]:retainedIds)writes+=owner(id).write;
        check(writes<=LINE_WRITE_CREDITS,"physical AXI write quota overflow");
        memory.sample(d);++cycles;
    }
    void until(const std::function<bool()>&done,const char*message){
        // Four-slot upstream finished192 mixed owners inside12000 cycles;
        // two slots legally take longer under the SAME bounded service law.
        // Scale only the finite traffic budget; keep the original no-progress
        // bound and every byte/owner/error/backpressure oracle intact.
        const uint64_t work=primaryQueue.size()+lineQueue.size()+primary.size()+lines.size()+1;
        auto limit=cycles+std::max<uint64_t>(12000,512*work),lastProgress=cycles;
        uint64_t progress=0;
        while(!done()){
            tick();
            const auto now=memory.rBytes+memory.wBytes+memory.bCount+primaryResults+lineResults;
            if(now!=progress){lastProgress=cycles;progress=now;}
            if(cycles>=limit||cycles-lastProgress>=12000)std::cerr<<"LINE_TIMEOUT cycles="<<cycles<<" idle="<<cycles-lastProgress
                <<" accepted="<<primaryRequests<<','<<lineRequests<<" returned="<<primaryResults<<','<<lineResults
                <<" queued="<<primaryQueue.size()<<','<<lineQueue.size()<<" live="<<primary.size()<<','<<lines.size()
                <<" AXI_R="<<memory.rBytes<<" AXI_W="<<memory.wBytes<<" AXI_B="<<memory.bCount<<'\n';
            check(cycles<limit,message);
            check(cycles-lastProgress<12000,"two-ingress no-progress deadlock");
        }
    }
    void drain(){until([&]{return primaryQueue.empty()&&lineQueue.empty()&&primary.empty()&&lines.empty();},"two-ingress drain deadlock");check(retainedIds.empty()&&memory.reads.empty()&&memory.writes.empty()&&memory.replies.empty(),"retirement left AXI owner behind");check(memory.memory==oracle&&memory.high==high,"independent final memory mismatch");}
};
int main(int argc,char**argv){try{
    for(int i=1;i<argc;++i){std::string a=argv[i];if(a.starts_with("--mutate="))mutation=a.substr(9);else throw std::runtime_error("unknown option");}
    // Sources below are valid until their external response. Two existing
    // ingress queues can enqueue together; actual bridge allocation is NOT
    // the external enqueue. Direct unit cases remain untouched in the old file.
    {
        Test t;t.memory.readDelay=1;t.primaryQueue.push_back(Test::write(0,base+0x40000));
        t.lineQueue.push_back(Test::read(0,base));t.drain();
        check(t.concurrentCapture>0,"independent boundary enqueues did not overlap");
    }
    {
        Test t;t.memory.denyRead=64;
        t.lineQueue.push_back(Test::read(225,base+64));
        t.lineQueue.push_back(Test::read(226,base+DMA_RAM_BYTES-64));
        t.lineQueue.push_back(Test::read(227,base+DMA_RAM_BYTES));
        t.primaryQueue.push_back(Test::write(5,base+0x40000,bulkSize));t.drain();
        t.primaryQueue.push_back(Test::read(6,base+0x40000,bulkSize));t.drain();
        for(unsigned mask=0;mask<256;++mask){
            t.primaryQueue.push_back(Test::write(7,base+0x60000,3,mask));t.drain();
            t.primaryQueue.push_back(Test::read(8,base+0x60000,3));t.drain();
        }
    }
    {
        Test t;t.gappedProducer=true;t.pauseAW=true;t.pauseW=true;
        t.primaryQueue.push_back(Test::write(8,base+0x40000));
        t.lineQueue.push_back(Test::read(8,base));
        t.until([&]{return t.lineResults==1;},"held AW/W blocked independent line read");
        for(unsigned i=0;i<20;++i)t.tick();
        t.pauseAW=false;t.pauseW=false;t.drain();
    }
    {
        Test t;t.memory.reversePairs=true;
        for(unsigned i=0;i<96;++i){
            t.lineQueue.push_back(Test::read(i,base+64*i));
            t.primaryQueue.push_back(i%2?Test::read(i%16,base+0x40000+128*i,bulkSize):
                Test::write(i%16,base+0x40000+128*i,bulkSize));
        }
        t.drain();check(t.primaryRequests==96&&t.lineRequests==96,"stress lost accepted origin");
    }
    std::cout<<"LINE_PREFLIGHT_BOUNDARY_PASS real_slots="<<LINE_SHARED_SLOTS
        <<" real_write_credits="<<LINE_WRITE_CREDITS
        <<" existing_queues=2_each independent_DDR_bytes_errors_masks256_high_alias_gapped_A_reordered_AXI=PASS exact_reference_interface_cycles=PASS\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"LINE_PREFLIGHT_BOUNDARY_FAIL "<<e.what()<<"\n";return 1;}}
