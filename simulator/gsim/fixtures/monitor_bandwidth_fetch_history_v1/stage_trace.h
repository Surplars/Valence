#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <ostream>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// Passive registered-state observations. No ALU-completion handshake is inferred
// from a ROB done bit. Source producers retain complete (generation,index) keys.
namespace monitor_stage {
using Key = std::pair<uint64_t,unsigned>;
inline void require(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
inline constexpr std::array<const char*,8> stateNames{"lsu_start","completion_visible_awaiting_retire","issued_completion_not_visible","nonload_pending_registered_ready_not_issue_eligibility","load_address_source_not_ready","load_source_ready_no_matching_staged_address","load_staged_capacity_predicate_blocked","load_staged_other_start_gating"};
inline constexpr std::array<const char*,13> histogramNames{"load_accepted_allocation_gap","pointer_addi_accepted_allocation_gap","sum_add_accepted_allocation_gap","branch_accepted_allocation_gap","all_hot_allocation_to_pending_clear_visible","all_hot_done_visible_to_retire","load_allocation_to_source_ready_visible","load_source_ready_to_prepared_visible","load_prepared_visible_to_start","load_start_to_physical_request","load_predecessor_done_visible_to_start","load_predecessor_retirement_to_start_signed","load_predecessor_retired_without_done_to_start"};
inline bool hot(uint64_t pc){return pc>=0xfff787d0&&pc<=0xfff787dc&&(pc&3)==0;}
struct Entry {
    Key key{};uint64_t pc=0;
    unsigned source1=0,source2=0,destination=0;
    bool writes=false,alias=false,ready1=false,ready2=false,pending=false,done=false;
};
struct Snapshot {
    std::vector<Key> allocations; // Accepted rename prefix at this cycle, bound on next registered view.
    std::vector<Entry> entries; // ROB age order, oldest first, only allocated owners.
    std::optional<Key> prepared,start;
    uint64_t address=0;
    bool capacityBlocked=false,available=false;
};
struct Node {
    Entry identity;
    uint64_t allocated=0,seen=0;
    std::optional<uint64_t> ready1,ready2,pendingClear,prepared,start,physicalAccepted,done,retired,cancelled;
    std::optional<uint64_t> address;
    std::shared_ptr<Node> producer1,producer2;
    std::map<std::string,uint64_t> states;
};
struct StageTrace {
    std::map<Key,std::shared_ptr<Node>> active;
    std::map<Key,uint64_t> allocations;
    std::array<std::shared_ptr<Node>,64> physicalWriters{};
    std::vector<std::shared_ptr<Node>> records;
    uint64_t sourceProducerJoins=0,hotPhysicalJoins=0;
    void reset(){active.clear();allocations.clear();physicalWriters={};records.clear();sourceProducerJoins=hotPhysicalJoins=0;}
    static void observe(Node &n,const Entry &e,uint64_t cycle){
        require(n.identity.pc==e.pc&&n.identity.source1==e.source1&&n.identity.source2==e.source2&&
            n.identity.destination==e.destination&&n.identity.writes==e.writes&&n.identity.alias==e.alias,
            "hot stage immutable full-token identity changed");
        if(e.ready1&&!n.ready1)n.ready1=cycle;
        if(e.ready2&&!n.ready2)n.ready2=cycle;
        if(!e.pending&&!n.pendingClear)n.pendingClear=cycle;
        if(e.done&&!n.done)n.done=cycle;
    }
    void sample(uint64_t cycle,const Snapshot &s){
        require(s.entries.size()<=16,"hot stage ROB capacity exceeded");
        std::set<Key> keys;
        // Update existing producer completions before resolving a newly seen consumer.
        for(const auto &e:s.entries){require(keys.insert(e.key).second,"hot stage duplicate live full token");
            auto it=active.find(e.key);if(it!=active.end())observe(*it->second,e,cycle);}
        for(auto it=active.begin();it!=active.end();){if(!keys.contains(it->first)){
            if(!it->second->retired)it->second->cancelled=cycle;it=active.erase(it);
        }else ++it;}
        for(const auto &e:s.entries){
            require(e.key.second<16&&e.source1<64&&e.source2<64&&e.destination<64,"hot stage register schema range");
            auto it=active.find(e.key);
            if(it==active.end()){
                auto a=allocations.find(e.key);
                require(a!=allocations.end()&&a->second+1==cycle,"hot stage registered owner lacks exact prior-cycle allocation");
                auto n=std::make_shared<Node>();n->identity=e;n->allocated=a->second;n->seen=cycle;allocations.erase(a);
                // Only hot records retain dependency edges; ordinary execution
                // remains bounded to the live ROB and 64 last physical writers.
                if(hot(e.pc)){
                    n->producer1=physicalWriters[e.source1];n->producer2=physicalWriters[e.source2];
                    const unsigned used=e.pc<0xfff787d8?1:2;
                    for(unsigned operand=0;operand<used;++operand){const auto physical=operand?e.source2:e.source1;const auto producer=operand?n->producer2:n->producer1;
                        require(!physical||(producer&&producer->identity.destination==physical&&producer->identity.key.first<e.key.first),"hot used operand lost full-token physical producer");}
                    records.push_back(n);
                    if(e.pc==0xfff787d0){
                        require(bool(n->producer1),"hot load lost address-source producer");
                        require(n->producer1->identity.destination==e.source1&&n->producer1->identity.key!=e.key,
                            "hot load source physical/full-token binding mismatch");
                        require(n->producer1->identity.pc==0xfff787c8||n->producer1->identity.pc==0xfff787d4,
                            "hot load pointer predecessor PC changed");
                        ++sourceProducerJoins;
                    }
                }
                if(e.writes&&!e.alias&&e.destination)physicalWriters[e.destination]=n;
                it=active.emplace(e.key,n).first;
                observe(*n,e,cycle);
            }
            auto &n=*it->second;
            const bool prepared=s.prepared&&*s.prepared==e.key&&e.pending;
            if(prepared&&e.pc==0xfff787d0){
                if(!n.prepared)n.prepared=cycle;
                require(!n.address||*n.address==s.address,"hot load prepared address changed for full token");n.address=s.address;
            }
            if(hot(e.pc)){
                const bool start=s.start&&*s.start==e.key;
                const char *state;
                if(start)state="lsu_start";
                else if(e.done)state="completion_visible_awaiting_retire";
                else if(!e.pending)state="issued_completion_not_visible";
                else if(e.pc!=0xfff787d0)state="nonload_pending_registered_ready_not_issue_eligibility";
                else if(!e.ready1)state="load_address_source_not_ready";
                else if(!prepared)state="load_source_ready_no_matching_staged_address";
                else if(s.capacityBlocked)state="load_staged_capacity_predicate_blocked";
                else state="load_staged_other_start_gating";
                ++n.states[state];
            }
        }
        require(allocations.empty(),"hot stage accepted allocation absent from next registered ROB view");
        require(s.allocations.size()<=2,"hot stage allocation prefix width drift");
        for(const auto &key:s.allocations){require(key.second<16&&!active.contains(key)&&allocations.emplace(key,cycle).second,
            "hot stage duplicate accepted allocation full token");}
        if(s.start){
            auto it=active.find(*s.start);
            require(it!=active.end(),"hot stage start lacks full-token ROB owner");
            auto &n=*it->second;
            if(n.identity.pc==0xfff787d0){
                require(!n.start&&n.ready1&&n.prepared&&s.available,"hot load start missing readiness/preparation/capacity witness");
                n.start=cycle;
            }
        }
    }
    void retire(Key key,uint64_t pc,uint64_t cycle){
        auto it=active.find(key);require(it!=active.end()&&it->second->identity.pc==pc,"hot stage retirement lost full-token ROB owner");
        auto &n=*it->second;require(!n.retired&&!n.cancelled,"hot stage duplicate/cancelled retirement");n.retired=cycle;
        // Ordinary ALUs and fast loads may retire on accepted completion without registered done.
        // Record that explicitly elsewhere; do not fabricate a done-visible time.
    }
    void physical(Key key,uint64_t address,uint64_t cycle){
        auto it=active.find(key);
        if(it==active.end())return; // killed read remains owned by the independent LSU ledger
        auto &n=*it->second;if(n.identity.pc!=0xfff787d0)return;
        require(n.start&&n.address&&*n.address==address,"hot physical request lost staged full-token address");
        require(!n.physicalAccepted&&cycle>=*n.start,"hot physical request duplicated or before start");n.physicalAccepted=cycle;++hotPhysicalJoins;
    }
    static int64_t value(const std::optional<uint64_t> &n){return n?int64_t(*n):-1;}
    void report(std::ostream &out,std::ostream &summary,unsigned expected=1024) const {
        std::array<unsigned,4> retired{};
        uint64_t doneJoins=0,retirementJoins=0;
        std::map<std::string,uint64_t> states;
        std::map<std::string,std::map<int64_t,uint64_t>> hist;
        for(auto name:stateNames)states[name]=0;
        for(auto name:histogramNames)hist[name]={};
        std::array<std::optional<uint64_t>,4> previousAllocation{};
        std::map<Key,std::shared_ptr<Node>> external;std::set<Key> hotKeys;
        for(const auto &n:records)hotKeys.insert(n->identity.key);
        out<<"kind\ttag\tindex\tpc\tsource1\tsource2\tdestination\tallocated\tfirst_seen\tready1_visible\tready2_visible\tpending_clear_visible\tprepared_visible\tlsu_start\tphysical_accepted\tdone_visible\tretired\tcancelled\tretired_without_done\tsrc1_tag\tsrc1_index\tsrc1_pc\tsrc1_done_visible\tsrc1_retired\tsrc2_tag\tsrc2_index\tsrc2_pc\tsrc2_done_visible\tsrc2_retired";
        for(auto name:stateNames)out<<"\tstate_"<<name;out<<'\n';
        auto row=[&](const Node &n,unsigned kind){
            out<<kind<<'\t'<<n.identity.key.first<<'\t'<<n.identity.key.second<<'\t'<<n.identity.pc<<'\t'<<n.identity.source1<<'\t'<<n.identity.source2<<'\t'<<n.identity.destination<<'\t'<<n.allocated<<'\t'<<n.seen<<'\t'<<value(n.ready1)<<'\t'<<value(n.ready2)<<'\t'<<value(n.pendingClear)<<'\t'<<value(n.prepared)<<'\t'<<value(n.start)<<'\t'<<value(n.physicalAccepted)<<'\t'<<value(n.done)<<'\t'<<value(n.retired)<<'\t'<<value(n.cancelled)<<'\t'<<bool(n.retired&&!n.done);
            for(auto producer:{n.producer1,n.producer2}){
                if(producer){out<<'\t'<<producer->identity.key.first<<'\t'<<producer->identity.key.second<<'\t'<<producer->identity.pc<<'\t'<<value(producer->done)<<'\t'<<value(producer->retired);
                    if(!hotKeys.contains(producer->identity.key))external.emplace(producer->identity.key,producer);}
                else out<<"\t-1\t-1\t-1\t-1\t-1";
            }
            for(auto name:stateNames){auto i=n.states.find(name);out<<'\t'<<(i==n.states.end()?0:i->second);}out<<'\n';
        };
        for(const auto &ptr:records){const auto &n=*ptr;row(n,0);
            require(bool(n.retired)!=bool(n.cancelled),"hot stage owner lacks exclusive terminal state");
            if(!n.retired)continue;
            const unsigned instructionIndex=(n.identity.pc-0xfff787d0)/4;++retired.at(instructionIndex);
            const std::array<const char*,4> labels{"load","pointer_addi","sum_add","branch"};
            if(previousAllocation[instructionIndex])++hist[std::string(labels[instructionIndex])+"_accepted_allocation_gap"][n.allocated-*previousAllocation[instructionIndex]];
            previousAllocation[instructionIndex]=n.allocated;
            for(auto [state,count]:n.states)states[state]+=count;
            auto add=[&](const char *name,std::optional<uint64_t> a,std::optional<uint64_t> b){if(a&&b)++hist[name][int64_t(*b)-int64_t(*a)];};
            add("all_hot_allocation_to_pending_clear_visible",n.allocated,n.pendingClear);
            add("all_hot_done_visible_to_retire",n.done,n.retired);
            if(n.identity.pc==0xfff787d0){
                require(n.ready1&&n.prepared&&n.start&&n.physicalAccepted&&n.producer1,
                    "hot retired load lacks mandatory source/preparation/physical witness");
                const auto &producer=*n.producer1;
                if(producer.done){require(*producer.done<=*n.start,"hot predecessor done observed after load start");++doneJoins;}
                else{require(producer.retired&&*producer.retired<=*n.start,"hot predecessor lacks done or retirement-without-done witness");++retirementJoins;
                    add("load_predecessor_retired_without_done_to_start",producer.retired,n.start);}
                add("load_allocation_to_source_ready_visible",n.allocated,n.ready1);
                add("load_source_ready_to_prepared_visible",n.ready1,n.prepared);
                add("load_prepared_visible_to_start",n.prepared,n.start);
                add("load_start_to_physical_request",n.start,n.physicalAccepted);
                add("load_predecessor_done_visible_to_start",producer.done,n.start);
                add("load_predecessor_retirement_to_start_signed",producer.retired,n.start);
            }
        }
        for(const auto &[key,n]:external)row(*n,1);
        require(retired==std::array<unsigned,4>{expected,expected,expected,expected},"hot stage exact scalar instruction coverage missing");
        require(doneJoins+retirementJoins==expected&&hotPhysicalJoins>=expected,"hot stage predecessor/physical join coverage missing");
        for(auto [state,count]:states)summary<<"MONITOR_STAGE_STATE name="<<state<<" owner_cycles="<<count<<'\n';
        for(const auto &[name,bins]:hist){summary<<"MONITOR_STAGE_HIST name="<<name<<" histogram=";bool comma=false;
            for(auto [gap,count]:bins){if(comma)summary<<',';comma=true;summary<<gap<<':'<<count;}summary<<'\n';}
        summary<<"MONITOR_STAGE_PASS hot_retired_loads="<<retired[0]<<" pointer_addi="<<retired[1]<<" sum_add="<<retired[2]<<" branch="<<retired[3]
            <<" source_producer_joins="<<sourceProducerJoins<<" retired_predecessor_done_joins="<<doneJoins<<" retired_predecessor_retirement_without_done_joins="<<retirementJoins<<" physical_address_joins="<<hotPhysicalJoins<<" external_producer_rows="<<external.size()
            <<" allocation_scope=accepted_rename_prefix_full_token completion_scope=registered_done_or_explicit_retirement_without_done pending_clear_scope=registered_pending_visibility\n";
    }
};
}
