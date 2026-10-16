// Unchanged decoded instruction, byte-memory, token and physical-response oracle.
#define main retained_ready_query_main
#include "ready_store_query77_backend.cpp"
#undef main

int main(int argc, char **argv) try {
    require(argc<=2,"usage: queued-cancel [--mutate-retained-handle]");
    const bool mutate=argc==2 && std::string(argv[1])=="--mutate-retained-handle";
    require(argc==1||mutate,"unknown negative control");
    Bench b; b.expectedQuery=true; b.configure(); b.warm(); b.latency=40;
    const Bytes before=b.expected;
    const auto physicalBefore=b.physicalCount, responsesBefore=b.responseCount;
    b.dut.set_holdBackendMemory(true);
    b.dualWorkload(2,false);
    for(unsigned n=0;n<200 && !(b.entries.at(*b.youngLoad).killed&&b.entries.at(*b.secondLoad).killed&&
        b.dut.get_audit$$cancelledQueued());++n)b.tick();
    // Preserve the failure trace if natural scheduling cannot produce the requested case.
    std::cout<<"QUEUED_CANCEL_HELD cycle="<<b.cycle<<" count="<<unsigned(b.dut.get_queued$$count())
        <<" handles="<<unsigned(b.dut.get_queued$$handles())
        <<" cancelled_handles="<<unsigned(b.dut.get_queued$$cancelledHandles())
        <<" stalls="<<b.dut.get_audit$$stalled()<<" cancel_queued="<<b.dut.get_audit$$cancelledQueued()
        <<" early="<<b.earlyStarts<<" credits="<<b.creditReturns
        <<" physical="<<b.physicalCount-physicalBefore<<" responses="<<b.responseCount-responsesBefore<<'\n';
    require(b.entries.at(*b.youngLoad).killed&&b.entries.at(*b.secondLoad).killed,
        "natural decoded redirect failed to kill both early owners");
    require(b.earlyStarts==2&&b.dut.get_queued$$count()==2&&b.dut.get_audit$$stalled()&&
        b.dut.get_audit$$cancelledQueued(),"real stalled FIFO queued-cancellation coverage absent");
    require(b.physicalCount==physicalBefore&&b.responseCount==responsesBefore&&b.creditReturns==0,
        "held cancelled queued owner reached physical service or returned a credit early");
    unsigned expectedMask=0,found=0;
#define SLOT(N) \
    if(b.dut.get_io$$lsuOwner##N##$$valid()) { \
        Token token{unsigned(b.dut.get_io$$lsuOwner##N##$$bits$$index()),uint64_t(b.dut.get_io$$lsuOwner##N##$$bits$$tag())}; \
        if(token==*b.youngLoad||token==*b.secondLoad){expectedMask|=1u<<N;++found;} \
    }
    SLOT(0);SLOT(1);SLOT(2);SLOT(3);
#undef SLOT
    require(found==2,"cancelled queued owners lost their exact resident LSU tokens");
    unsigned observedMask=b.dut.get_queued$$handles();
    if(mutate)observedMask^=1; // Host-observer negative only; does not mutate RTL.
    require(observedMask==expectedMask&&b.dut.get_queued$$cancelledHandles()==expectedMask,
        "independent retained queued-handle oracle mismatch");
    b.wait(12);
    require(b.dut.get_queued$$count()==2&&b.dut.get_queued$$handles()==expectedMask&&b.creditReturns==0,
        "held cancelled queue ownership or credits changed before service");
    b.dut.set_holdBackendMemory(false);b.expected=before;
    b.drain();b.dualWitness(false,true);
    require(b.physicalCount==physicalBefore+2&&b.responseCount==responsesBefore+2&&b.creditReturns==2,
        "released cancelled queued owners failed exact physical response/credit drain");
    require(b.dut.get_queued$$count()==0&&b.dut.get_audit$$accepted()==b.dut.get_audit$$drained(),
        "released cancelled request FIFO failed to empty");
    std::cout<<"QUEUED_CANCEL_PASS cycles="<<b.cycle<<" queued_handles="<<expectedMask
        <<" stalled="<<b.dut.get_audit$$stalled()<<" cancel_queued="<<b.dut.get_audit$$cancelledQueued()
        <<" physical_delta="<<b.physicalCount-physicalBefore<<" responses_delta="<<b.responseCount-responsesBefore
        <<" credit_returns="<<b.creditReturns<<" posted_cache=NOT_EXERCISED\n";
    return 0;
} catch(const std::exception &e){std::cerr<<"QUEUED_CANCEL_FAIL "<<e.what()<<'\n';return 1;}
