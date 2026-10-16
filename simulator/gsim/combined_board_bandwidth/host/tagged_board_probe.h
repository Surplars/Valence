#pragma once
#ifndef TAGGED_STORE_RETURNS
#define TAGGED_STORE_RETURNS 0
#endif
#include "tagged_board_oracle.h"
#include <iostream>
#if TAGGED_STORE_RETURNS
// These scalar methods are emitted only by the companion test-only wrapper
// patch. No generated offsets or temporary node suffixes are assumed here.
#define TR(x) d.get_cpuTagged$$##x()
namespace tagged_board {
struct Probe {
    Ledger ledger;
    unsigned requestHandle=0,replyHandle=0;
    unsigned mode=0,bytes=65536;
    static Token token(uint64_t index,uint64_t tag){return {unsigned(index),tag};}
    uint64_t physical(uint64_t va) const {
        if(mode&&va>=0x40000000ULL&&va<0x40000000ULL+bytes)return 0x80400000ULL+(va-0x40000000ULL);
        if(mode&&va>=0x41000000ULL&&va<0x41000000ULL+bytes)return 0x81400000ULL+(va-0x41000000ULL);
        return va;
    }
    template<class D> void sample(D &d,uint64_t cycle) {
        (void)cycle;
        require(d.get_backendSlotCount()==4,"tagged board changed LSU geometry");
        if(TR(fpEpoch))ledger.fpEpoch(token(TR(fpIndex),TR(fpTag)));
        else if(ledger.fp)ledger.fpRelease();
        const auto raw=d.get_dataPathEvents();
        std::array<CacheRow,2> rows{};
        const unsigned ownedMask=d.get_cpuSupplyPrefetch$$responseOwnedMask();
        const unsigned completeMask=d.get_cpuSupplyPrefetch$$responseCompleteMask();
        rows[0].owned=ownedMask&1;rows[1].owned=ownedMask&2;
        if(rows[0].owned)rows[0]={true,bool(completeMask&1),unsigned(TR(cacheHandle0)),unsigned(TR(cacheKind0))};
        if(rows[1].owned)rows[1]={true,bool(completeMask&2),unsigned(TR(cacheHandle1)),unsigned(TR(cacheKind1))};
        ledger.rows(rows);
#define SLOT_CHECK(n) {const bool live=TR(slot##n##$$live); \
        require(bool(ledger.slots[n])==live,"LSU live reservation vanished or appeared without start/release"); \
        if(live){auto t=token(TR(slot##n##$$index),TR(slot##n##$$tag));ledger.slot(n,t);if(TR(slot##n##$$cancel))ledger.cancel(n,t);}}
        SLOT_CHECK(0);SLOT_CHECK(1);SLOT_CHECK(2);SLOT_CHECK(3);
#undef SLOT_CHECK
        if(TR(sbLocal))ledger.local(TR(sbOriginHandle),TR(sbLocalWrite));
        const bool cacheValid=TR(cacheReply$$valid);
        if(cacheValid)ledger.cacheOffer({unsigned(TR(cacheReply$$handle)),unsigned(TR(cacheReply$$flags)),TR(cacheReply$$data)},
            true,TR(cacheReply$$ready),TR(cacheSelected),rows,TR(cacheOldestHit));
        else ledger.cacheOffer({},false,false,0,rows,false);
        const bool physicalFire=TR(physicalReply$$valid)&&TR(physicalReply$$ready);
        require(physicalFire==bool(raw&(1ULL<<21)),"legacy/handle physical reply fire aliases differ");
        if(physicalFire){replyHandle=TR(physicalReply$$handle);ledger.physicalReply({replyHandle,unsigned(TR(physicalReply$$flags)),TR(physicalReply$$data)});}
        if(TR(integerReply$$valid)&&TR(integerReply$$ready))
            ledger.integerReply({unsigned(TR(integerReply$$handle)),unsigned(TR(integerReply$$flags)),TR(integerReply$$data)});
        if(TR(fpEpoch)&&TR(backendReply$$valid)&&TR(backendReply$$ready))
            ledger.fpReply({unsigned(TR(backendReply$$handle)),unsigned(TR(backendReply$$flags)),TR(backendReply$$data)});
        if(TR(fpComplete))ledger.fpComplete(token(TR(fpCompleteIndex),TR(fpCompleteTag)),TR(fpTval),TR(fpException),TR(fpCause));
        if(TR(sbDrainReply))ledger.storeReply({unsigned(TR(sbReply$$handle)),unsigned(TR(sbReply$$flags)),TR(sbReply$$data)});
#define SLOT_END(n) {const bool complete=TR(slot##n##$$complete),discard=TR(slot##n##$$discard),fast=TR(slot##n##$$fastLoad); \
        if(complete||discard||fast) { \
            auto t=token(TR(slot##n##$$index),TR(slot##n##$$tag)); \
            require(!fast,"COPY board changed fast-load-retire setting"); \
            if(complete)require(token(TR(slot##n##$$completeIndex),TR(slot##n##$$completeTag))==t,"completion high/full token changed"); \
            if(discard)ledger.complete(n,t,ledger.slot(n,t).op.va,false,0,true); \
            else ledger.complete(n,t,TR(slot##n##$$tval),TR(slot##n##$$exception),TR(slot##n##$$cause)); \
            ledger.release(n,t);}}
        SLOT_END(0);SLOT_END(1);SLOT_END(2);SLOT_END(3);
#undef SLOT_END
        if(TR(startValid)){
            const unsigned flags=TR(startFlags);Operation op;
            op.token=token(d.get_backendStartIndex(),d.get_backendStartTag());op.va=TR(startVa);op.pa=physical(op.va);
            op.data=TR(startData);op.size=TR(startSize);op.write=flags&1;op.atomic=flags&2;
            op.virtualized=flags&4;op.prechecked=flags&8;op.frozen=flags&16;
            if(op.prechecked)require(TR(startPa)==op.pa,"prechecked PA disagrees with independent fixed guest translation");
            ledger.start(TR(startSlot),op);
        }
        if(TR(queued$$valid)&&TR(queued$$ready))ledger.reserve(TR(queued$$handle),token(d.get_backendRequestIndex(),d.get_backendRequestTag()),
            TR(queued$$address),TR(queued$$data),TR(queued$$write));
        if(TR(sbEnqueue)){
            Token origin;
            if(TR(sbFast)){origin=token(d.get_backendHeadIndex(),d.get_backendHeadTag());
                require(origin==token(d.get_backendQueueHeadIndex(),d.get_backendQueueHeadTag()),"SB fast enqueue head/ROB full-token disagreement");}
            else {const auto &x=ledger.owner(TR(sbOriginHandle));origin=x.op.token;
                require(x.op.pa==TR(sbAddress)&&x.op.data==TR(sbData)&&x.op.write,"SB enqueue lost original accepted integer owner");}
            ledger.enqueueStore(4+TR(sbSlot),origin,TR(sbAddress),TR(sbData),TR(sbSize));
        }
        if(TR(fpEpoch)&&TR(backendRequest$$valid)&&TR(backendRequest$$ready))
            ledger.fpRequest(token(TR(fpIndex),TR(fpTag)),TR(backendRequest$$address),physical(TR(backendRequest$$address)),
                TR(backendRequest$$data),TR(backendRequest$$write),TR(backendRequest$$size));
        const bool requestFire=TR(physical$$valid)&&TR(physical$$ready);
        require(requestFire==bool(raw&(1ULL<<19)),"legacy/handle physical request fire aliases differ");
        if(requestFire){requestHandle=TR(physical$$handle);ledger.physicalRequest(requestHandle,TR(physical$$address),TR(physical$$data),
            TR(physical$$write),TR(physical$$size),TR(physical$$ordinary));}
        if(TR(cache$$valid)&&TR(cache$$ready)){
            const unsigned h=TR(cache$$handle);require(ledger.transport.contains(h),"cache unknown physical handle");
            if(TR(cachePostedIntent))ledger.transport.at(h).ordinary=false;
            ledger.cacheRequest(h,d.get_cpuSupplyPrefetch$$responseTailTicket(),TR(cache$$address),TR(cache$$data),TR(cache$$write),TR(cacheStoreWrite));
        }
    }
    void finish() const {ledger.finish();}
    void report() const {
        std::cout<<"TAGGED_RETURN_PASS accepted="<<ledger.reservations<<" physical="<<ledger.physicalAccepted
            <<" physical_replies="<<ledger.physicalReplied<<" cache_replies="<<ledger.cacheReplied
            <<" bypassed_stores="<<ledger.bypassedStores<<" complete="<<ledger.completions
            <<" cancelled_drains="<<ledger.cancelledDrains<<" local_replies="<<ledger.localReplies
            <<" sb_accepted="<<ledger.sbAccepted<<" sb_replies="<<ledger.sbReplied
            <<" fp_epochs="<<ledger.fpStarts<<" fp_path="<<(ledger.fpStarts?"OBSERVED":"NOT_EXERCISED")<<" namespace=7 handle_bits=3 full_token_bits=68\n";
    }
};
}
#undef TR
#endif
