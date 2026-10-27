    // Real preparation + real DTLB. Root leaf maps 0x40000000..0x7fffffff
    // to 0x80000000..0xbfffffff. The independent VA/PA relationship is fixed.
    void certifiedSuperpage(bool enabled) {
        defaults();
        d.set_io$$vm$$satp(0x8000000000080200ULL); d.set_io$$vm$$dataPrivilege(1);
        d.set_io$$pmpCfg(0x1f); d.set_io$$pmpAddress((1ULL<<54)-1);
        const uint64_t va=0x40210000ULL, pa=0x80210000ULL;
        auto transaction=[&](bool certificate, uint64_t tag, bool cancel=false) {
            Op op{9,3,tag,va}; bool started=false,physical=false,returned=false,complete=false;
            unsigned ptes=0,passes=0,slot=0; bool discarded=false; uint64_t startCycle=0; uint64_t due=0; std::deque<uint64_t> walks;
            for(uint64_t cycle=0;cycle<300;++cycle) {
                drive(op);d.set_io$$start$$bits$$virtualized(1);d.set_io$$parallel(0);
                d.set_io$$useCertificate(certificate);d.set_io$$start$$valid(cycle>=5&&!started);
                d.set_io$$cancel(cancel&&started&&cycle==startCycle+1?(1U<<slot):0);
                bool reply=physical&&!returned&&cycle>=due;
                d.set_io$$memory$$response$$valid(reply);d.set_io$$memory$$response$$bits$$data(beat(pa));
                bool pte=!walks.empty()&&cycle>=walks.front();
                d.set_io$$pte$$response$$valid(pte);
                d.set_io$$pte$$response$$bits$$data((0x80000ULL<<10)|0xcf);
                d.step();sample(reply,pte);
                if(!started&&cycle>=5&&d.get_io$$start$$ready()) {
                    started=true;startCycle=cycle;const unsigned mask=d.get_io$$startSlots();
                    need(mask&&!(mask&(mask-1)),"certified unique LSU start slot");while(!(mask&(1U<<slot)))++slot;
                }
                if(d.get_io$$discarded()){need(cancel&&!discarded,"certified unowned cancellation discard");discarded=true;}
                if(d.get_io$$pte$$request$$valid()) {
                    need(!certificate,"warmed certified load unexpectedly walked");
                    need(d.get_io$$pte$$request$$bits()==0x80200008ULL,"independent root superpage PTE address");
                    walks.push_back(cycle+2);++ptes;
                }
                if(pte&&d.get_io$$pte$$response$$ready())walks.pop_front();
                if(d.get_io$$certifiedPass())++passes;
                if(d.get_io$$finalRequest()) {
                    need(d.get_io$$selectedSource()==0&&!d.get_io$$finalOrigin(),"certified direct source association");
                    need(bool(d.get_io$$finalPayload$$precheckedLoad())==certificate,"real preparation certificate class");
                    need(d.get_io$$finalPayload$$address()==(certificate?pa:va),"real LSU VA to PA conversion");
                }
                if(d.get_io$$memory$$request$$valid()) {
                    need(started&&!physical,"certified once-only physical owner");physical=true;due=cycle+3;
                    need(d.get_io$$memory$$request$$bits$$address()==pa&&!d.get_io$$memory$$request$$bits$$write(),"independent superpage PA");
                }
                if(reply&&d.get_io$$memory$$response$$ready())returned=true;
                if(d.get_io$$complete$$valid()) {
                    need(!cancel&&returned&&!complete&&!d.get_io$$complete$$bits$$exception(),"certified ordered successful completion");
                    need(d.get_io$$complete$$bits$$token$$tag()==tag&&d.get_io$$complete$$bits$$token$$index()==9,
                         "certified full token completion");
                    need(d.get_io$$complete$$bits$$data()==beat(pa),"certified independent loaded data");complete=true;
                }
                if((cancel?discarded:complete)&&d.get_io$$allIdle()) {
                    need(returned&&walks.empty()&&ptes==(certificate?0:1),"superpage warm and peek walk count");
                    need(passes==unsigned(certificate&&enabled),"certified route must reflect profile, not permission oracle");
                    return;
                }
            }
            throw std::runtime_error("certified superpage transaction timeout");
        };
        transaction(false,0xc000000000000001ULL);
        // Same low VPN and page offset as a warmed legal superpage; noncanonical
        // bit39 must not acquire a proof or LSU request even though the PA fits.
        Op bad{9,3,0xc000000000000002ULL,va|(1ULL<<39)};
        for(unsigned cycle=0;cycle<40;++cycle) {
            drive(bad);d.set_io$$start$$bits$$virtualized(1);d.set_io$$useCertificate(1);
            d.set_io$$start$$valid(1);d.set_io$$memory$$response$$valid(0);d.set_io$$pte$$response$$valid(0);
            d.step();sample();
            need(!d.get_io$$proofAllowed()&&!d.get_io$$start$$ready()&&!d.get_io$$requestOwned()&&
                 !d.get_io$$finalRequest()&&!d.get_io$$memory$$request$$valid()&&!d.get_io$$pte$$request$$valid(),
                 "noncanonical warmed lowVPN superpage acquired authority");
        }
        d.set_io$$start$$valid(0);d.set_io$$useCertificate(0);d.step();sample();
        transaction(true,0xc000000000000003ULL);
        transaction(true,0xc000000000000004ULL,true);
        d.set_io$$start$$valid(0);d.set_io$$useCertificate(0);
        std::cout<<"CERTIFIED_INGRESS_CHAIN_CASE name=real_producer_warmed_superpage_noncanonical enabled="<<enabled<<"\n";
    }
    void mixedFinalSources() {
        defaults();
        unsigned fast=0,physical=0,replies=0,finals=0,drains=0,fastFlows=0,directs=0;
        bool started=false,completed=false;std::deque<std::pair<uint64_t,uint64_t>> pending;
        struct Payload {uint64_t address,data;bool write;};std::deque<Payload> accepted;
        const uint64_t loadAddress=0x8023f000ULL;
        Op load{7,3,0xd000000000000007ULL,loadAddress};
        for(uint64_t cycle=0;cycle<500;++cycle) {
            drive(load);d.set_io$$parallel(0);d.set_io$$start$$valid(cycle>=2&&!started);
            // The second fast store overlaps the registered direct-load head:
            // it is accepted into StoreBuffer but cannot flow through that cycle.
            const bool fastValid=fast==0||(fast<6&&cycle>=3);
            d.set_io$$fastStore$$valid(fastValid);
            d.set_io$$fastStore$$bits$$address(0x80230000ULL+8*fast);
            d.set_io$$fastStore$$bits$$data(0xdead000000000000ULL+fast);
            d.set_io$$fastStore$$bits$$write(1);d.set_io$$fastStore$$bits$$size(3);d.set_io$$fastStore$$bits$$mask(255);
            const bool ready=cycle>=40&&cycle%5!=3;
            d.set_io$$memory$$request$$ready(ready);
            bool reply=!pending.empty()&&cycle>=pending.front().second;
            d.set_io$$memory$$response$$valid(reply);
            d.set_io$$memory$$response$$bits$$data(reply?beat(pending.front().first):0);
            d.step();sample(reply);
            if(cycle>=2&&!started&&d.get_io$$start$$ready())started=true;
            if(fastValid&&d.get_io$$fastStore$$ready())++fast;
            if(d.get_io$$finalRequest()) {
                Payload x{d.get_io$$finalPayload$$address(),d.get_io$$finalPayload$$data(),bool(d.get_io$$finalPayload$$write())};
                if(injection=="source"&&!injected) {x.address^=8;injected=true;std::cout<<"CHAIN_INJECTION_REACHED kind=source\n";}
                if(x.write) {
                    need(x.address>=0x80230000ULL&&x.address<0x80230030ULL&&(x.address&7)==0,
                         "fast/drain final selected unknown store");
                    const unsigned index=(x.address-0x80230000ULL)/8;
                    need(index<fast&&x.data==0xdead000000000000ULL+index,"final payload not associated with accepted fast source");
                    if(d.get_io$$selectedSource()==1)++drains;
                    else {need(d.get_io$$selectedSource()==2,"fast store selected wrong source");++fastFlows;}
                } else {
                    need(started&&x.address==loadAddress&&d.get_io$$selectedSource()==0,
                         "final direct payload not associated with LSU source");++directs;
                }
                accepted.push_back(x);++finals;
            }
            if(d.get_io$$memory$$request$$valid()&&ready) {
                need(!accepted.empty(),"physical source without final accepted owner");
                const auto x=accepted.front();accepted.pop_front();
                need(d.get_io$$memory$$request$$bits$$address()==x.address&&
                     bool(d.get_io$$memory$$request$$bits$$write())==x.write&&
                     (!x.write||d.get_io$$memory$$request$$bits$$data()==x.data),
                     "mixed final source order/payload mismatch");
                pending.push_back({x.address,cycle+4});++physical;
            }
            if(reply&&d.get_io$$memory$$response$$ready()){pending.pop_front();++replies;}
            if(d.get_io$$complete$$valid()) {
                need(!completed&&d.get_io$$complete$$bits$$token$$tag()==load.tag&&
                     d.get_io$$complete$$bits$$token$$index()==7&&!d.get_io$$complete$$bits$$exception()&&
                     d.get_io$$complete$$bits$$data()==beat(loadAddress),"mixed independent full-tag load completion");completed=true;
            }
            if(fast==6&&completed&&d.get_io$$allIdle()) {
                need(finals==7&&physical==7&&replies==7&&accepted.empty()&&pending.empty()&&drains>0&&directs==1,
                     "mixed source coverage/conservation missing");
                std::cout<<"CERTIFIED_INGRESS_CHAIN_CASE name=actual_storebuffer_multisource finals="<<finals<<" drains="<<drains<<" fast="<<fastFlows<<" direct="<<directs<<"\n";return;
            }
        }
        throw std::runtime_error("mixed final source drain timeout");
    }
