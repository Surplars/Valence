#define TRI_SPEED_NO_MAIN 1
#include "trispeed_gmac_frames.cpp"
int main(int argc,char**argv){try{
    const bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";unsigned cases=0,aborts=0,overlap=0;
    for(unsigned rate:{2U,1U,0U}){
        // Two complete banks: cancel active/queued independently and recover.
        {Test t;t.setRate(rate);t.allowAborted=true;t.submit(ethernetBody(256,0x71));t.submit(ethernetBody(256,0x72));
            unsigned n=0;while((!t.wireActive||t.wire.size()<30)&&n++<500000)t.tick();check(t.wireActive,"bank abort setup lacked active wire");
            t.S(txAbort,1);for(unsigned i=0;i<2*t.factor()+6;++i)t.tick();t.S(txAbort,0);t.drain();t.allowAborted=false;
            check(t.txAbort==2&&t.txReject==2&&t.txDone==0,"active+queued TX bank abort lost/doubled owner");
            auto next=ethernetBody(77,0x73);t.expectedTx.push_back(ethernetWire(next));if(inject)t.expectedTx.back()[19]^=1;t.submit(next);t.drain();
            check(t.txComplete==1&&t.txDone==1,"aborted TX bank payload replayed after recovery");aborts+=t.txAbort;overlap+=t.inputOverlap;++cases;}
        // Abort the prefetched next bank together with a partial new producer.
        for(unsigned afterDone:{0U,1U,2U,3U,5U}){Test t;t.setRate(rate);auto first=ethernetBody(64,0x80+afterDone);t.expectedTx.push_back(ethernetWire(first));
            t.submit(first);t.submit(ethernetBody(63,0x90+afterDone));unsigned n=0;while(!t.txDone&&n++<500000)t.tick();check(t.txDone==1,"prefetch abort setup did not retire first frame");
            t.S(txFrame$$valid,1);t.S(txFrame$$bits$$data,0x44332211);t.S(txFrame$$bits$$keep,15);t.S(txFrame$$bits$$last,0);t.S(txFrame$$bits$$bad,0);
            do{t.tick();}while(!t.G(txFrame$$ready));t.S(txFrame$$valid,0);for(unsigned i=0;i<afterDone;++i)t.tick();
            t.S(txAbort,1);t.submit(ethernetBody(60,0xa0));t.S(txAbort,0);t.drain();
            check(t.txComplete==1&&t.txDone==1&&t.txAbort==2&&t.txReject==2,"prefetch/partial-producer TX cancellation mismatch");
            t.transmit(ethernetBody(81,0xb0+afterDone));check(t.txComplete==2&&t.txDone==2,"stale prefetch resurrected a discarded bank");aborts+=t.txAbort;overlap+=t.inputOverlap;++cases;}
        // Rejected short native frame must not advance producer ownership or
        // contaminate the following frame while the other bank is on the wire.
        {Test t;t.setRate(rate);auto a=ethernetBody(2048,0xc0),c=ethernetBody(61,0xc2);t.expectedTx.push_back(ethernetWire(a));t.expectedTx.push_back(ethernetWire(c));
            t.submit(a);t.submit(ethernetBody(13,0xc1));t.submit(c);t.drain();check(t.txReject==1&&t.txDone==2&&t.txComplete==2,"malformed TX collector advanced/destroyed bank ownership");overlap+=t.inputOverlap;++cases;}
    }
    check(aborts==36&&overlap>0,"TX owner tests lacked abort/overlap witnesses");
    std::cout<<"TX_BANK_OWNER_PASS cases="<<cases<<" aborted_owners="<<aborts<<" collection_overlap="<<overlap<<" active_queued_partial=1 prefetch_phase_cancellation=1 reuse_after_abort=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
