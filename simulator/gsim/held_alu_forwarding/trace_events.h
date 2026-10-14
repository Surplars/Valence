#pragma once
#include "held_observer.h"
#include <fstream>
namespace b1 {
inline void trace_events(const Snapshot& s,const HeldObserver& o){
    static std::ofstream out("timing-events.tsv");
    static bool header=false;
    auto pc=[&](Token t){auto i=o.history.find(t);return i==o.history.end()?uint64_t(0):i->second.instruction.pc;};
    if(!header){out<<"cycle";
        for(unsigned n=0;n<2;++n)for(const char* field:{"occupied","pc","index","tag","capture","deqValid","deqReady","cancel","promise","destination","source1","source2","left","right"})out<<"\ts"<<n<<"_"<<field;
        for(unsigned n=0;n<2;++n)for(const char* field:{"valid","accepted","producer","pc","index","tag"})out<<"\tc"<<n<<"_"<<field;
        for(unsigned n=0;n<2;++n)for(const char* field:{"valid","pc","word","index","tag","source1","source2","destination"})out<<"\trename"<<n<<"_"<<field;
        for(const char* unit:{"lsu","mul","div","system"})out<<'\t'<<unit<<"_start\t"<<unit<<"_pc";
        out<<"\tretire0_pc\tretire1_pc\n";header=true;
    }
    out<<s.cycle;
    for(const auto& e:s.stage)out<<'\t'<<e.occupied<<'\t'<<(e.occupied?pc(e.held):0)<<'\t'<<e.held.index<<'\t'<<e.held.tag<<'\t'<<e.capture()<<'\t'<<e.deqValid<<'\t'<<e.deqReady<<'\t'<<e.cancel<<'\t'<<e.promise<<'\t'<<e.destination<<'\t'<<e.heldSource1<<'\t'<<e.heldSource2<<'\t'<<e.left<<'\t'<<e.right;
    for(const auto& e:s.complete)out<<'\t'<<e.valid<<'\t'<<e.accepted<<'\t'<<unsigned(e.producer)<<'\t'<<(e.valid?pc(e.token):0)<<'\t'<<e.token.index<<'\t'<<e.token.tag;
    for(const auto& e:s.rename)out<<'\t'<<e.valid<<'\t'<<e.pc<<'\t'<<e.instruction<<'\t'<<e.token.index<<'\t'<<e.token.tag<<'\t'<<e.source1<<'\t'<<e.source2<<'\t'<<e.destination;
    for(const auto& e:{s.memory,s.multiplier,s.divider})out<<'\t'<<e.fire<<'\t'<<(e.fire?pc(e.token):0);
    out<<'\t'<<s.system.fire<<'\t'<<(s.system.fire?pc(s.system.token):0);
    for(const auto& e:s.retire)out<<'\t'<<(e.valid?e.pc:0);
    out<<'\n';
}
}
