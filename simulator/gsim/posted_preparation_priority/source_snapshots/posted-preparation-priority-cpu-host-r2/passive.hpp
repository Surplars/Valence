#pragma once
#include "axi_accounting.h"
#include <vector>
#include <cstdlib>
#include <fstream>
namespace bandwidth {
using posted_board::AxiSample;
using posted_board::Window;
struct EdgeClock {
    bool seen=false; uint64_t previous=0;
    void sample(uint64_t cycle) {
        posted_board::demand(!seen || cycle==previous+1,"passive sample duplicate/gap/omitted edge");
        seen=true;previous=cycle;
    }
};
struct OwnerEvent {
    unsigned kind=0,slot=0,epoch=0,cohortSlot=0;uint64_t generation=0,line=0,cycle=0,cohortGeneration=0;
    bool member=false,reservation=false,ticket=false,newLine=false,victimValid=false,victimDirty=false;
    unsigned tokenIndex=0,responseTicket=0,mshr=0,set=0,way=0,ticketSlot=0,ticketOwnerSlot=0;
    uint64_t tokenTag=0,victimAddress=0,ticketOwnerGeneration=0;
    void json(std::ostream&o)const;
};
constexpr const char* ownerNames[]={"accepted","installed","drained","victim_release_ack","released"};
inline void OwnerEvent::json(std::ostream&o)const{
    o<<"{\"event\":\""<<ownerNames[kind]<<"\",\"slot\":"<<slot<<",\"generation\":"<<generation<<",\"epoch\":"<<epoch<<",\"line\":"<<line<<",\"cycle\":"<<cycle
     <<",\"cohort_slot\":"<<cohortSlot<<",\"cohort_generation\":"<<cohortGeneration;
    if(member)o<<",\"token_index\":"<<tokenIndex<<",\"token_tag\":"<<tokenTag<<",\"response_ticket\":"<<responseTicket;
    if(kind==0)o<<",\"new_line\":"<<newLine;
    if(reservation){o<<",\"mshr\":"<<mshr<<",\"set\":"<<set<<",\"way\":"<<way<<",\"victim_valid\":"<<victimValid;if(victimValid)o<<",\"victim_dirty\":"<<victimDirty<<",\"victim_address\":"<<victimAddress;}
    if(ticket)o<<",\"wb_ticket_slot\":"<<ticketSlot<<",\"wb_ticket_owner_slot\":"<<ticketOwnerSlot<<",\"wb_ticket_owner_generation\":"<<ticketOwnerGeneration;
    o<<'}';
}
struct OwnerSample { std::vector<OwnerEvent> events; bool failed=false; uint64_t live=0; };
template<class D>OwnerSample ownerSample(D& d){
    OwnerSample s;s.failed=d.get_lineage$$owner$$failed();
    s.live=d.get_lineage$$owner$$mshrMask()|d.get_lineage$$owner$$postedMask()|d.get_lineage$$owner$$responseMask()|d.get_lineage$$owner$$wbMask()|d.get_lineage$$cacheBusy();
    if(d.get_lineage$$owner$$accepted$$valid()){OwnerEvent e;e.kind=0;
        e.slot=d.get_lineage$$owner$$accepted$$bits$$member$$context$$owner$$slot();
        e.generation=d.get_lineage$$owner$$accepted$$bits$$member$$context$$owner$$generation();
        e.epoch=d.get_lineage$$owner$$accepted$$bits$$member$$context$$epoch();
        e.line=d.get_lineage$$owner$$accepted$$bits$$member$$context$$lineAddress();
        e.cohortSlot=d.get_lineage$$owner$$accepted$$bits$$member$$context$$cohortRoot$$slot();
        e.cohortGeneration=d.get_lineage$$owner$$accepted$$bits$$member$$context$$cohortRoot$$generation();
        e.member=true;e.tokenIndex=d.get_lineage$$owner$$accepted$$bits$$member$$token$$index();e.tokenTag=d.get_lineage$$owner$$accepted$$bits$$member$$token$$tag();e.responseTicket=d.get_lineage$$owner$$accepted$$bits$$member$$responseTicket();
        e.newLine=d.get_lineage$$owner$$accepted$$bits$$newLine();
        e.reservation=true;e.mshr=d.get_lineage$$owner$$accepted$$bits$$reservation$$mshr();e.set=d.get_lineage$$owner$$accepted$$bits$$reservation$$set();e.way=d.get_lineage$$owner$$accepted$$bits$$reservation$$way();e.victimValid=d.get_lineage$$owner$$accepted$$bits$$reservation$$victimValid();
        if(e.victimValid){e.victimDirty=d.get_lineage$$owner$$accepted$$bits$$reservation$$victimDirty();e.victimAddress=d.get_lineage$$owner$$accepted$$bits$$reservation$$victimAddress();}
        s.events.push_back(e);
    }
    if(d.get_lineage$$owner$$installedValid()){OwnerEvent e;e.kind=1;
        e.slot=d.get_lineage$$owner$$installedEvent$$context$$owner$$slot();
        e.generation=d.get_lineage$$owner$$installedEvent$$context$$owner$$generation();
        e.epoch=d.get_lineage$$owner$$installedEvent$$context$$epoch();
        e.line=d.get_lineage$$owner$$installedEvent$$context$$lineAddress();
        e.cohortSlot=d.get_lineage$$owner$$installedEvent$$context$$cohortRoot$$slot();
        e.cohortGeneration=d.get_lineage$$owner$$installedEvent$$context$$cohortRoot$$generation();
        e.reservation=true;e.mshr=d.get_lineage$$owner$$installedEvent$$reservation$$mshr();e.set=d.get_lineage$$owner$$installedEvent$$reservation$$set();e.way=d.get_lineage$$owner$$installedEvent$$reservation$$way();e.victimValid=d.get_lineage$$owner$$installedEvent$$reservation$$victimValid();
        if(e.victimValid){e.victimDirty=d.get_lineage$$owner$$installedEvent$$reservation$$victimDirty();e.victimAddress=d.get_lineage$$owner$$installedEvent$$reservation$$victimAddress();}
        s.events.push_back(e);
    }
    if(d.get_lineage$$owner$$drained$$valid()){OwnerEvent e;e.kind=2;
        e.slot=d.get_lineage$$owner$$drained$$bits$$context$$owner$$slot();
        e.generation=d.get_lineage$$owner$$drained$$bits$$context$$owner$$generation();
        e.epoch=d.get_lineage$$owner$$drained$$bits$$context$$epoch();
        e.line=d.get_lineage$$owner$$drained$$bits$$context$$lineAddress();
        e.cohortSlot=d.get_lineage$$owner$$drained$$bits$$context$$cohortRoot$$slot();
        e.cohortGeneration=d.get_lineage$$owner$$drained$$bits$$context$$cohortRoot$$generation();
        e.member=true;e.tokenIndex=d.get_lineage$$owner$$drained$$bits$$token$$index();e.tokenTag=d.get_lineage$$owner$$drained$$bits$$token$$tag();e.responseTicket=d.get_lineage$$owner$$drained$$bits$$responseTicket();
        s.events.push_back(e);
    }
    if(d.get_lineage$$owner$$completed$$valid()){OwnerEvent e;e.kind=3;
        e.slot=d.get_lineage$$owner$$completed$$bits$$context$$owner$$slot();
        e.generation=d.get_lineage$$owner$$completed$$bits$$context$$owner$$generation();
        e.epoch=d.get_lineage$$owner$$completed$$bits$$context$$epoch();
        e.line=d.get_lineage$$owner$$completed$$bits$$context$$lineAddress();
        e.cohortSlot=d.get_lineage$$owner$$completed$$bits$$context$$cohortRoot$$slot();
        e.cohortGeneration=d.get_lineage$$owner$$completed$$bits$$context$$cohortRoot$$generation();
        e.reservation=true;e.mshr=d.get_lineage$$owner$$completed$$bits$$reservation$$mshr();e.set=d.get_lineage$$owner$$completed$$bits$$reservation$$set();e.way=d.get_lineage$$owner$$completed$$bits$$reservation$$way();e.victimValid=d.get_lineage$$owner$$completed$$bits$$reservation$$victimValid();
        if(e.victimValid){e.victimDirty=d.get_lineage$$owner$$completed$$bits$$reservation$$victimDirty();e.victimAddress=d.get_lineage$$owner$$completed$$bits$$reservation$$victimAddress();}
        e.ticket=true;e.ticketSlot=d.get_lineage$$owner$$completed$$bits$$ticket$$slot();e.ticketOwnerSlot=d.get_lineage$$owner$$completed$$bits$$ticket$$owner$$slot();e.ticketOwnerGeneration=d.get_lineage$$owner$$completed$$bits$$ticket$$owner$$generation();
        s.events.push_back(e);
    }
    if(d.get_lineage$$owner$$released$$valid()){OwnerEvent e;e.kind=4;
        e.slot=d.get_lineage$$owner$$released$$bits$$context$$owner$$slot();
        e.generation=d.get_lineage$$owner$$released$$bits$$context$$owner$$generation();
        e.epoch=d.get_lineage$$owner$$released$$bits$$context$$epoch();
        e.line=d.get_lineage$$owner$$released$$bits$$context$$lineAddress();
        e.cohortSlot=d.get_lineage$$owner$$released$$bits$$context$$cohortRoot$$slot();
        e.cohortGeneration=d.get_lineage$$owner$$released$$bits$$context$$cohortRoot$$generation();
        e.reservation=true;e.mshr=d.get_lineage$$owner$$released$$bits$$reservation$$mshr();e.set=d.get_lineage$$owner$$released$$bits$$reservation$$set();e.way=d.get_lineage$$owner$$released$$bits$$reservation$$way();e.victimValid=d.get_lineage$$owner$$released$$bits$$reservation$$victimValid();
        if(e.victimValid){e.victimDirty=d.get_lineage$$owner$$released$$bits$$reservation$$victimDirty();e.victimAddress=d.get_lineage$$owner$$released$$bits$$reservation$$victimAddress();}
        s.events.push_back(e);
    }
    return s;
}
struct OwnerCounts {
    uint64_t count[5]={},liveCycles=0;std::vector<OwnerEvent> examples;
    void add(const OwnerSample& s){
        posted_board::demand(!s.failed,"passive posted owner failure observed");liveCycles+=s.live!=0;
        for(const auto& e:s.events){++count[e.kind];if(examples.size()<12)examples.push_back(e);}
    }
    void json(std::ostream& o,const char* label)const{
        o<<"{\"window\":\""<<label<<"\",\"full_generation_bits\":64,\"live_cycles\":"<<liveCycles;
        for(unsigned i=0;i<5;++i)o<<",\""<<ownerNames[i]<<"\":"<<count[i];
        o<<",\"causal_attribution\":\"unknown_bus_owner_not_joined\",\"examples\":[";bool comma=false;
        for(const auto&e:examples){if(comma)o<<',';comma=true;e.json(o);}o<<"]}";
    }
};
struct Passive {
    std::ofstream trace;uint64_t traceEvents=0;
    void openTrace(){const char*path=std::getenv("POSTED_BANDWIDTH_OWNER_TRACE");posted_board::demand(path&&*path,"owner sidecar path missing");trace.open(path);posted_board::demand(bool(trace),"cannot open owner sidecar");}
    void writeEvents(const OwnerSample&s,Window w){
        posted_board::demand(bool(trace),"owner sidecar not open");
        for(const auto&e:s.events){trace<<"{\"sequence\":"<<traceEvents++<<",\"window\":\""<<(w==Window::Kernel?"roi":w==Window::Flush?"flush":"outside")<<"\",\"owner\":";e.json(trace);trace<<"}\n";}
        posted_board::demand(bool(trace),"owner sidecar write failed");
    }
    posted_board::AxiAccounting axi;EdgeClock clock;bool pending=false;uint64_t cycle=0;
    AxiSample prior;OwnerSample priorOwners;OwnerCounts kernelOwners,flushOwners,wholeOwners;
    template<class D,class M>void sample(D&d,M&m,uint64_t now,unsigned acceptedPhase){
        clock.sample(now);
        // pfroi has just accepted the previous edge, so its phase classifies
        // exactly this pending AXI/owner snapshot. No DUT/memory writes occur.
        if(pending){Window w=acceptedPhase==1?Window::Kernel:acceptedPhase==2?Window::Flush:Window::None;
            axi.sample(prior,w);wholeOwners.add(priorOwners);writeEvents(priorOwners,w);
            if(w==Window::Kernel)kernelOwners.add(priorOwners);if(w==Window::Flush)flushOwners.add(priorOwners);
        }
        AxiSample s;s.arValid=d.get_io$$ddrAxi$$ar$$valid();s.arReady=m.arReady;
        s.awValid=d.get_io$$ddrAxi$$aw$$valid();s.awReady=m.awReady;
        s.rValid=m.rValid;s.rReady=d.get_io$$ddrAxi$$r$$ready();
        s.wValid=d.get_io$$ddrAxi$$w$$valid();s.wReady=m.wReady;
        s.bValid=m.bValid;s.bReady=d.get_io$$ddrAxi$$b$$ready();
        s.arId=d.get_io$$ddrAxi$$ar$$bits$$id();s.arLen=d.get_io$$ddrAxi$$ar$$bits$$len();s.arSize=d.get_io$$ddrAxi$$ar$$bits$$size();
        s.awId=d.get_io$$ddrAxi$$aw$$bits$$id();s.awLen=d.get_io$$ddrAxi$$aw$$bits$$len();s.awSize=d.get_io$$ddrAxi$$aw$$bits$$size();
        const auto r=m.selected();if(s.rValid){posted_board::demand(r!=m.pendingReads.end(),"driven R lacks original DDR owner");s.rId=r->id;s.rLast=r->beat+1==r->count;}
        s.bId=m.wId;s.wStrobe=d.get_io$$ddrAxi$$w$$bits$$strb();s.wLast=d.get_io$$ddrAxi$$w$$bits$$last();
        prior=s;priorOwners=ownerSample(d);for(auto& e:priorOwners.events)e.cycle=now;cycle=now;pending=!d.get_backendReset();
    }
    void finish(std::ostream&o,unsigned selected,uint64_t roiCycles,uint64_t flushCycles){
        trace<<"{\"terminal\":true,\"events\":"<<traceEvents<<"}\n";trace.flush();posted_board::demand(bool(trace),"owner sidecar terminal flush failed");
        axi.finish(selected>=18);posted_board::demand(axi.kernel.cycles==roiCycles&&axi.flush.cycles==flushCycles,"passive/legacy ROI edge mismatch");
        o<<"POSTED_BANDWIDTH_AXI ";axi.kernel.json(o,"roi");if(selected>=18){o<<"\nPOSTED_BANDWIDTH_AXI ";axi.flush.json(o,"flush");}
        o<<"\nPOSTED_BANDWIDTH_OWNER ";kernelOwners.json(o,"roi");o<<"\nPOSTED_BANDWIDTH_OWNER ";flushOwners.json(o,"flush");
        o<<"\nPOSTED_BANDWIDTH_OWNER ";wholeOwners.json(o,"whole_boot_diagnostic");
        o<<"\nPOSTED_BANDWIDTH_USEFUL {\"case\":"<<selected<<",\"architectural_read_bytes\":"<<(selected<18?65536:selected%2?131072:0)<<",\"architectural_write_bytes\":"<<(selected<18?0:131072)<<",\"raw_bus_bytes_are_useful\":false,\"prefetch_useful_bus_bytes\":null,\"ddr_due\":32,\"ddr_beat_gap\":1,\"injected_held_b\":false}\n";
    }
};
}
