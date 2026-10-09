#pragma once
// Independent byte-array AXI slave: no DUT constants/state contribute to expectations.
struct PipelineDdr {
    struct Read { uint32_t address; unsigned count, size, id, beat; uint64_t due, serial; bool error; };
    struct Write { uint32_t address; unsigned count, size, id, beat; uint64_t due, serial; bool error; };
    std::vector<uint8_t> memory, high;
    std::map<uint64_t,uint64_t> completedB;
    std::deque<Read> reads;
    std::deque<Write> writes, replies;
    std::optional<uint64_t> heldR, heldB;
    uint64_t rData=0, now=0, serial=0, arCount=0, awCount=0, rBytes=0, wBytes=0, bCount=0;
    uint64_t lastW=0,lastB=0,lastDestinationB=0,peakR=0,peakW=0,mixedCycles=0;
    uint64_t destination=0,length=0, destinationBytes=0;
    unsigned readDelay=32,bDelay=40;
    bool stalls=true,idSkew=true,reversePairs=false;
    bool arReady=false,awReady=false,wReady=false,rValid=false,bValid=false;
    bool corruptWrite=false,dropWrite=false,mutationApplied=false;
    std::optional<uint32_t> denyRead,denyWrite;
    PipelineDdr():memory(1024*1024),high(4096) {}
    uint8_t& byte(uint64_t a){if(a<memory.size())return memory.at(a);check(a>=DMA_RAM_BYTES-high.size()&&a<DMA_RAM_BYTES,"AXI touched unmapped sparse backing gap");return high.at(a-(DMA_RAM_BYTES-high.size()));}
    const uint8_t& byte(uint64_t a) const {if(a<memory.size())return memory.at(a);check(a>=DMA_RAM_BYTES-high.size()&&a<DMA_RAM_BYTES,"AXI read unmapped sparse backing gap");return high.at(a-(DMA_RAM_BYTES-high.size()));}
    uint64_t word(uint32_t a) const {uint64_t v=0;for(unsigned b=0;b<8;++b)v|=uint64_t(byte(uint64_t(a)+b))<<(8*b);return v;}
    bool target(uint32_t a) const { return a>=destination&&a<destination+length; }
    template<class Q> static auto selected(Q& q,const std::optional<uint64_t>& s) {
        return std::find_if(q.begin(),q.end(),[&](const auto& e){return s&&e.serial==*s;});
    }
    static void format(uint32_t address,unsigned count,unsigned size,unsigned burst) {
        check(size<=3&&count>=1&&count<=16&&burst==1,"AXI format outside declared contract");
        check(uint64_t(address)+(uint64_t(count)<<size)<=DMA_RAM_BYTES,"AXI outside independent aperture");
        check(!(address&((1U<<size)-1))&&(address&4095U)+(count<<size)<=4096,"AXI alignment or 4KiB boundary");
    }
    template<class Dut> void drive(Dut& d,uint64_t cycle) {
        now=cycle;arReady=reads.size()<4&&(!stalls||cycle%7!=2);awReady=writes.size()+replies.size()<2&&(!stalls||cycle%11!=3);
        wReady=!writes.empty()&&(!stalls||cycle%5!=1);
        if(!heldR)for(auto i=reads.rbegin();i!=reads.rend();++i)if(cycle>=i->due){heldR=i->serial;rData=word((i->address+(i->beat<<i->size))&~7U);break;}
        if(!heldB)for(auto i=replies.rbegin();i!=replies.rend();++i)if(cycle>=i->due){heldB=i->serial;break;}
        auto r=selected(reads,heldR);auto b=selected(replies,heldB);rValid=r!=reads.end();bValid=b!=replies.end();
        d.set_io$$ddrAxi$$ar$$ready(arReady);d.set_io$$ddrAxi$$aw$$ready(awReady);d.set_io$$ddrAxi$$w$$ready(wReady);
        d.set_io$$ddrAxi$$r$$valid(rValid);d.set_io$$ddrAxi$$r$$bits$$id(rValid?r->id:0);
        d.set_io$$ddrAxi$$r$$bits$$data(rValid?rData:0);d.set_io$$ddrAxi$$r$$bits$$last(rValid&&r->beat+1==r->count);
        d.set_io$$ddrAxi$$r$$bits$$resp(rValid&&r->error&&r->beat+1==r->count?2:0);
        d.set_io$$ddrAxi$$b$$valid(bValid);d.set_io$$ddrAxi$$b$$bits$$id(bValid?b->id:0);d.set_io$$ddrAxi$$b$$bits$$resp(bValid&&b->error?2:0);
    }
    template<class Dut> void sample(Dut& d) {
        if(d.get_io$$ddrAxi$$ar$$valid()&&arReady){
            uint32_t a=d.get_io$$ddrAxi$$ar$$bits$$addr();unsigned n=d.get_io$$ddrAxi$$ar$$bits$$len()+1,s=d.get_io$$ddrAxi$$ar$$bits$$size(),id=d.get_io$$ddrAxi$$ar$$bits$$id();
            format(a,n,s,d.get_io$$ddrAxi$$ar$$bits$$burst());for(auto&x:reads)check(x.id!=id,"AXI reused read ID");
            reads.push_back({a,n,s,id,0,now+readDelay+(reversePairs&&((a/64)%2==0)?96:0),serial++,denyRead&&a==*denyRead});++arCount;
        }
        if(d.get_io$$ddrAxi$$aw$$valid()&&awReady){
            uint32_t a=d.get_io$$ddrAxi$$aw$$bits$$addr();unsigned n=d.get_io$$ddrAxi$$aw$$bits$$len()+1,s=d.get_io$$ddrAxi$$aw$$bits$$size(),id=d.get_io$$ddrAxi$$aw$$bits$$id();
            format(a,n,s,d.get_io$$ddrAxi$$aw$$bits$$burst());for(auto&x:writes)check(x.id!=id,"AXI reused write ID");for(auto&x:replies)check(x.id!=id,"AXI reused pending B ID");
            writes.push_back({a,n,s,id,0,0,serial++,denyWrite&&a==*denyWrite});++awCount;
        }
        if(d.get_io$$ddrAxi$$w$$valid()&&wReady){
            check(!writes.empty(),"AXI W lost address owner");auto&w=writes.front();uint32_t a=(w.address+(w.beat<<w.size))&~7U;
            check(bool(d.get_io$$ddrAxi$$w$$bits$$last())==(w.beat+1==w.count),"AXI WLAST mismatch");
            uint64_t v=d.get_io$$ddrAxi$$w$$bits$$data();unsigned mask=d.get_io$$ddrAxi$$w$$bits$$strb();
            bool mutate=target(a)&&!mutationApplied&&(corruptWrite||dropWrite);if(mutate){mutationApplied=true;if(corruptWrite)v^=1;}
            for(unsigned b=0;b<8;++b)if(mask&(1U<<b)){++wBytes;if(target(a+b))++destinationBytes;if(!(mutate&&dropWrite))byte(uint64_t(a)+b)=uint8_t(v>>(8*b));}
            lastW=now+1;++w.beat;if(w.beat==w.count){w.due=now+bDelay+(reversePairs&&((w.address/64)%2==0)?128:0)+(idSkew?(w.id%2?3:17):0);replies.push_back(w);writes.pop_front();}
        }
        if(rValid&&d.get_io$$ddrAxi$$r$$ready()){
            auto r=selected(reads,heldR);check(r!=reads.end(),"AXI R lost owner");rBytes+=1U<<r->size;++r->beat;
            if(r->beat==r->count)reads.erase(r);else r->due=now+1;heldR.reset();
        }
        if(bValid&&d.get_io$$ddrAxi$$b$$ready()){
            auto b=selected(replies,heldB);check(b!=replies.end()&&b->beat==b->count,"AXI B before last W");
            ++completedB[b->address];lastB=now+1;if(target(b->address))lastDestinationB=now+1;replies.erase(b);heldB.reset();++bCount;
        }
        peakR=std::max(peakR,uint64_t(reads.size()));peakW=std::max(peakW,uint64_t(writes.size()+replies.size()));mixedCycles+=!reads.empty()&&(!writes.empty()||!replies.empty());
    }
    bool destinationPending() const {for(auto&w:writes)if(target(w.address))return true;for(auto&w:replies)if(target(w.address))return true;return false;}
};
