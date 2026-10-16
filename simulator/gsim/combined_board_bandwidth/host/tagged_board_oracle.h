#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>

// Host-owned facts only. Tokens preserve all 64 generation bits. A return tag is
// a reservation index, never a replacement for the full accepted operation.
namespace tagged_board {
inline void require(bool value, const char *why) { if (!value) throw std::runtime_error(why); }
struct Token { unsigned index=0; uint64_t tag=0; auto operator<=>(const Token&) const = default; };
struct Operation {
    Token token; uint64_t va=0,pa=0,data=0; unsigned size=3;
    bool write=false,atomic=false,virtualized=false,prechecked=false,frozen=false;
};
struct Reply { unsigned handle=0,flags=0; uint64_t data=0; auto operator<=>(const Reply&) const = default; };
struct Life {
    Operation op; unsigned slot=0; uint64_t serial=0;
    bool queued=false,returned=false,complete=false,cancelled=false,discarded=false,local=false;
    unsigned flags=0; uint64_t responseData=0;
};
struct Transport {
    Token token; uint64_t serial=0,va=0,pa=0,data=0; unsigned size=3;
    bool write=false,ordinary=false,storeHit=false,cacheAccepted=false,cacheReturned=false;
    bool physicalReturned=false; unsigned ticket=0,flags=0; uint64_t responseData=0;
};
struct CacheRow { bool owned=false,complete=false; unsigned handle=0,kind=0; };
struct Ledger {
    static constexpr unsigned integerCount=4,storeCount=2,fpHandle=6,handleCount=7;
    std::map<Token,Life> lives;
    std::array<std::optional<Token>,integerCount> slots{};
    std::map<unsigned,Token> handles;
    std::map<unsigned,Transport> transport;
    std::map<unsigned,Transport> storeOwners;
    std::array<std::optional<unsigned>,2> tickets{};
    std::deque<unsigned> physicalOrder,cacheOrder,storeOrder;
    std::optional<Reply> heldCache;
    std::optional<Life> fp;
    uint64_t fpStarts=0,fpReplies=0,fpReleases=0;
    uint64_t serial=0,starts=0,reservations=0,releases=0,physicalAccepted=0,physicalReplied=0;
    uint64_t cacheReplied=0,bypassedStores=0,completions=0,cancelledDrains=0,localReplies=0,sbAccepted=0,sbReplied=0;
    static void legal(unsigned h) { require(h<handleCount,"illegal return handle code"); }
    Life &owner(unsigned h) {
        require(h<integerCount && handles.contains(h),"unknown or stale integer return handle");
        auto &x=lives.at(handles.at(h)); require(x.slot==h,"handle no longer names its exact slot"); return x;
    }
    const Life &slot(unsigned h,Token token) const {
        require(h<integerCount && slots[h] && *slots[h]==token,"slot/full-token binding changed");
        return lives.at(token);
    }
    void start(unsigned h,Operation op) {
        require(!fp,"integer start during exclusive FP epoch");
        require(h<integerCount && !slots[h],"same-index slot reused before reply and completion/discard drain");
        require(!lives.contains(op.token),"duplicate full ROB token start");
        require(op.token.index<16,"ROB index outside unchanged 16-entry board");
        require(op.size==3&&!op.atomic,"COPY board owner size/class changed");
        Life x;x.op=op;x.slot=h;x.serial=++serial;lives.emplace(op.token,x);slots[h]=op.token;++starts;
    }
    void reserve(unsigned h,Token token,uint64_t address,uint64_t data,bool write) {
        legal(h);slot(h,token);require(lives.contains(token),"unknown/stale accepted full token");auto &x=lives.at(token);
        require(!x.queued&&!handles.contains(h),"live return handle reused at request-queue acceptance");
        require(address==(x.op.prechecked?x.op.pa:x.op.va)&&write==x.op.write&&data==(write?x.op.data:data),
            "accepted request detached from full-token VA/data/class");
        x.queued=true;handles.emplace(h,token);++reservations;
    }
    void cancel(unsigned h,Token token) {
        slot(h,token);auto &x=lives.at(token);require(!x.op.write&&!x.op.atomic,"cancelled irrevocable owner");x.cancelled=true;
    }
    void local(unsigned h,bool write) {
        auto &x=owner(h);require(!x.local&&!x.op.frozen&&x.op.write==write,"frozen/duplicate/misclassified local ACK");x.local=true;
    }
    void fpEpoch(Token token) {
        if(fp){require(fp->op.token==token,"exclusive FP full-token owner changed");return;}
        require(handles.empty()&&transport.empty()&&storeOwners.empty()&&!heldCache,"FP epoch started before integer/SB/cache drain");
        for(const auto &s:slots)require(!s,"FP epoch started with live integer slot");
        Life x;x.op.token=token;x.slot=fpHandle;x.serial=++serial;fp=x;++fpStarts;
    }
    void fpRequest(Token token,uint64_t va,uint64_t pa,uint64_t data,bool write,unsigned size) {
        require(fp&&fp->op.token==token&&!fp->queued,"FP request lost exclusive full token or repeated");
        fp->op.va=va;fp->op.pa=pa;fp->op.data=data;fp->op.write=write;fp->op.size=size;fp->queued=true;
    }
    void fpReply(Reply r) {
        require(r.handle==fpHandle&&fp&&fp->queued&&!fp->returned&&transport.contains(fpHandle),"unknown/duplicate FP reply");
        const auto &x=transport.at(fpHandle);require(x.physicalReturned&&x.token==fp->op.token&&x.serial==fp->serial&&x.flags==r.flags&&x.responseData==r.data,"FP reply detached from accepted operation");
        fp->returned=true;fp->flags=r.flags;fp->responseData=r.data;transport.erase(fpHandle);++fpReplies;
    }
    void fpComplete(Token token,uint64_t tval,bool exception,uint64_t cause) {
        require(fp&&fp->op.token==token&&!fp->complete&&(!fp->queued||fp->returned),"FP completion lost token or preceded drain");
        if(fp->queued){require(tval==fp->op.va&&exception==bool(fp->flags),"FP completion lost VA/fault");if(exception)require(cause==((fp->flags&2)?(fp->op.write?15U:13U):(fp->op.write?7U:5U)),"FP fault cause changed");}
        fp->complete=true;
    }
    void fpRelease() {require(fp&&fp->complete&&(!fp->queued||fp->returned),"FP epoch released before reply and completion");fp.reset();++fpReleases;}
    void enqueueStore(unsigned h,Token token,uint64_t pa,uint64_t data,unsigned size) {
        require(h>=integerCount&&h<fpHandle&&!storeOwners.contains(h),"SB drain slot reused before actual response");
        Transport x;x.token=token;x.serial=++serial;x.va=pa;x.pa=pa;x.data=data;x.size=size;x.write=true;
        storeOwners.emplace(h,x);storeOrder.push_back(h);++sbAccepted;
    }
    void physicalRequest(unsigned h,uint64_t pa,uint64_t data,bool write,unsigned size,bool ordinary) {
        legal(h);require(!transport.contains(h),"duplicate/live physical handle accepted");Transport x;
        if(h<integerCount) { auto &l=owner(h);require(!l.returned&&!l.local,"physical issue after local/actual return");
            require(pa==l.op.pa&&write==l.op.write&&size==l.op.size&&(!write||data==l.op.data),"physical request lost full-token VA/PA/data binding");
            x.token=l.op.token;x.serial=l.serial;x.va=l.op.va;
        } else if(h==fpHandle) {
            require(fp&&fp->queued&&!fp->returned,"unbound FP physical return domain");
            require(fp->op.pa==pa&&fp->op.data==data&&fp->op.write==write&&fp->op.size==size,"FP physical request lost VA/PA/token");
            x.token=fp->op.token;x.serial=fp->serial;x.va=fp->op.va;
        } else { require(storeOwners.contains(h),"unbound SB physical return domain");x=storeOwners.at(h);
            require(x.pa==pa&&x.data==data&&x.size==size&&write,"SB drain payload changed"); }
        x.pa=pa;x.data=data;x.write=write;x.size=size;x.ordinary=ordinary;
        transport.emplace(h,x);physicalOrder.push_back(h);++physicalAccepted;
    }
    void cacheRequest(unsigned h,unsigned ticket,uint64_t pa,uint64_t data,bool write,bool storeWrite) {
        require(ticket<2&&!tickets[ticket],"cache reused a live physical response row");
        require(transport.contains(h),"cache acceptance has no independently accepted physical owner");auto &x=transport.at(h);
        require(!x.cacheAccepted&&x.pa==pa&&x.write==write&&(!write||x.data==data),"cache request detached from physical owner");
        require(!storeWrite||write,"SRAM store-write witness names a read");
        x.cacheAccepted=true;x.ticket=ticket;x.storeHit=storeWrite;tickets[ticket]=h;cacheOrder.push_back(h);
    }
    void rows(const std::array<CacheRow,2>& rows) const {
        for(unsigned i=0;i<2;++i) {
            require(rows[i].owned==bool(tickets[i]),"cache physical row occupancy disagrees with accepted transfers");
            if(tickets[i])require(rows[i].handle==*tickets[i],"cache ticket/handle binding changed");
        }
    }
    void cacheOffer(Reply r,bool valid,bool ready,unsigned selected,const std::array<CacheRow,2>& rows,bool oldestHitPending) {
        if(heldCache)require(valid&&r==*heldCache,"held response handle/data/fault changed or valid dropped");
        if(!valid)return;
        legal(r.handle);require(selected<2&&tickets[selected]&&*tickets[selected]==r.handle&&transport.contains(r.handle),"wrong/stale cache return handle");
        auto &x=transport.at(r.handle);require(x.cacheAccepted&&!x.cacheReturned,"duplicate cache response");
        require(rows[selected].owned&&rows[selected].handle==r.handle,"offered response lost actual row identity");
        require(!cacheOrder.empty(),"cache response lacks request order");
        const bool bypass=cacheOrder.front()!=r.handle;
        if(bypass) {
            const auto &old=transport.at(cacheOrder.front());
            require(r.handle<integerCount&&x.ordinary&&x.write&&x.storeHit&&rows[selected].complete&&rows[selected].kind==0&&r.flags==0,
                "younger return is not an already-complete successful ordinary integer store hit");
            require(old.ordinary&&!old.write&&rows[old.ticket].kind==0,"store response bypassed an ordered/non-read owner");
            require(!rows[old.ticket].complete&&!oldestHitPending||bool(heldCache),"unheld younger store preempted ready oldest response");
        } else require(rows[selected].complete||oldestHitPending,"early success before a real cache result");
        if(x.write&&x.storeHit)require(rows[selected].complete||(!bypass&&oldestHitPending),"early store success without registered/oldest-hit result");
        if(!ready){heldCache=r;return;}
        heldCache.reset();x.cacheReturned=true;x.flags=r.flags;x.responseData=r.data;tickets[selected].reset();
        auto at=std::find(cacheOrder.begin(),cacheOrder.end(),r.handle);require(at!=cacheOrder.end(),"cache return absent from accepted sequence");cacheOrder.erase(at);
        ++cacheReplied;bypassedStores+=bypass;
    }
    void physicalReply(Reply r) {
        legal(r.handle);require(transport.contains(r.handle),"unknown/stale physical response handle");auto &x=transport.at(r.handle);
        require(x.cacheReturned&&!x.physicalReturned&&x.flags==r.flags&&x.responseData==r.data,"duplicate/early/changed physical response");
        auto it=std::find(physicalOrder.begin(),physicalOrder.end(),r.handle);require(it!=physicalOrder.end(),"physical response absent from accepted sequence");
        if(it!=physicalOrder.begin()) {
            require(r.handle<integerCount&&x.ordinary&&x.write&&x.storeHit&&r.flags==0,"physical read-read or ordered-domain response reordering");
            for(auto p=physicalOrder.begin();p!=it;++p){const auto &old=transport.at(*p);require(old.ordinary&&!old.write,"store passed non-read physical owner");}
        }
        physicalOrder.erase(it);x.physicalReturned=true;++physicalReplied;
    }
    void integerReply(Reply r) {
        auto &x=owner(r.handle);require(!x.returned,"duplicate integer response handle");
        if(x.local){require(r.flags==0,"local response returned an unexpected fault");++localReplies;}
        else {require(transport.contains(r.handle),"integer response lacks real physical owner");const auto &p=transport.at(r.handle);
            require(p.physicalReturned&&p.token==x.op.token&&p.serial==x.serial&&p.flags==r.flags&&p.responseData==r.data,"integer reply lost exact token/generation or arrived early");transport.erase(r.handle);}
        x.returned=true;x.flags=r.flags;x.responseData=r.data;cancelledDrains+=x.cancelled;
    }
    void storeReply(Reply r) {
        require(!storeOrder.empty()&&storeOrder.front()==r.handle&&storeOwners.contains(r.handle)&&transport.contains(r.handle),"SB return lost ordered drain owner");
        const auto &x=transport.at(r.handle);require(x.physicalReturned&&!r.flags&&x.flags==r.flags&&x.responseData==r.data,"SB early/error drain response");
        storeOrder.pop_front();storeOwners.erase(r.handle);transport.erase(r.handle);++sbReplied;
    }
    void complete(unsigned h,Token token,uint64_t tval,bool exception,uint64_t cause,bool discard=false) {
        slot(h,token);auto &x=lives.at(token);require(!x.complete&&!x.discarded,"duplicate full-token completion/discard");
        require(!x.queued||x.returned,"completion/discard before real accepted response drain");
        if(discard){require(x.cancelled,"uncancelled slot discarded");x.discarded=true;}
        else {require(tval==x.op.va,"completion lost precise original VA");
            if(x.queued){require(exception==bool(x.flags),"completion lost response exception");if(exception)require(cause==((x.flags&2)?(x.op.write?15U:13U):(x.op.write?7U:5U)),"completion fault cause detached from operation");}
            x.complete=true;++completions;}
    }
    void release(unsigned h,Token token) {
        slot(h,token);auto &x=lives.at(token);require((x.complete||x.discarded)&&(!x.queued||x.returned),"slot released before response plus completion/discard");
        if(x.queued){require(handles.at(h)==token,"full token changed at release");handles.erase(h);}slots[h].reset();++releases;
    }
    void finish() const {
        require(!fp&&fpStarts==fpReleases,"FP epoch did not drain");
        require(handles.empty()&&transport.empty()&&storeOwners.empty()&&physicalOrder.empty()&&cacheOrder.empty()&&storeOrder.empty()&&!heldCache,"tagged owners/held replies not drained");
        for(const auto &s:slots)require(!s,"LSU slot not drained");for(const auto &t:tickets)require(!t,"cache ticket not drained");
        require(starts==releases&&physicalAccepted==physicalReplied&&physicalReplied==cacheReplied&&sbAccepted==sbReplied,"tagged request/response/lifetime conservation");
    }
};
}
