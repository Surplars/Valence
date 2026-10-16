#pragma once
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>

// Default52, two Home Acquire entries, two ways, 256 sets, internal line Grant.
// Ownership is derived from accepted A/C/Grant/E/ReleaseAck history. No DUT
// future/capture/ready decision, release slot, beat counter or NEXT state is
// used to establish permission to overlap a committed directory owner.
struct FutureHomeLedger {
    struct Resident { bool live=false; uint64_t pa=0,generation=0; };
    struct Acquire { bool live=false,granted=false,denied=false; uint64_t pa=0,generation=0; unsigned source=0,dir=0; };
    struct Release { bool live=false,dirty=false; uint64_t pa=0,generation=0; unsigned dir=0,beats=0; };
    struct Held { bool live=false; uint64_t pa=0,data=0; unsigned source=0,opcode=0; };
    std::array<Resident,512> residents{};
    std::array<Acquire,2> acquires{};
    std::array<Release,8> releases{};
    std::optional<unsigned> capture;
    Held heldA,heldC;
    uint64_t generation=0,acceptedA=0,acceptedC=0,acceptedE=0,acceptedAck=0;
    uint64_t futureAdmissions=0,overlapCycles=0;
    static void require(bool p,const char *s){if(!p)throw std::runtime_error(s);}
    static unsigned setOf(uint64_t pa){require(!(pa&63),"future home unaligned full PA");return unsigned((pa>>6)&255);}
    bool reserved(unsigned dir) const {for(const auto &a:acquires)if(a.live&&a.dir==dir)return true;return false;}
    bool permitsOwned(unsigned dir,uint64_t pa) const {
        if(!capture)return false;
        const auto &r=releases[*capture];
        return r.live&&r.dirty&&r.beats>0&&r.beats<8&&r.dir==dir&&r.pa!=pa&&
            residents[dir].live&&residents[dir].pa==r.pa&&residents[dir].generation==r.generation&&
            setOf(pa)==(dir&255);
    }
    bool futureAvailable(uint64_t pa) const {
        return capture&&permitsOwned(releases[*capture].dir,pa)&&!reserved(releases[*capture].dir);
    }
    template<class P> void check(P &p){
        for(unsigned dir=0;dir<512;++dir){
            require(p.owned(dir)==residents[dir].live,"future home committed ownership differs from accepted C/E history");
            if(residents[dir].live)require(p.homeResidentPa(dir)==residents[dir].pa,
                "future home committed full PA differs from accepted A/E history");
        }
        unsigned overlaps=0;
        for(unsigned i=0;i<2;++i){
            const auto &a=acquires[i];const unsigned phase=p.homePhase(i);
            require(phase<=4&&bool(phase)==a.live,"future home Acquire lifetime differs from accepted A/E history");
            if(!a.live)continue;
            require(p.homePa(i)==a.pa&&p.homeSource(i)==a.source&&p.homeDirectory(i)==a.dir,
                "future home Acquire full PA/source/directory changed");
            require((phase==4)==a.granted,"future home Grant/E lifetime differs from accepted Grant");
            if(residents[a.dir].live){
                require(!a.granted&&permitsOwned(a.dir,a.pa),"future home unrelated committed/reserved directory collision");
                ++overlaps;
            }
        }
        require(overlaps<=1,"future home multiple reservations overlap one dirty capture");
        overlapCycles+=overlaps!=0;
        if(p.homeGrantValid()){
            const unsigned i=p.homeGrantEntry();require(i<2,"future home Grant sink range");
            const auto &a=acquires[i];
            require(a.live&&!a.granted&&p.homeGrantSource()==a.source&&!residents[a.dir].live,
                "future home Grant published before complete C or lost source owner");
        }
        if(p.homeEValid()){
            const unsigned i=p.homeESink();require(i<2,"future home E sink range");
            require(acquires[i].live&&acquires[i].granted&&!residents[acquires[i].dir].live,
                "future home E lacks completed Grant or overlaps committed owner");
        }
    }
    template<class P> void advance(P &p){
        const bool av=p.aValid(),cv=p.homeCValid();
        const bool af=av&&p.aFire(),cf=cv&&p.homeCReady();
        uint64_t apa=0,cpa=0,cdata=0;unsigned asource=0,csource=0,copcode=0;
        if(av){apa=p.aPa();asource=p.aSource();setOf(apa);}
        if(cv){cpa=p.homeCPa();csource=p.homeCSource();copcode=p.homeCOpcode();cdata=p.homeCData();setOf(cpa);
            require(csource<8&&(copcode==6||copcode==7)&&p.homeCSize()==6&&p.homeCParam()==1,
                "future home unexpected C class/size/permission/source");}
        if(heldA.live)require(av&&apa==heldA.pa&&asource==heldA.source,"future home held A identity changed");
        if(heldC.live)require(cv&&cpa==heldC.pa&&csource==heldC.source&&copcode==heldC.opcode&&cdata==heldC.data,
            "future home held C identity/data changed");
        heldA={av&&!af,apa,0,asource,6};heldC={cv&&!cf,cpa,cdata,csource,copcode};
        unsigned aslot=2,adir=512,cdir=512;
        bool future=false;
        if(af){
            require(asource<2,"future home A source range");
            for(unsigned i=0;i<2;++i){const auto &a=acquires[i];
                if(!a.live&&aslot==2)aslot=i;
                if(a.live)require(a.source!=asource&&a.pa!=apa,"future home A duplicated live source/full PA");}
            require(aslot<2,"future home A reused live Acquire entry");
            for(unsigned w=0;w<2;++w){const unsigned dir=setOf(apa)+256*w;
                require(!residents[dir].live||residents[dir].pa!=apa,"future home A targets committed full PA");
                if(adir==512&&!residents[dir].live&&!reserved(dir))adir=dir;}
            for(const auto &r:releases)if(r.live)require(r.pa!=apa,"future home A targets pending release full PA");
            require(!cv||cpa!=apa,"future home A targets currently offered C full PA");
            if(adir==512){require(futureAvailable(apa),"future home A has no free or proven future directory");
                adir=releases[*capture].dir;future=true;}
        }
        if(cv){
            if(capture){const auto &r=releases[*capture];
                require(csource==*capture&&copcode==7&&cpa==r.pa&&r.beats>0&&r.beats<8,
                    "future home dirty C burst interleaved/changed full identity");cdir=r.dir;
            }else{
                for(unsigned w=0;w<2;++w){const unsigned dir=setOf(cpa)+256*w;
                    if(residents[dir].live&&residents[dir].pa==cpa){require(cdir==512,"future home duplicate committed full PA");cdir=dir;}}
                require(cdir<512,"future home first C lacks accepted A/E resident owner");
                if(cf){require(!releases[csource].live&&!reserved(cdir),"future home first C reused source/reserved directory");
                    for(const auto &r:releases)require(!r.live||r.pa!=cpa,"future home duplicate pending C full PA");}
            }
        }
        // Validate/apply E against pre-edge ownership. A on this edge cannot
        // recycle an E-retiring entry, and a future C8 cannot justify early E.
        if(p.homeEValid()&&p.homeEFire()){
            const unsigned i=p.homeESink();auto &a=acquires[i];
            require(!cf||cdir!=a.dir,"future home simultaneous C/E directory alias");
            if(!a.denied)residents[a.dir]={true,a.pa,a.generation};
            a.live=false;++acceptedE;
        }
        if(p.homeGrantValid()&&p.homeGrantFire()){
            auto &a=acquires[p.homeGrantEntry()];a.granted=true;a.denied=p.homeGrantDenied();
        }
        if(p.homeAckFire()){
            const unsigned source=p.homeAckSource();require(source<8,"future home ReleaseAck source range");
            auto &r=releases[source];require(r.live&&r.beats==(r.dirty?8U:1U),
                "future home ReleaseAck lacks complete accepted C owner");
            r.live=false;++acceptedAck; // Never clears a possibly reused directory.
        }
        if(cf){
            if(!capture){
                releases[csource]={true,copcode==7,cpa,residents[cdir].generation,cdir,1};
                if(copcode==7)capture=csource;else residents[cdir].live=false;
            }else{
                auto &r=releases[*capture];++r.beats;
                if(r.beats==8){residents[r.dir].live=false;capture.reset();}
            }
            ++acceptedC;
        }
        if(af){acquires[aslot]={true,false,false,apa,++generation,asource,adir};++acceptedA;futureAdmissions+=future;}
    }
    void finish() const {
        require(!capture&&!heldA.live&&!heldC.live,"future home accepted capture/held offer not drained");
        for(const auto &a:acquires)require(!a.live,"future home Acquire not drained");
        for(const auto &r:releases)require(!r.live,"future home ReleaseAck owner not drained");
        require(acceptedA==acceptedE,"future home A/E conservation");
        std::cout<<"FUTURE_HOME_LEDGER_PASS a="<<acceptedA<<" c="<<acceptedC<<" e="<<acceptedE
            <<" release_ack="<<acceptedAck<<" future_admissions="<<futureAdmissions<<" overlap_cycles="<<overlapCycles<<"\n";
    }
};
