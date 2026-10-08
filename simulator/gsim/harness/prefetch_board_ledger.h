#pragma once
#include <array>
#include <cstdlib>
#include <deque>
#include <fstream>
#include <map>
#include <set>
#include <vector>

// Passive, address-based ownership ledger for the frozen Selected board model.
// The DUT's data/tag arrays never supply expected payload values.
struct PrefetchBoardLedger {
    static constexpr uint64_t src=0x80400000ULL, dst=0x81400040ULL, bytes=65536;
    struct Token {
        uint64_t address=0, allocated=0, filled=0, consumed=0, evicted=0;
        uint64_t evictingAddress=0;
        unsigned index=0;
        int region=-1, pass=-1;
        bool destinationEviction=false;
        bool consumerWrite=false, reportedUseful=false;
        uint64_t flushBeforeConsume=0;
        uint64_t firstReadAfterStore=0, firstReadAddress=0;
    };
    struct Slot { uint64_t address=0, token=0; int region=-1, pass=-1; bool valid=false; };
    struct Counts {
        uint64_t reads=0, loadChecks=0, firstHits=0, priorFillHits=0;
        uint64_t allocated=0, filled=0, consumed=0, unusedEvicted=0, destinationEvicted=0;
        uint64_t missingHit=0, falseReleaseCycles=0, trueReleaseCycles=0, falseReleaseStarts=0;
        std::set<uint64_t> readLines, allocatedLines, consumedLines, priorHitLines;
        std::map<uint64_t,uint64_t> readCounts;
    };
    struct Expected { uint64_t address=0; int region=-1, pass=-1; bool checkValue=false; };
    std::array<Counts,6> roi{};
    std::array<std::array<Counts,3>,6> passes{};
    std::array<std::array<unsigned,8192>,6> sourceWords{};
    std::array<std::array<std::array<uint8_t,1024>,3>,6> seen{};
    std::array<Slot,512> slots{};
    std::array<uint64_t,2> owners{};
    std::array<bool,2> trueRelease{};
    std::vector<Token> tokens{Token{}};
    struct FirstHit { uint64_t cycle,address,token; unsigned index; int region,pass,fillRegion,fillPass; };
    std::vector<FirstHit> firstHits;
    std::deque<Expected> replies;
    uint64_t checked=0, usefulEvents=0, tokenConsumes=0, storeConsumes=0, unreportedAfterFlush=0, lastFlush=0, cycles=0;
    bool injected=false;
    const char *mutation=std::getenv("PREFETCH_LEDGER_INJECT");
    static bool source(uint64_t a) { return a>=src && a<src+bytes; }
    static bool destination(uint64_t a) { return a>=dst && a<dst+bytes; }
    static uint64_t line(uint64_t a) { return a&~63ULL; }
    int nextPass(int region,uint64_t address) const {
        if(region<0 || !source(address)) return -1;
        unsigned p=3, start=(line(address)-src)/8;
        for(unsigned k=0;k<8;++k) p=std::min(p,sourceWords[region][start+k]);
        return p<3?int(p):-1;
    }
    template<class F> void count(int region,int pass,F f) {
        if(region>=0) { f(roi[region]); if(pass>=0&&pass<3) f(passes[region][pass]); }
    }
    void remove(unsigned index,uint64_t clock,uint64_t replacing,bool isDestination) {
        auto &s=slots[index];
        if(s.valid && s.token) {
            auto &t=tokens.at(s.token);
            check(t.address==s.address && t.index==index,"prefetch ledger eviction identity mismatch");
            check(!t.evicted,"prefetch ledger duplicate eviction");
            t.evicted=clock; t.evictingAddress=replacing; t.destinationEviction=isDestination;
            if(!t.consumed) count(t.region,t.pass,[&](Counts &c){++c.unusedEvicted;c.destinationEvicted+=isDestination;});
        }
        s.valid=false;
    }
    void sample(SBoardSocGsim &d,const Test &test,int region) {
        const uint64_t clock=test.cycles+1;
        cycles=clock;
        const auto events=d.get_dataPathEvents();
        const uint64_t address=d.get_dataPathRequest9Address();
        const uint64_t meta=d.get_dataPathRequest9Meta();
        const bool write=meta&1;
        const unsigned pf=d.get_dataPrefetchEvents();
        if(d.board$platform$core$core$core$backend$systemUnit$_io_fenceIFlush_T) lastFlush=clock;
#define PC(name) d.board$platform$privateCache$##name
        // Physical adapter ownership is ordered even across register/MMIO routes.
        // Capture expectations at acceptance; speculative load cancellation cannot
        // transfer an older response's expected value to a younger request.
        if((events>>19)&1) {
            int pass=-1;
            bool timedSource=region>=0 && (region==0 || region==1 || region==3) && source(address);
            bool verify=timedSource && !write && (region==0 || region==3);
            if(timedSource) {
                check(!(address&7) && ((meta>>7)&3)==3,"source oracle expects aligned 64-bit accesses");
                pass=sourceWords[region][(address-src)/8]++;
                check(pass<3,"source oracle saw more than three copies of one word");
            }
            replies.push_back({address,region,pass,verify});
        }
        if((events>>21)&1) {
            check(!replies.empty(),"physical response has no independent owner");
            auto expected=replies.front(); replies.pop_front();
            if(expected.checkValue) {
                uint64_t value=d.get_dataPathReply0Data();
                if(mutation && std::string(mutation)=="response" && !injected) {value^=1;injected=true;}
                check(!d.get_dataPathReply0Flags() && value==0x10203040ULL+(expected.address-src)/8,
                    "source ordered response oracle mismatch");
                ++checked;count(expected.region,expected.pass,[](Counts &c){++c.loadChecks;});
            }
        }
        if(region>=0 && d.get_io$$ddrAxi$$ar$$valid() && test.ddr.arReady) {
            // DDR addresses are relative to the RAM aperture in this exact model.
            const uint64_t a=uint64_t(d.get_io$$ddrAxi$$ar$$bits$$addr())+ramBase;
            if(source(a)) count(region,nextPass(region,a),[&](Counts &c){++c.reads;c.readLines.insert(line(a));++c.readCounts[line(a)];});
        }
        for(unsigned w=0;w<2;++w) if(region>=0 && PC(wbLive)[w] && PC(wbPrefetch)[w]) {
            if(trueRelease[w]) ++roi[region].trueReleaseCycles; else ++roi[region].falseReleaseCycles;
        }
        // Demand observation precedes this edge's fill and invalidation updates.
        if(PC(cpuFire) && source(address) && !write && region>=0 && (region==0||region==3)) {
            check((events>>19)&1,"cache source acceptance differs from physical adapter acceptance");
            const unsigned word=(address-src)/8, pass=sourceWords[region][word]-1;
            auto &mask=seen[region][pass][word/8];
            if(!mask && PC(found)) {
                const auto &s=slots[PC(index)];
                check(s.valid && s.address==line(address),"independent resident line identity mismatch");
                firstHits.push_back({clock,s.address,s.token,PC(index),region,int(pass),s.region,s.pass});
                count(region,pass,[&](Counts &c){++c.firstHits;
                    if(s.region!=region || s.pass!=int(pass)){++c.priorFillHits;c.priorHitLines.insert(s.address);}});
            }
            mask|=1U<<(word%8);
        }
        bool independentReadConsumption=false;
        if(PC(cpuFire) && PC(ordinary) && PC(found)) {
            auto &s=slots[PC(index)];
            check(s.valid && s.address==line(address),"cache hit disagrees with independent fill/eviction ledger");
            if(s.token && !write) {
                auto &t=tokens.at(s.token);
                if(t.consumed && t.consumerWrite && !t.firstReadAfterStore) {
                    t.firstReadAfterStore=clock;t.firstReadAddress=address;
                    check(!((pf>>2)&1),"store-consumed prefetch reported a second useful consumption");
                    std::cout<<"PREFETCH_LEDGER_READ_AFTER_STORE token="<<s.token<<" line="<<t.address
                        <<" first_store_cycle="<<t.consumed<<" read_cycle="<<clock<<" read_address="<<address
                        <<" tracked_valid="<<unsigned(PC(trackedValid))<<" tracked_address="<<PC(trackedAddress)<<"\n";
                }
            }
            if(s.token && !tokens.at(s.token).consumed) {
                auto &t=tokens.at(s.token);
                check(t.filled && !t.evicted && t.address==line(address),"prefetch consumption lost immutable token");
                t.consumed=clock;t.consumerWrite=write;t.reportedUseful=(pf>>2)&1;
                t.flushBeforeConsume=lastFlush;t.consumerWrite?++storeConsumes:0;
                independentReadConsumption=!write;++tokenConsumes;
                if(!write && !t.reportedUseful) {
                    check(lastFlush>t.filled && !(PC(trackedValid)&&PC(trackedAddress)==t.address),
                        "unreported first prefetch read lacks an observed tracking-cancelling flush");
                    ++unreportedAfterFlush;
                }
                count(t.region,t.pass,[&](Counts &c){++c.consumed;c.consumedLines.insert(t.address);});
            }
        }
        if((pf>>2)&1) {
            ++usefulEvents;
            if(!PC(cpuFire)||!PC(readHit)) count(region,nextPass(region,address),[](Counts &c){++c.missingHit;});
            check(independentReadConsumption,"reported useful event lacks one actual immutable-token hit");
        }
        if(PC(startEviction)) {
            const bool direct=PC(_directEviction_T_14);
            const unsigned m=PC(evictMshr), w=PC(wbFree);
            const bool miss=PC(evictFromMiss);
            const uint64_t replacing=miss?(direct?address:PC(pending$$address)[m]):0;
            const bool isWrite=miss && (direct?write:bool(PC(pending$$write)[m]));
            const unsigned index=PC(evictIndex);
            check(slots[index].valid && slots[index].address==PC(evictionAddress$NEXT),"evicted line identity mismatch");
            bool copyIdentity=false;
            if(slots[index].token && isWrite && destination(replacing)) {
                const auto &t=tokens.at(slots[index].token);
                copyIdentity=t.address==src+(line(replacing)-dst)+64 &&
                    ((t.address>>6)&255)==((replacing>>6)&255) && PC(replacement)[index&255]==(index>>8);
            }
            remove(index,clock,replacing,copyIdentity);
            trueRelease[w]=miss && !direct && PC(prefetchOwner)[m];
            if(region>=0 && PC(wbPrefetch$NEXT)[w] && !trueRelease[w]) ++roi[region].falseReleaseStarts;
        }
        if(PC(probeFire) && PC(actualProbeHit)) remove(PC(probeIndex),clock,0,false);
        if(PC(flushActive)) {
            unsigned i=PC(flushIndex);
            if(PC(valid)[i] && !PC(valid$NEXT)[i] && slots[i].valid) remove(i,clock,0,false);
        }
        if(PC(engine$_io_response_valid_T_1)) {
            const unsigned m=PC(engine$io$$response$$bits$$tag), index=PC(pendingIndex)[m];
            const uint64_t a=line(PC(pending$$address)[m]);
            const bool prefetch=PC(prefetchOwner)[m];
            if(prefetch) {
                check(owners[m]!=0,"prefetch fill lacks allocation token");
                auto &t=tokens.at(owners[m]);
                check(t.address==a && t.index==index && !t.filled,"prefetch fill changed token identity");
                t.filled=clock;count(t.region,t.pass,[](Counts &c){++c.filled;});
            }
            check(!PC(engine$io$$response$$bits$$error),"unexpected failed board refill");
            check(!slots[index].valid,"refill overwrote a resident line without an observed eviction");
            slots[index]={a,prefetch?owners[m]:0,region,nextPass(region,a),true};
            owners[m]=0;
        }
        if((pf>>1)&1) {
            const unsigned m=PC(freeMshr), index=PC(pfIndex);
            check(!owners[m],"prefetch allocation reused a live token owner");
            uint64_t a=PC(candidateAddress);
            if(mutation && std::string(mutation)=="token" && !injected && region>=0) {a^=64;injected=true;}
            tokens.push_back({a,clock,0,0,0,0,index,region,nextPass(region,a),false});
            owners[m]=tokens.size()-1;
            count(region,nextPass(region,a),[&](Counts &c){++c.allocated;c.allocatedLines.insert(a);});
        }
#undef PC
    }
    static void row(const Counts &c,int region,int pass) {
        std::cout<<"PREFETCH_LEDGER region="<<region<<" pass="<<pass<<" source_reads="<<c.reads
            <<" unique_read_lines="<<c.readLines.size()<<" checked_loads="<<c.loadChecks
            <<" first_line_hits="<<c.firstHits<<" earlier_fill_hits="<<c.priorFillHits
            <<" unique_earlier_fill_lines="<<c.priorHitLines.size()<<" allocations="<<c.allocated
            <<" unique_allocated_lines="<<c.allocatedLines.size()<<" fills="<<c.filled
            <<" first_consumptions="<<c.consumed<<" unique_consumed_lines="<<c.consumedLines.size()
            <<" unused_evictions="<<c.unusedEvicted<<" exact_copy_destination_evictions="<<c.destinationEvicted
            <<" consumption_without_hit="<<c.missingHit<<" false_release_starts="<<c.falseReleaseStarts
            <<" false_release_cycles="<<c.falseReleaseCycles<<" true_release_cycles="<<c.trueReleaseCycles<<"\n";
    }
    void report() const {
        check(checked==49152,"independent ordered source response count mismatch");
        check(usefulEvents+storeConsumes+unreportedAfterFlush==tokenConsumes,"prefetch useful/token ledger total mismatch");
        const char *prefix=std::getenv("PREFETCH_LEDGER_OUTPUT");
        check(prefix && *prefix,"missing passive ledger output path");
        std::ofstream tokenFile(std::string(prefix)+"-tokens.csv");
        std::ofstream addressFile(std::string(prefix)+"-source-reads.csv");
        std::ofstream hitFile(std::string(prefix)+"-first-hits.csv");
        check(tokenFile.good()&&addressFile.good()&&hitFile.good(),"cannot create passive ledger detail files");
        tokenFile<<"id,region,pass,address,index,allocated,filled,consumed,evicted,evicting_address,exact_copy_destination,consumer_write,reported_useful,flush_before_consume,first_read_after_store,first_read_address\n";
        for(size_t i=1;i<tokens.size();++i){const auto &t=tokens[i];
            tokenFile<<i<<','<<t.region<<','<<t.pass<<','<<t.address<<','<<t.index<<','<<t.allocated<<','<<t.filled<<','
                <<t.consumed<<','<<t.evicted<<','<<t.evictingAddress<<','<<t.destinationEviction<<','<<t.consumerWrite<<','
                <<t.reportedUseful<<','<<t.flushBeforeConsume<<','<<t.firstReadAfterStore<<','<<t.firstReadAddress<<'\n';}
        addressFile<<"region,pass,address,read_requests\n";
        for(int r=0;r<6;++r){for(const auto &[address,count]:roi[r].readCounts)addressFile<<r<<",-1,"<<address<<','<<count<<'\n';
            for(int p=0;p<3;++p)for(const auto &[address,count]:passes[r][p].readCounts)addressFile<<r<<','<<p<<','<<address<<','<<count<<'\n';}
        hitFile<<"cycle,region,pass,address,index,token,fill_region,fill_pass\n";
        for(const auto &h:firstHits)hitFile<<h.cycle<<','<<h.region<<','<<h.pass<<','<<h.address<<','<<h.index<<','
            <<h.token<<','<<h.fillRegion<<','<<h.fillPass<<'\n';
        tokenFile.close();addressFile.close();hitFile.close();
        check(tokenFile.good()&&addressFile.good()&&hitFile.good(),"passive ledger detail write failed");
        for(int r=0;r<6;++r){row(roi[r],r,-1);if(r==0||r==1||r==3)for(int p=0;p<3;++p)row(passes[r][p],r,p);}
        uint64_t pending=0;
        for(size_t i=1;i<tokens.size();++i) pending+=!tokens[i].consumed&&!tokens[i].evicted;
        std::cout<<"PREFETCH_LEDGER_TOTAL tokens="<<tokens.size()-1<<" useful="<<usefulEvents
            <<" checked_loads="<<checked<<" first_store_consumptions="<<storeConsumes
            <<" first_reads_after_tracking_flush="<<unreportedAfterFlush
            <<" unused_still_resident="<<pending<<" pending_physical_replies="<<replies.size()<<"\n";
    }
};
