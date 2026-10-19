// Independent two-owner, real R/D beat ledger. This is a modeled bridge ceiling,
// not CPU performance, MIG behavior, physical clock signoff or a DDR board score.
#include "TileLinkAxi4Bridge.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
static void need(bool v, const char* why) { if (!v) throw std::runtime_error(why); }
static constexpr uint64_t base = 0x80200000ULL;
static uint64_t pattern(uint64_t physical) { return 0x9163afe752490bcdULL ^ physical * 0x100010001ULL; }
struct Owner { unsigned source, beat=0; uint64_t address; bool issued=false, received=false; };
struct Read { unsigned id, beat=0, due; uint64_t address; };
int main(int argc, char** argv) { try {
    unsigned latency=argc>1?std::stoul(argv[1]):0;
    bool stalls=argc>2&&std::string(argv[2])=="1";
    bool high=argc>3&&std::string(argv[3])=="1";
    bool inject=argc>4&&std::string(argv[4])=="--inject";
    STileLinkAxi4Bridge d;
    d.set_io$$tl$$a$$valid(0);d.set_io$$tl$$c$$valid(0);d.set_io$$tl$$e$$valid(0);
    d.set_io$$tl$$d$$ready(0);d.set_io$$axi$$ar$$ready(0);d.set_io$$axi$$r$$valid(0);
    d.set_io$$axi$$aw$$ready(0);d.set_io$$axi$$w$$ready(0);d.set_io$$axi$$b$$valid(0);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
    std::array<bool,2> live{};
    std::deque<Owner> owners;
    std::vector<Read> reads;
    std::optional<Read> held;
    std::optional<std::pair<unsigned,uint64_t>> offer;
    std::optional<std::tuple<uint64_t,unsigned,unsigned>> heldD, heldAR;
    unsigned accepted=0, completed=0, rbeats=0, dbeats=0, ars=0, first=0, elapsed=0, peak=0;
    constexpr unsigned total=256, bytes=total*64;
    for(unsigned cycle=0;cycle<1000000&&completed<total;++cycle) {
        if(!offer&&accepted<total) for(unsigned source=0;source<2;++source) if(!live[source]) {
            offer={{source,(high?0x100000000ULL:base)+uint64_t(accepted)*64}};break;
        }
        if(!held) {
            auto it=std::find_if(reads.begin(),reads.end(),[&](const auto& r){return r.due<=cycle;});
            if(it!=reads.end()) held=*it;
        }
        const bool arReady=!stalls||cycle%5<3, dr=!stalls||cycle%7<5;
        d.set_io$$tl$$a$$valid(bool(offer));
        d.set_io$$tl$$a$$bits$$opcode(4);d.set_io$$tl$$a$$bits$$param(0);
        d.set_io$$tl$$a$$bits$$size(6);d.set_io$$tl$$a$$bits$$source(offer?offer->first:0);
        d.set_io$$tl$$a$$bits$$address(offer?offer->second:0);
        d.set_io$$tl$$a$$bits$$mask(255);d.set_io$$tl$$a$$bits$$data(0);d.set_io$$tl$$a$$bits$$corrupt(0);
        d.set_io$$tl$$d$$ready(dr);d.set_io$$axi$$ar$$ready(arReady);
        d.set_io$$axi$$r$$valid(bool(held));
        d.set_io$$axi$$r$$bits$$id(held?held->id:0);
        d.set_io$$axi$$r$$bits$$data(held?pattern(base+held->address+uint64_t(held->beat)*8):0);
        d.set_io$$axi$$r$$bits$$resp(0);d.set_io$$axi$$r$$bits$$last(held&&held->beat==7);
        d.step();
        need(!d.get_io$$axi$$aw$$valid()&&!d.get_io$$axi$$w$$valid(),"read benchmark emitted write");
        if(offer&&d.get_io$$tl$$a$$ready()) {
            need(!live[offer->first],"source reused before final D");
            owners.push_back({offer->first,0,offer->second});
            live[offer->first]=true;
            peak=std::max(peak,unsigned(owners.size()));
            if(!accepted)first=cycle;
            ++accepted;offer.reset();
        }
        auto ar=std::make_tuple(uint64_t(d.get_io$$axi$$ar$$bits$$addr()),
            unsigned(d.get_io$$axi$$ar$$bits$$id()),unsigned(d.get_io$$axi$$ar$$bits$$len()));
        bool av=d.get_io$$axi$$ar$$valid();
        if(heldAR) need(av&&ar==*heldAR,"AR changed while stalled");
        heldAR=av&&!arReady?std::optional{ar}:std::nullopt;
        if(av&&arReady) {
            auto it=std::find_if(owners.begin(),owners.end(),[&](const auto& r){
                return !r.issued&&r.address-base==std::get<0>(ar);});
            need(it!=owners.end()&&std::get<1>(ar)<2&&std::get<2>(ar)==7&&
                 d.get_io$$axi$$ar$$bits$$size()==3,"independent translated AR owner/length oracle");
            for(auto r:reads) need(r.id!=std::get<1>(ar),"AXI ID reused during R");
            it->issued=true;
            reads.push_back({std::get<1>(ar),0,cycle+latency,std::get<0>(ar)});++ars;
        }
        if(held&&d.get_io$$axi$$r$$ready()) {
            auto it=std::find_if(reads.begin(),reads.end(),[&](const auto& r){return r.id==held->id;});
            need(it!=reads.end()&&it->beat==held->beat,"R lost or changed owner");
            if(++it->beat==8) {
                auto owner=std::find_if(owners.begin(),owners.end(),[&](const auto& r){
                    return r.address-base==held->address;});
                need(owner!=owners.end(),"R completion without owner");owner->received=true;
                reads.erase(it);
            }
            ++rbeats;held.reset();
        }
        bool dv=d.get_io$$tl$$d$$valid();
        auto out=std::make_tuple(uint64_t(d.get_io$$tl$$d$$bits$$data()),
            unsigned(d.get_io$$tl$$d$$bits$$source()),unsigned(d.get_io$$tl$$d$$bits$$size()));
        if(heldD) need(dv&&out==*heldD,"D payload changed under backpressure");
        heldD=dv&&!dr?std::optional{out}:std::nullopt;
        if(dv&&dr) {
            need(!owners.empty()&&owners.front().received,"D exposed before complete R burst");
            auto& owner=owners.front();
            need(std::get<0>(out)==(pattern(owner.address+uint64_t(owner.beat)*8)^(inject?1ULL:0ULL))&&
                 std::get<1>(out)==owner.source&&std::get<2>(out)==6&&
                 d.get_io$$tl$$d$$bits$$opcode()==1&&!d.get_io$$tl$$d$$bits$$denied()&&
                 !d.get_io$$tl$$d$$bits$$corrupt(),"independent bridge bandwidth data/metadata oracle");
            ++dbeats;
            if(++owner.beat==8){live[owner.source]=false;owners.pop_front();++completed;}
        }
        elapsed=cycle-first+1;
    }
    need(completed==total&&accepted==total&&ars==total&&rbeats==2048&&dbeats==2048&&
         reads.empty()&&owners.empty()&&!held&&peak==2,"bandwidth drain/count/two-owner oracle");
    std::cout<<"I1_BRIDGE_BANDWIDTH_PASS {\"latency\":"<<latency<<",\"backpressure\":"<<int(stalls)
        <<",\"above4G\":"<<int(high)<<",\"bytes\":"<<bytes<<",\"cycles\":"<<elapsed
        <<",\"rbeats\":"<<rbeats<<",\"dbeats\":"<<dbeats<<",\"slots\":2,\"write_credits\":1"
        <<",\"read_bytes_per_cycle\":"<<double(bytes)/elapsed
        <<",\"r_channel_utilization\":"<<double(rbeats)/elapsed<<"}\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
