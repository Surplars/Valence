#include "TranslatedFrozenProofGsim.h"
#include "pending_store_proof_reference.h"
#include <algorithm>
#include <cstring>
#include <deque>
#include <iostream>
#include <memory>
#include <optional>
#include <tuple>
#include <type_traits>
using pending_store_reference::require;
constexpr uint64_t RAM = 0x180010000ULL, VA = 0x40000000ULL;
struct Op {
    uint64_t id=0, va=0, pa=0, data=0, proofVa=0, proofPa=0, tag=0;
    unsigned size=3, mask=255, proofSize=3, proofMask=255, index=0, epoch=0, pbmt=0;
    bool frozen=true, virt=true, write=true, atomic=false, uncached=false, prechecked=false;
    bool fault=false, pageFault=false, physicalError=false, certificate=false, physical=false, response=false;
    uint64_t readData() const { return 0xA500000000000000ULL ^ (id*0x9E3779B97F4A7C15ULL); }
};
using Ptr=std::shared_ptr<Op>;
class Bench {
    STranslatedFrozenProofGsim d;
    std::deque<Ptr> pending, owners;
    std::deque<std::pair<uint64_t,Ptr>> replies;
    std::optional<std::pair<uint64_t,Ptr>> translation;
    using Payload=std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool,bool,bool>;
    std::optional<Payload> heldPhysical;
    unsigned nextId=1;
public:
    uint64_t cycle=0, blockUntil=0;
    unsigned epoch=0, pmpCfg=0x1f;
    bool flush=false, invalidPoison=true, mutateToken=false, mutateData=false;
    unsigned sent=0, responses=0, physical=0, certificates=0, translations=0, stalls=0, holds=0, faultResponses=0;
    unsigned sizeCoverage=0, concurrent=0;
    Bench() {
        static_assert(std::is_trivially_copyable_v<STranslatedFrozenProofGsim>);
        std::memset(&d,0,sizeof(d)); d.LOG_START=1; d.activateAll();
        drive();d.set_reset(1);d.step();d.resetAll();d.step();d.resetAll();d.set_reset(0);
        for(unsigned i=0;i<8;++i)tick();
    }
    Ptr op(unsigned size=3, bool frozen=true, bool write=true, bool virt=true) {
        auto x=std::make_shared<Op>(); x->id=nextId++;x->size=x->proofSize=size;
        const uint64_t offset=(x->id*16+(size==0?3:size==1?2:size==2?4:0))&0xfff;
        x->va=VA+offset;x->pa=RAM+offset;x->proofVa=x->va;x->proofPa=x->pa;
        x->mask=x->proofMask=((1u<<(1u<<size))-1)<<(offset&7);
        x->tag=0x8000000100000000ULL+x->id;x->index=x->id%16;x->epoch=epoch;
        x->data=0x8877665544332211ULL^x->id;x->frozen=frozen;x->write=write;x->virt=virt;
        if(!virt)x->va=x->pa;
        return x;
    }
    void add(Ptr x){pending.push_back(x);}
    void drive() {
        Op empty; const Op&r=pending.empty()?empty:*pending.front(); const bool valid=!pending.empty();
        d.set_io$$upstream$$request$$valid(valid);
        d.set_io$$upstream$$request$$bits$$address(r.va);d.set_io$$upstream$$request$$bits$$data(r.data);
        d.set_io$$upstream$$request$$bits$$size(r.size);d.set_io$$upstream$$request$$bits$$mask(r.mask);
        d.set_io$$upstream$$request$$bits$$write(r.write);d.set_io$$upstream$$request$$bits$$atomic(r.atomic);
        d.set_io$$upstream$$request$$bits$$atomicOp(0);d.set_io$$upstream$$request$$bits$$virtualized(r.virt);
        d.set_io$$upstream$$request$$bits$$uncached(r.uncached);d.set_io$$upstream$$request$$bits$$precheckedLoad(r.prechecked);
        d.set_io$$upstream$$request$$bits$$translationEpoch(r.epoch);d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$upstream$$response$$ready(cycle%7!=4);
        const bool origin=valid&&r.write&&r.virt&&!r.atomic&&!r.uncached&&!r.prechecked;
        d.set_io$$origin$$valid(origin);d.set_io$$origin$$bits$$token$$index(origin?r.index:15);
        d.set_io$$origin$$bits$$token$$tag(origin?r.tag:UINT64_MAX);d.set_io$$origin$$bits$$epoch(origin?r.epoch:UINT32_MAX);
        const bool frozen=valid&&r.frozen;d.set_io$$frozen$$valid(frozen);
        d.set_io$$frozen$$bits$$address(frozen?r.proofVa:(invalidPoison?UINT64_MAX:0));
        d.set_io$$frozen$$bits$$physicalAddress(frozen?r.proofPa:(invalidPoison?UINT64_MAX:0));
        d.set_io$$frozen$$bits$$size(frozen?r.proofSize:7);d.set_io$$frozen$$bits$$mask(frozen?r.proofMask:0x55);
        d.set_io$$physical$$request$$ready(cycle>=blockUntil&&cycle%5!=3);
        const bool rv=!replies.empty()&&replies.front().first<=cycle;
        d.set_io$$physical$$response$$valid(rv);
        d.set_io$$physical$$response$$bits$$data(rv?replies.front().second->readData()^(mutateData&&!replies.front().second->write?1:0):UINT64_MAX);
        d.set_io$$physical$$response$$bits$$error(rv&&replies.front().second->physicalError);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        d.set_io$$translation$$request$$ready(!translation&&cycle%4!=3);
        const bool tv=translation&&translation->first<=cycle;
        d.set_io$$translation$$response$$valid(tv);
        d.set_io$$translation$$response$$bits$$physicalAddress(tv?translation->second->pa:UINT64_MAX);
        d.set_io$$translation$$response$$bits$$pageFault(tv&&translation->second->pageFault);
        d.set_io$$translation$$response$$bits$$accessFault(0);
        d.set_io$$translation$$response$$bits$$level(0);
        d.set_io$$translation$$response$$bits$$napot(0);
        d.set_io$$translation$$response$$bits$$global(0);
        d.set_io$$translation$$response$$bits$$pbmt(tv?translation->second->pbmt:3);
        d.set_io$$context$$satp((8ULL<<60)|0x81000);d.set_io$$context$$dataPrivilege(1);
        d.set_io$$context$$sum(0);d.set_io$$context$$mxr(0);
        d.set_io$$pmpCfg(pmpCfg);d.set_io$$flush(flush);
    }
    void tick() {
        const bool rv=!replies.empty()&&replies.front().first<=cycle;
        const bool tv=translation&&translation->first<=cycle;
        const bool tr=!translation&&cycle%4!=3;
        const Ptr offeredReply=rv?replies.front().second:nullptr;
        drive();d.step();epoch=d.get_io$$epoch();
        if(!pending.empty()) {
            if(d.get_io$$upstream$$request$$ready()){owners.push_back(pending.front());pending.pop_front();++sent;}
            else ++stalls;
        }
        concurrent=std::max(concurrent,unsigned(owners.size()));
        if(tv&&d.get_io$$translation$$response$$ready())translation.reset();
        if(d.get_io$$translation$$request$$valid()&&tr) {
            require(!translation,"duplicate delayed translation");
            uint64_t address=d.get_io$$translation$$request$$bits$$virtualAddress();
            auto it=std::find_if(owners.begin(),owners.end(),[&](auto x){return x->va==address&&!x->frozen&&x->virt&&!x->prechecked;});
            require(it!=owners.end(),"frozen request retranslated or delayed-walk owner lost");
            require(d.get_io$$translation$$request$$bits$$access()==((*it)->write?1:0),"translation access mismatch");
            translation=std::make_pair(cycle+7+(*it)->id%3,*it);++translations;
        }
        if(d.get_io$$checked$$valid()) {
            const uint64_t tag=d.get_io$$checked$$bits$$origin$$token$$tag();
            auto it=std::find_if(owners.begin(),owners.end(),[&](auto x){return x->tag==tag;});
            require(it!=owners.end(),"independent original owner missing at certificate");auto x=*it;
            require(!x->fault&&!x->certificate&&x->write&&x->virt&&!x->uncached&&!x->pbmt,"unexpected or duplicate certificate");
            require(tag==(x->tag^(mutateToken?(1ULL<<63):0))&&
                d.get_io$$checked$$bits$$origin$$token$$index()==x->index&&
                d.get_io$$checked$$bits$$origin$$epoch()==x->epoch&&
                d.get_io$$checked$$bits$$virtualAddress()==x->va&&
                d.get_io$$checked$$bits$$physicalAddress()==x->pa&&
                d.get_io$$checked$$bits$$size()==x->size&&d.get_io$$checked$$bits$$mask()==x->mask,
                "independent original full-tuple certificate mismatch");
            x->certificate=true;++certificates;
        }
        const bool pv=d.get_io$$physical$$request$$valid();
        if(pv) {
            Payload now{d.get_io$$physical$$request$$bits$$address(),d.get_io$$physical$$request$$bits$$data(),
                d.get_io$$physical$$request$$bits$$size(),d.get_io$$physical$$request$$bits$$mask(),
                bool(d.get_io$$physical$$request$$bits$$write()),bool(d.get_io$$physical$$request$$bits$$atomic()),
                bool(d.get_io$$physical$$request$$bits$$uncached())};
            if(heldPhysical)require(now==*heldPhysical,"held physical request changed");
            const bool ready=cycle>=blockUntil&&cycle%5!=3;
            heldPhysical=ready?std::nullopt:std::optional{now};holds+=!ready;
            if(ready) {
                auto it=std::find_if(owners.begin(),owners.end(),[](auto x){return !x->fault&&!x->physical;});
                require(it!=owners.end(),"fault placeholder or duplicate request reached physical memory");auto x=*it;
                require(now==Payload{x->pa,x->data,x->size,x->mask,x->write,x->atomic,x->uncached||x->pbmt!=0},
                    "independent original physical request mismatch");
                require(!d.get_io$$physical$$request$$bits$$virtualized()&&!d.get_io$$physical$$request$$bits$$precheckedLoad()&&
                    !d.get_io$$physical$$request$$bits$$translationEpoch(),"private authorization escaped physical boundary");
                if(x->frozen)require(x->certificate,"frozen write lacks prior checked certificate");
                x->physical=true;replies.emplace_back(cycle+13+x->id%5,x);++physical;sizeCoverage|=1u<<x->size;
            }
        }else require(!heldPhysical,"held physical valid withdrawn");
        if(rv&&d.get_io$$physical$$response$$ready()){replies.front().second->response=true;replies.pop_front();}
        if(d.get_io$$upstream$$response$$valid()) {
            require(!owners.empty(),"duplicate or ownerless ordered response");auto x=owners.front();
            require(x->fault||(x->physical&&(x->response||offeredReply==x)),"early response before physical completion");
            require(bool(d.get_io$$upstream$$response$$bits$$error())==(x->fault||x->physicalError)&&
                bool(d.get_io$$upstream$$response$$bits$$pageFault())==x->pageFault,"fault placeholder response order/class mismatch");
            if(x->fault){require(!x->physical&&!x->certificate,"fault emitted physical request or certificate");
                require(d.get_io$$upstream$$response$$bits$$data()==0,"fault placeholder data changed");}
            else require(d.get_io$$upstream$$response$$bits$$data()==x->readData(),"independent original response data mismatch");
            if(cycle%7!=4){faultResponses+=x->fault;++responses;owners.pop_front();}
        }
        ++cycle;
    }
    void drain() {
        for(unsigned i=0;i<10000&&(!pending.empty()||!owners.empty());++i)tick();
        require(pending.empty()&&owners.empty()&&replies.empty()&&!translation,"ordered fixture failed to drain");
        for(unsigned i=0;i<5;++i)tick();require(d.get_io$$idle(),"adapter did not return idle");
    }
    void context(bool doFlush,unsigned cfg=0x1f) {
        require(pending.empty()&&owners.empty(),"positive context change violates original drain contract");
        flush=doFlush;pmpCfg=cfg;tick();flush=false;for(unsigned i=0;i<8;++i)tick();
    }
    void positive() {
        blockUntil=cycle+85;
        for(unsigned i=0;i<48;++i){auto x=op(i%4);if(i%9==3){x->epoch--;x->fault=true;}if(i%13==4)x->physicalError=true;add(x);}
        drain();require(stalls&&holds&&concurrent>=12&&sizeCoverage==15,"full/FIFO hold/all-size coverage missing");
        std::cout<<"COMPACT_CASE full_fifo_sizes_high_pa mixed_ordered_faults concurrent="<<concurrent<<" stalls="<<stalls<<" holds="<<holds<<'\n';
        unsigned oldTranslations=translations;
        for(unsigned i=0;i<32;++i){auto x=op(i%4,i%4==0,i%3!=0,i%5!=0);
            if(!x->virt)x->frozen=false;
            if(x->frozen)x->write=true;
            if(!x->frozen&&x->virt&&i%11==2){x->fault=x->pageFault=true;}
            if(!x->frozen&&x->virt&&i%7==3)x->pbmt=1;
            add(x);}
        drain();require(translations>oldTranslations,"mixed delayed walk was not exercised");
        std::cout<<"COMPACT_CASE nonfrozen_delayed_walk_physical_identity_invalid_payload_poison translations="<<translations<<'\n';
        for(unsigned size=0;size<4;++size){auto x=op(size,false,false,false);x->prechecked=true;add(x);}
        auto noncanonical=op();noncanonical->va|=1ULL<<39;noncanonical->proofVa=noncanonical->va;
        noncanonical->fault=true;add(noncanonical);add(op());drain();
        std::cout<<"COMPACT_CASE prechecked_loads_noncanonical_frozen_fault\n";
        auto stale=op();context(true);stale->fault=true;add(stale);drain();
        context(false,0x19);auto denied=op();denied->fault=true;add(denied);drain();
        context(false,0x1f);add(op());drain();
        std::cout<<"COMPACT_CASE flush_stale_epoch_pmp_denial_legal_drains\n";
        require(sent==responses&&physical+faultResponses==responses,"final owner conservation mismatch");
        std::cout<<"COMPACT_PAIR_PASS requests="<<sent<<" responses="<<responses<<" physical="<<physical
            <<" faults="<<faultResponses<<" certificates="<<certificates<<" translations="<<translations<<" cycles="<<cycle<<'\n';
    }
    void malformed(const std::string&mode) {
        auto x=op();
        if(mode.rfind("--size",0)==0)x->proofSize=unsigned(mode.back()-'0');
        else if(mode=="--mask")x->proofMask^=1;
        else if(mode=="--va")x->proofVa+=8;
        else if(mode=="--offset")x->proofPa+=8;
        else if(mode=="--pa-high")x->proofPa^=1ULL<<48;
        else if(mode=="--pa-range")x->pa=x->proofPa=RAM+65536+(x->va&4095);
        else if(mode=="--unaligned")x->va=x->proofVa=VA+1,x->pa=x->proofPa=RAM+1;
        else if(mode=="--request-size")x->size=2;
        else if(mode=="--atomic")x->atomic=true;
        else if(mode=="--flush-live"||mode=="--pmp-live"){
            blockUntil=cycle+100;for(unsigned i=0;i<14;++i)add(op());for(unsigned i=0;i<25;++i)tick();
            if(mode=="--flush-live")flush=true;else pmpCfg=0x19;tick();
            throw std::runtime_error("expected live-context protocol assertion missing");
        }else throw std::runtime_error("unknown malformed mode");
        add(x);drain();throw std::runtime_error("expected malformed protocol assertion missing");
    }
};
int main(int argc,char**argv){try{std::cout.setf(std::ios::unitbuf);Bench b;std::string mode=argc>1?argv[1]:"";
    if(mode=="--mutate-token")b.mutateToken=true;
    else if(mode=="--mutate-data")b.mutateData=true;
    else if(!mode.empty()){b.malformed(mode);return 2;}
    b.positive();return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
