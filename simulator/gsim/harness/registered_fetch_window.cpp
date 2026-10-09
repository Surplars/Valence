#include "RegisteredFetchWindowGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#ifndef WINDOW_CAPACITY
#define WINDOW_CAPACITY 3
#endif
#ifndef WINDOW_PREVIOUS_PACKET
#define WINDOW_PREVIOUS_PACKET 0
#endif
static_assert(WINDOW_CAPACITY == 3 || WINDOW_CAPACITY == 5);
struct Packet { bool valid=false; uint64_t data=0; unsigned access=0,page=0; };
using Rows = std::array<Packet,5>;
// A time-indexed map of literal, modulo-64-bit byte addresses. This oracle does
// not model the DUT's regions, compressed offsets, key matching, or mux tree.
struct Snapshot {
    uint64_t base=0;
    unsigned context=0;
    bool killed=false;
    std::map<uint64_t,Packet> packets;
};
static void check(bool ok,const std::string& why) {
    if(!ok) throw std::runtime_error("fetch window independent oracle mismatch: "+why);
}
static bool samePayload(const Packet& a,const Packet& b) {
    return a.data==b.data && a.access==b.access && a.page==b.page;
}
int main(int argc,char **argv) { try {
    std::string negative;
    if(argc==2) {
        const std::string_view option(argv[1]);
        check(option.starts_with("--inject-"),"unknown option");
        negative=option.substr(9);
        check(negative=="mismatch" || negative=="lost-tag" || negative=="context" ||
              negative=="access-fault" || negative=="page-fault" || negative=="invalidation" ||
              negative=="priority" || negative=="capture","unknown negative control");
    } else check(argc==1,"unexpected arguments");
    SRegisteredFetchWindowGsim d;
    std::mt19937_64 random(0x76ab3910);
    std::vector<Snapshot> timeline(2);
    unsigned checked=0,valid=0,streams=0,cycles=0,historyHits=0,priorityHits=0;
    unsigned historyInvalidations=0,historyCrossings=0,alignmentChecks=0,contextMask=0;
    unsigned accessMask=0,pageMask=0,overwriteChecks=0,tailChecks=0,resetChecks=0;
    bool injected=false;
    auto drive = [&](uint64_t queryBase,unsigned queryContext,uint64_t readBase,unsigned readContext,
                     const Rows& rows,bool invalidate,unsigned offset=0) {
        d.set_io$$queryBase(queryBase); d.set_io$$readBase(readBase);
        d.set_io$$queryContext(queryContext); d.set_io$$readContext(readContext);
        d.set_io$$invalidate(invalidate); d.set_io$$pcOffset(offset);
#define QUERY(n) d.set_io$$query##n##$$valid(rows[n].valid); \
        d.set_io$$query##n##$$data(rows[n].data); d.set_io$$query##n##$$access(rows[n].access); \
        d.set_io$$query##n##$$page(rows[n].page)
        QUERY(0); QUERY(1); QUERY(2); QUERY(3); QUERY(4);
#undef QUERY
    };
    auto capture = [&](uint64_t base,unsigned context,const Rows& rows,bool killed) {
        Snapshot next{base,context,killed,{}};
        for(unsigned row=0;row<WINDOW_CAPACITY;++row) {
            Packet packet=rows[row]; packet.valid&=!killed;
            next.packets.emplace(base+uint64_t{8}*row,packet);
        }
        timeline.push_back(next);
    };
    Rows empty{};
    drive(0,0,0,0,empty,false); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    auto tick = [&](uint64_t queryBase,unsigned queryContext,uint64_t readBase,unsigned readContext,
                    const Rows& rows,bool invalidate,bool streaming=false,unsigned offset=0,
                    const char *scenario="general") {
        drive(queryBase,queryContext,readBase,readContext,rows,invalidate,offset); d.step();
        Rows got{};
#define PACKET(n) got[n]={bool(d.get_io$$packet##n##$$valid()),d.get_io$$packet##n##$$data(), \
        unsigned(d.get_io$$packet##n##$$access()),unsigned(d.get_io$$packet##n##$$page())}
        PACKET(0); PACKET(1); PACKET(2);
#undef PACKET
        const Snapshot& primary=timeline.back();
        const Snapshot& older=timeline[timeline.size()-2];
        Packet previous{};
        const auto oldRow0=older.packets.find(older.base);
        if(oldRow0!=older.packets.end()) previous=oldRow0->second;
        // The last edge copies OLD row0, even when the base stays unchanged or
        // the row is absent. Invalidation at that edge also kills its validity.
        previous.valid&=!primary.killed;
        const bool historyAddress=older.base==readBase && older.context==readContext;
        const bool historyMatch=WINDOW_PREVIOUS_PACKET && previous.valid && historyAddress;
        bool selectedHistory=false;
        for(unsigned packet=0;packet<3;++packet) {
            Packet expected{},mainPacket{};
            const auto hit=primary.packets.find(readBase+uint64_t{8}*packet);
            if(primary.context==readContext && hit!=primary.packets.end()) mainPacket=hit->second;
            expected=mainPacket;
            if(packet==0 && !mainPacket.valid && historyMatch) {
                expected=previous; selectedHistory=true;
                if(!invalidate) {
                    ++historyHits; contextMask|=1U<<readContext;
                    accessMask|=1U<<expected.access; pageMask|=1U<<expected.page;
                } else ++historyInvalidations;
            }
            if(packet==0 && mainPacket.valid && historyMatch && !samePayload(mainPacket,previous))
                ++priorityHits;
            const bool rawPresent=expected.valid;
            expected.valid&=!invalidate;
            // Deliberately corrupt an observed output only at the relevant
            // witness. Each negative is a separate process and must be rejected.
            bool mutate=false;
            if(!injected && packet==0) {
                if(negative=="mismatch" && expected.valid) { got[0].data^=1; mutate=true; }
                if(negative=="lost-tag" && WINDOW_PREVIOUS_PACKET && previous.valid && !mainPacket.valid &&
                   older.context==readContext && older.base!=readBase &&
                   (older.base&63)==(readBase&63) && !invalidate) {
                    got[0]=previous; mutate=true;
                }
                if(negative=="context" && WINDOW_PREVIOUS_PACKET && previous.valid && !mainPacket.valid &&
                   older.base==readBase && older.context!=readContext && !invalidate) {
                    got[0]=previous; mutate=true;
                }
                if(negative=="access-fault" && selectedHistory && expected.valid) {
                    got[0].access^=2; mutate=true;
                }
                if(negative=="page-fault" && selectedHistory && expected.valid) {
                    got[0].page^=1; mutate=true;
                }
                if(negative=="invalidation" && selectedHistory && invalidate) {
                    got[0].valid=true; mutate=true;
                }
                if(negative=="priority" && mainPacket.valid && historyMatch &&
                   !samePayload(mainPacket,previous) && !invalidate) {
                    got[0]=previous; mutate=true;
                }
                if(negative=="capture" && selectedHistory && expected.valid &&
                   !samePayload(rows[0],previous)) {
                    got[0]=rows[0]; mutate=true;
                }
            }
            injected|=mutate;
            const std::string where=std::string(scenario)+" cycle="+std::to_string(cycles)+
                " packet="+std::to_string(packet)+(mutate?" negative="+negative:"");
            check(got[packet].valid==expected.valid,"address/context/invalidate validity "+where);
            // Miss payload is deliberately unspecified. A raw-authorized packet
            // stays exact even when invalidate suppresses its output validity.
            if(rawPresent) check(samePayload(got[packet],expected),"payload and both word faults "+where);
            valid+=expected.valid;
            if(streaming && packet<(WINDOW_CAPACITY==3?2:3))
                check(got[packet].valid,"cached mixed-width stream acquired a bubble "+where);
            ++checked;
        }
        // Byte/halfword decode is independent of the hardware alignment helper.
        // Invalid-packet bits are unconstrained by the window, so decode those
        // observed bits while separately proving packet validity and hit data.
        const std::array<uint32_t,4> instructions={uint32_t(d.get_io$$instruction0()),
            uint32_t(d.get_io$$instruction1()),uint32_t(d.get_io$$instruction2()),uint32_t(d.get_io$$instruction3())};
        const std::array<unsigned,4> faults={unsigned(d.get_io$$fault0()),unsigned(d.get_io$$fault1()),
            unsigned(d.get_io$$fault2()),unsigned(d.get_io$$fault3())};
        auto half=[&](unsigned at) { return uint16_t(got[at/8].data>>(8*(at%8))); };
        unsigned at=offset,alignedValid=0,alignedAccess=0,alignedPage=0;
        for(unsigned lane=0;lane<(WINDOW_CAPACITY==3?2:4);++lane) {
            const uint16_t first=half(at);
            const bool shortInstruction=(first&3)!=3;
            const unsigned next=at+2;
            const uint32_t instruction=first|(shortInstruction?0:uint32_t(half(next))<<16);
            const bool present=got[at/8].valid && (shortInstruction || got[next/8].valid);
            const bool firstAccess=(got[at/8].access>>(at%8/4))&1;
            const bool firstPage=(got[at/8].page>>(at%8/4))&1;
            const bool access=firstAccess || (!shortInstruction && ((got[next/8].access>>(next%8/4))&1));
            const bool page=firstPage || (!shortInstruction && ((got[next/8].page>>(next%8/4))&1));
            check(instructions[lane]==instruction,"mixed16/32 alignment payload");
            check(faults[lane]==(firstAccess || firstPage?at:next),"precise instruction fault offset");
            alignedValid|=unsigned(present)<<lane;
            alignedAccess|=unsigned(access)<<lane; alignedPage|=unsigned(page)<<lane;
            historyCrossings+=selectedHistory && present && !shortInstruction && at/8==0 && next/8==1;
            at+=shortInstruction?2:4; ++alignmentChecks;
        }
        check(d.get_io$$alignedValid()==alignedValid && d.get_io$$alignedAccess()==alignedAccess &&
              d.get_io$$alignedPage()==alignedPage,"mixed16/32 alignment presence/faults");
        if(streaming) ++streams;
        capture(queryBase,queryContext,rows,invalidate); ++cycles;
        return got;
    };
    auto randomRows = [&]() {
        Rows rows{};
        for(auto& row:rows) row={true,random(),unsigned(random()&3),unsigned(random()&3)};
        return rows;
    };
    // Preserve the original OFF steady stream, address-boundary sweep and
    // random sequence (including its deterministic seed and relative reads).
    uint64_t base=0xfffffffffffffff8ULL;
    for(unsigned n=0;n<256;++n) {
        const Rows rows=randomRows();
        tick(base,5,base,5,rows,false,n>0); base+=(WINDOW_CAPACITY==3?8:16);
    }
    for(uint64_t anchor : {uint64_t{0},uint64_t{0xffffffc0},uint64_t{0xffffffffffffffc0}}) {
        for(unsigned offset=0;offset<8;++offset) for(int delta=-4;delta<=5;++delta) {
            const Rows rows=randomRows(); const uint64_t address=anchor+8*offset;
            tick(address,3,timeline.back().base,3,rows,false);
            tick(address,3,address+uint64_t(8*delta),3,rows,false);
        }
    }
    for(unsigned n=0;n<6000;++n) {
        Rows rows{};
        for(auto& row:rows) row={bool(random()&1),random(),unsigned(random()&3),unsigned(random()&3)};
        const uint64_t queryBase=random()&~uint64_t{7};
        uint64_t readBase=timeline.back().base+uint64_t(8*(int(random()%11)-4));
        if(n%5==0) readBase^=uint64_t{1}<<63;
        const unsigned queryContext=random()&7;
        const unsigned readContext=n%3?timeline.back().context:unsigned(random()&7);
        tick(queryBase,queryContext,readBase,readContext,rows,n%29==0,false,(n&3)*2);
    }
    // One-cycle A -> A+8 -> A across every context, packet offset and boundary.
    // B's payload deliberately differs from A's. Both word fault bits sweep.
    for(uint64_t anchor : {uint64_t{0},uint64_t{0xffffffc0},uint64_t{0x7fffffffffffffc0},
                            uint64_t{0x8000000000000000},uint64_t{0xffffffffffffffc0}}) {
        for(unsigned context=0;context<8;++context) for(unsigned offset=0;offset<8;++offset) {
            const uint64_t a=anchor+uint64_t{8}*offset,b=a+8;
            Rows old=randomRows(),middle=randomRows(),now=randomRows();
            // A 32-bit instruction starts at byte 6; byte 8 is supplied by B.
            // Following halfwords alternate 16- and 32-bit instruction lengths.
            old[0].data=0x0093000100930001ULL;
            old[0].access=offset&3; old[0].page=(offset+context)&3;
            middle[0].data=0x0001009300011234ULL;
            tick(a,context,a,context,old,false);
            tick(b,context,b,context,middle,false);
            const Rows returned=tick(a,context,a,context,now,false,false,6,"one-cycle-return");
            check(returned[0].valid==bool(WINDOW_PREVIOUS_PACKET),"one-cycle return feature contract");
            check(returned[1].valid && returned[2].valid,"primary tail changed on history return");
            if(WINDOW_PREVIOUS_PACKET) check(samePayload(returned[0],old[0]),"old row0 snapshot was not retained");
            // Holding the middle base for a second edge replaces the shadow.
            tick(a,context,a,context,old,false);
            tick(b,context,b,context,middle,false);
            tick(b,context,b,context,middle,false);
            const Rows overwritten=tick(a,context,a,context,now,false,false,0,"two-cycle-overwrite");
            check(!overwritten[0].valid,"history incorrectly became a sticky cache"); ++overwriteChecks;
        }
    }
    // Full address equality: reject aliases differing in every tag bit, all the
    // way through bit63. Three low packet-key bits were swept above.
    for(unsigned bit=6;bit<64;++bit) {
        const uint64_t a=0x123456789abcde38ULL,b=a+8;
        const Rows old=randomRows(),middle=randomRows();
        tick(a,6,a,6,old,false); tick(b,6,b,6,middle,false);
        tick(a,6,a^(uint64_t{1}<<bit),6,old,false,false,0,"full-address-alias");
    }
    // Exhaust every unequal context pair; matching-context hits covered above.
    for(unsigned oldContext=0;oldContext<8;++oldContext) for(unsigned readContext=0;readContext<8;++readContext) {
        if(oldContext==readContext) continue;
        const uint64_t a=0xfffffff8ULL; const Rows old=randomRows(),middle=randomRows();
        tick(a,oldContext,a,oldContext,old,false); tick(a+8,readContext,a+8,readContext,middle,false);
        tick(a,readContext,a,readContext,old,false,false,0,"history-context-isolation");
    }
    for(unsigned fault=0;fault<16;++fault) {
        const uint64_t a=0x80000038ULL,b=a+8; const unsigned context=fault&7;
        Rows old=randomRows(),fresh=randomRows(),absent=randomRows();
        old[0].access=fault&3; old[0].page=fault>>2;
        fresh[0].access=(fault&3)^3; fresh[0].page=(fault>>2)^3;
        absent[0].valid=false;
        // Duplicate address/context: primary must win over older data and faults.
        tick(a,context,a,context,old,false); tick(a,context,a,context,fresh,false);
        tick(a,context,a,context,old,false,false,6,"primary-priority");
        // An absent matching primary row is a raw miss, permitting valid history.
        tick(a,context,a,context,old,false); tick(a,context,a,context,absent,false);
        tick(b,context,a,context,fresh,false,false,6,"absent-primary-fallback");
        // Conversely, absent OLD row0 must overwrite an older valid history.
        tick(a,context,a,context,old,false); tick(b,context,b,context,absent,false);
        tick(b+8,context,b+8,context,fresh,false);
        const Rows missing=tick(a,context,a,context,fresh,false,false,0,"absent-history-overwrite");
        check(!missing[0].valid,"absent old row0 resurrected older history"); ++overwriteChecks;
        // History is output0-only, even when it would match output1 or output2.
        for(unsigned packet=1;packet<3;++packet) {
            tick(a,context,a,context,old,false); tick(a+0x100,context,a+0x100,context,fresh,false);
            const Rows tail=tick(a,context,a-8*packet,context,fresh,false,false,0,"history-output0-only");
            check(!tail[packet].valid,"history incorrectly fed a later output packet"); ++tailChecks;
        }
        // Kill a current history hit without selecting different payload bits.
        tick(a,context,a,context,old,false); tick(b,context,b,context,fresh,false);
        tick(b+8,context,a,context,old,true,false,6,"invalidate-history-now");
        // The invalidating edge must not capture previously-present B as history.
        const Rows killed=tick(b+16,context,b,context,absent,false,false,0,"invalidate-history-next-edge");
        check(!killed[0].valid,"invalidating edge retained old row0 history");
        const Rows stale=tick(b+24,context,a,context,absent,false,false,0,"invalidate-no-resurrection");
        check(!stale[0].valid,"deasserted invalidation resurrected stale history");
        // Invalidate also suppresses a primary hit while leaving its bits exact.
        tick(a,context,a,context,old,false);
        tick(b,context,a,context,fresh,true,false,6,"invalidate-primary-now");
        const Rows killedPrimary=tick(b+8,context,a,context,absent,false,false,0,"invalidate-primary-next-edge");
        check(!killedPrimary[0].valid,"invalidated primary reappeared through history");
        // A single reset edge clears a populated shadow, including when reset
        // inputs would otherwise capture valid rows. Do not wait two edges.
        tick(a,context,a,context,old,false); tick(b,context,b,context,fresh,false);
        drive(a+0x100,context,a,context,old,false); d.set_reset(1); d.step(); d.set_reset(0);
        capture(a+0x100,context,old,true);
        const Rows reset=tick(a+0x108,context,b,context,fresh,false,false,0,"single-reset-edge");
        check(!reset[0].valid,"reset failed to clear history present"); ++resetChecks;
    }
    check(overwriteChecks && tailChecks && resetChecks,"directed coverage incomplete");
    if(WINDOW_PREVIOUS_PACKET) check(historyHits && priorityHits && historyInvalidations && historyCrossings &&
        contextMask==255 && accessMask==15 && pageMask==15,"history/fault/context/straddle coverage incomplete");
    if(!negative.empty() && !injected) throw std::runtime_error("negative control was not exercised: "+negative);
    std::cout<<"GSIM registered fetch window: PASS checks="<<checked<<" valid="<<valid
             <<" steadyCycles="<<streams<<" capacity="<<WINDOW_CAPACITY
             <<" previousPacket="<<WINDOW_PREVIOUS_PACKET<<" historyHits="<<historyHits
             <<" priorityHits="<<priorityHits<<" invalidatedHistoryHits="<<historyInvalidations
             <<" historyStraddles="<<historyCrossings<<" alignmentChecks="<<alignmentChecks
             <<" overwriteChecks="<<overwriteChecks<<" output0OnlyChecks="<<tailChecks<<" resetChecks="<<resetChecks
             <<" full-address wrap faults all-contexts invalidate no-resurrection\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; } }
