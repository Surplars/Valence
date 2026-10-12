// Reuse the nine authored real-protocol episodes, not a synthetic responder.
#define main original_concurrent_main
#include "concurrent_read_store_prefetch.cpp"
#undef main
#ifndef MEMORY_SCHEDULE_OVERLAP
#error "explicit MEMORY_SCHEDULE_OVERLAP=0|1 required"
#endif
static_assert(MEMORY_SCHEDULE_OVERLAP == 0 || MEMORY_SCHEDULE_OVERLAP == 1);

static void dirty_snapshot_store() {
    Gate g; g.permission(false);
    const uint64_t a=base+4096,b=a+stride,c=a+2*stride;
    // Distinct partial bytes in both committed ways; snapshot oracle derives
    // every C beat from authored data before accepting the miss.
    g.store(a,0x55);g.store(b,0xaa);
    const auto victim=g.choose(c,false,false);
    check(victim.allowed&&victim.victim.dirty,"dirty snapshot premise absent");
    const uint64_t other=victim.victim.address==a?b:a;
    g.hold(true,false,false,false);g.send({c},false);
    g.until([&]{return g.wb[0]||g.wb[1];},"miss did not retain victim WB");
    g.ticks(24);
    check(bool(g.t.d.get_io$$acquireOffer())==bool(MEMORY_SCHEDULE_OVERLAP),
        "snapshot-to-A offer boundary differs from explicit mode");
    check(!g.t.d.get_io$$releaseFire(),"held C unexpectedly fired");
    g.begin({other,true,0x1425364758697a8bULL,0x33});g.ticks(24);
    check(bool(!g.offered)==bool(MEMORY_SCHEDULE_OVERLAP),
        "disjoint store did not follow immutable-snapshot admission policy");
    g.hold(false,false,false,false);g.finish("dirty_snapshot_disjoint_store");
}

static void same_set_transient() {
    Gate g;g.permission(false);const uint64_t a=base+6144,b=a+stride;
    g.hold(false,false,true,false);g.send({a},false);
    g.until([&]{return g.t.d.get_io$$grantAckOffer();},"first real E owner absent");
    g.send({b},false);g.ticks(64);
    unsigned acquired=0;for(const auto& k:g.active)if(k)acquired+=g.owners.at(*k).acquired;
    check(acquired==(MEMORY_SCHEDULE_OVERLAP?2U:1U),
        "Home full-way admission failed to preserve independent transient owners");
    g.hold(false,false,false,false);g.finish("same_set_distinct_transients");
}

static void held_reply_handoff() {
    Gate g;g.permission(false);g.t.blockCpu=true;
    g.send({base+8192},false);
    g.until([&]{return g.t.d.get_io$$cpu$$response$$valid();},"first payload not retained");
    g.ticks(8);
    check(bool(g.active[0]||g.active[1])==!bool(MEMORY_SCHEDULE_OVERLAP),
        "installed payload did not transfer from MSHR to response ledger");
    g.send({base+8320},false);
    g.until([&]{unsigned done=0;for(const auto& [key,o]:g.owners)done+=o.filled;return done==2;},
        "second response did not reach original ledger");
    g.begin({base+8448});g.ticks(24);
    check(g.offered&&g.t.cpuExpected.size()==2,"freed MSHR fabricated a response credit");
    g.t.blockCpu=false;g.finish("held_reply_original_credits");
}

int main(int argc,char**argv){try{
    if(argc>1)return original_concurrent_main(argc,argv);
    for(bool first:{false,true}){episode(first,false,0);episode(first,true,0);episode(first,false,1);episode(first,false,2);}
    demand_first();dirty_snapshot_store();same_set_transient();held_reply_handoff();
    std::cout<<"MEMORY_SCHEDULE_OVERLAP_PASS cases="<<completedCases
        <<" mode="<<MEMORY_SCHEDULE_OVERLAP<<" mshrs=2 wb=2 responses=2 independent_bytes=1 real_E=1\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"MEMORY_SCHEDULE_OVERLAP_FAIL "<<e.what()<<'\n';return 1;}}
