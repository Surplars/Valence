#include <iostream>
#include <functional>
#include "tagged_board_oracle.h"
using namespace tagged_board;
static Operation operation(unsigned index,uint64_t tag,bool write,uint64_t pa) {
    Operation o;o.token={index,tag};o.va=pa;o.pa=pa;o.data=write?0x1234567812345678ULL:0;o.write=write;return o;
}
static void accepted(Ledger &l,unsigned h,Operation o,unsigned ticket,bool hit=false){l.start(h,o);l.reserve(h,o.token,o.va,o.data,o.write);l.physicalRequest(h,o.pa,o.data,o.write,3,true);l.cacheRequest(h,ticket,o.pa,o.data,o.write,hit);}
static void response(Ledger &l,unsigned h,unsigned ticket,std::array<CacheRow,2> rows,uint64_t data=0,unsigned flags=0){l.cacheOffer({h,flags,data},true,true,ticket,rows,false);l.physicalReply({h,flags,data});l.integerReply({h,flags,data});}
static void done(Ledger &l,unsigned h,Operation o,unsigned flags=0){l.complete(h,o.token,o.va,bool(flags),(flags&2)?(o.write?15:13):(o.write?7:5));l.release(h,o.token);}
static void positive() {
    Ledger l;auto read=operation(3,0x8000000000000001ULL,false,0x80400000);auto store=operation(4,0x4000000000000002ULL,true,0x81400000);
    accepted(l,0,read,0);accepted(l,1,store,1,true);
    std::array<CacheRow,2> rows{{{true,false,0,0},{true,true,1,0}}};l.rows(rows);
    l.cacheOffer({1,0,0},true,false,1,rows,false);
    rows[0].complete=true;l.cacheOffer({1,0,0},true,true,1,rows,false);l.physicalReply({1,0,0});l.integerReply({1,0,0});done(l,1,store);
    rows[1].owned=false;response(l,0,0,rows,0x9988);done(l,0,read);
    auto reuse=read;reuse.token.tag^=0x2000000000000000ULL;accepted(l,0,reuse,1);
    response(l,0,1,{{{false,false,0,0},{true,true,0,0}}},0x9988);done(l,0,reuse);
    auto buffered=operation(9,0x9000000000000010ULL,true,0x81400008);l.start(2,buffered);l.reserve(2,buffered.token,buffered.va,buffered.data,true);
    l.enqueueStore(4,buffered.token,buffered.pa,buffered.data,3);l.local(2,true);l.integerReply({2,0,0});done(l,2,buffered);
    // The integer owner has retired; the independent SB drain remains reserved.
    l.physicalRequest(4,buffered.pa,buffered.data,true,3,true);l.cacheRequest(4,0,buffered.pa,buffered.data,true,false);
    l.cacheOffer({4,0,0},true,true,0,{{{true,true,4,1},{false,false,0,0}}},false);l.physicalReply({4,0,0});l.storeReply({4,0,0});
    auto cancelled=operation(2,0xf000000000000012ULL,false,0x80400008);accepted(l,3,cancelled,0);l.cancel(3,cancelled.token);
    response(l,3,0,{{{true,true,3,0},{false,false,0,0}}},0x1234);l.complete(3,cancelled.token,cancelled.va,false,0,true);l.release(3,cancelled.token);
    auto errored=operation(1,0xa000000000000014ULL,false,0x80400010);accepted(l,1,errored,0);
    response(l,1,0,{{{true,true,1,0},{false,false,0,0}}},0,1);done(l,1,errored,1);
    Token fp{6,0xb000000000000001ULL};l.fpEpoch(fp);l.fpRequest(fp,0x80400018,0x80400018,0,false,3);
    l.physicalRequest(6,0x80400018,0,false,3,true);l.cacheRequest(6,0,0x80400018,0,false,false);
    l.cacheOffer({6,0,44},true,true,0,{{{true,true,6,0},{false,false,0,0}}},false);l.physicalReply({6,0,44});l.fpReply({6,0,44});l.fpComplete(fp,0x80400018,false,0);l.fpRelease();
    l.finish();require(l.bypassedStores==1&&l.cancelledDrains==1&&l.sbReplied==1&&l.fpReplies==1,"positive coverage counters missing");
}
static void negative(const std::string &name) {
    Ledger l;auto a=operation(3,0x8000000000000001ULL,false,0x80400000),b=operation(4,0x4000000000000002ULL,true,0x81400000);
    accepted(l,0,a,0);accepted(l,1,b,1,true);
    std::array<CacheRow,2> rows{{{true,false,0,0},{true,true,1,0}}};
    if(name=="wrong-handle")l.cacheOffer({2,0,0},true,true,1,rows,false);
    else if(name=="illegal-handle")l.physicalReply({7,0,0});
    else if(name=="wrong-ticket")l.cacheOffer({1,0,0},true,true,0,rows,false);
    else if(name=="early-store-success"){rows[1].complete=false;l.cacheOffer({1,0,0},true,true,1,rows,false);}
    else if(name=="false-store-write"){l.transport.at(1).storeHit=false;l.cacheOffer({1,0,0},true,true,1,rows,false);}
    else if(name=="reordered-read"){l.transport.at(1).write=false;l.cacheOffer({1,0,0},true,true,1,rows,false);}
    else if(name=="ordered-bypass"){l.transport.at(0).ordinary=false;l.cacheOffer({1,0,0},true,true,1,rows,false);}
    else if(name=="ready-oldest"){rows[0].complete=true;l.cacheOffer({1,0,0},true,true,1,rows,false);}
    else if(name=="held-handle"){l.cacheOffer({1,0,0},true,false,1,rows,false);l.cacheOffer({0,0,0},true,true,0,rows,false);}
    else if(name=="held-data"){l.cacheOffer({1,0,0},true,false,1,rows,false);l.cacheOffer({1,0,1},true,true,1,rows,false);}
    else if(name=="held-fault"){l.cacheOffer({1,0,0},true,false,1,rows,false);l.cacheOffer({1,1,0},true,true,1,rows,false);}
    else if(name=="duplicate-cache"){l.cacheOffer({1,0,0},true,true,1,rows,false);l.cacheOffer({1,0,0},true,true,1,rows,false);}
    else if(name=="early-physical")l.physicalReply({1,0,0});
    else if(name=="early-integer")l.integerReply({1,0,0});
    else if(name=="high-full-token"){auto bad=a.token;bad.tag^=1ULL<<63;l.complete(0,bad,a.va,false,0);}
    else if(name=="same-index-live-reuse"){auto replacement=a;replacement.token.tag^=1ULL<<62;l.start(0,replacement);}
    else if(name=="same-index-stale-generation"){auto bad=a.token;bad.tag^=1ULL<<63;l.reserve(0,bad,a.va,0,false);}
    else if(name=="wrong-pa"){l.transport.erase(0);l.physicalRequest(0,a.pa+8,0,false,3,true);}
    else if(name=="cancel-without-drain"){l.cancel(0,a.token);l.complete(0,a.token,a.va,false,0,true);}
    else if(name=="reuse-after-reply-before-complete"){response(l,1,1,rows);auto replacement=b;replacement.token.tag++;l.start(1,replacement);}
    else if(name=="duplicate-integer"){response(l,1,1,rows);l.integerReply({1,0,0});}
    else if(name=="stale-after-release"){response(l,1,1,rows);done(l,1,b);l.integerReply({1,0,0});}
    else if(name=="same-index-completion-stale"){response(l,1,1,rows);done(l,1,b);auto c=b;c.token.tag^=1ULL<<63;l.start(1,c);l.complete(1,b.token,b.va,false,0);}
    else if(name=="precise-va"){response(l,1,1,rows);l.complete(1,b.token,b.va+8,false,0);}
    else if(name=="fault-bits"){response(l,1,1,rows);l.complete(1,b.token,b.va,true,7);}
    else if(name=="frozen-local-ack"){l.lives.at(a.token).op.frozen=true;l.local(0,false);}
    else if(name=="sb-live-reuse"){l.enqueueStore(4,b.token,b.pa,b.data,3);l.enqueueStore(4,b.token,b.pa,b.data,3);}
    else if(name=="sb-unbound")l.physicalRequest(4,b.pa,b.data,true,3,true);
    else if(name=="fp-before-drain")l.fpEpoch({6,5});
    else throw std::invalid_argument("unknown negative case");
    throw std::logic_error("negative was incorrectly accepted");
}
int main(int argc,char **argv) {
    try {if(argc==1){positive();std::cout<<"TAGGED_ORACLE_POSITIVE_PASS store_overtake=1 held_late_read=1 fulltoken_reuse=1 cancelled_drain=1 sb_retired_origin=1 fp_epoch=1\n";return 0;}
        negative(argv[1]);
    }catch(const std::runtime_error &e){std::cerr<<"TAGGED_ORACLE_REJECT "<<(argc>1?argv[1]:"positive")<<" "<<e.what()<<"\n";return 1;}
    catch(const std::exception &e){std::cerr<<"TAGGED_ORACLE_TEST_ERROR "<<e.what()<<"\n";return 2;}
    return 2;
}
