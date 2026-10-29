#include "fabric_machine_vec_api.h"
#include "../harness/gsim_model_storage.h"
#ifndef ENABLE_JTAG
#define ENABLE_JTAG 1
#endif
#ifndef ENABLE_MEMORY_COPY_DMA
#define ENABLE_MEMORY_COPY_DMA 1
#endif
#ifndef ENABLE_NETWORK
#define ENABLE_NETWORK 1
#endif
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

static void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
struct Driver {
    GsimModelStorage<FabricDut> storage;
    FabricDut& dut=storage.get();
    std::string runtimeNegative;
    struct Read { uint64_t address; unsigned id, beats, beat, size, due; };
    struct Write { uint64_t address; unsigned id, beats, beat, size; };
    struct Reply { unsigned id, due; uint64_t data=0; };
    std::deque<Read> reads;
    std::deque<Write> writes;
    std::deque<Reply> writeReplies, msiReplies;
    std::array<std::deque<Reply>,3> registerReplies;
    std::map<uint64_t,uint64_t> memory;
    std::array<unsigned,2> nextOwner{0,0};
    unsigned cycles=0, scalarReplies=0, axiReads=0, axiWrites=0, axiB=0, romReads=0, romSubwordReads=0, romDenied=0;
    unsigned registerRequests=0, msi=0, probes=0, grants=0, clearReplies=0, maintenance=0;
    bool holdB=false, inject=false, probeActive=false, ePending=false, privateDirty=false;
    bool holdProbe=false, probeClearEnabled=false, autoClearRequested=false, autoClearAccepted=false;
    unsigned postStatusClears=0;
    bool networkHoleMutation=false;
    bool captureNetworkTx=false;
    std::vector<uint32_t> networkTx;
    unsigned networkControl=0;
#ifdef RUNTIME_CANCELLATION
    unsigned runtimePrepares=0, runtimeCancels=0, runtimeResumes=0, tileResumes=0, tileResumed=0, terminals=0;
#endif
    unsigned probeBeat=0, probeSource=0, eSink=0;
    uint64_t probeAddress=0;
    static constexpr uint64_t ramBase=0x80200000ULL;
    static constexpr uint64_t dirtyBase=0xd170000000000000ULL;

    Driver() {
        dut.set_io$$transportCpuEmptySynchronized(1); dut.set_io$$fabricTransportEmpty(1);
#ifdef RUNTIME_MAINTENANCE
        dut.set_io$$runtimeResume$$valid(0); dut.set_io$$runtimeResume$$bits(0);
        dut.set_io$$tile$$maintenanceResume$$ready(0);
        dut.set_io$$tile$$maintenanceStatus$$bits$$holdUntilResume(0);
#endif
#ifdef RUNTIME_CANCELLATION
        dut.set_io$$runtimeCancel$$valid(0); dut.set_io$$runtimeCancel$$bits(0);
        dut.set_io$$runtimeComplete$$ready(0);
        dut.set_io$$tile$$maintenanceResumed$$valid(0); dut.set_io$$tile$$maintenanceResumed$$bits(0);
#endif
        dut.set_io$$externalMaintenance$$valid(0); dut.set_io$$externalMaintenance$$bits$$epoch(0);
        dut.set_io$$externalMaintenance$$bits$$invalidateInstructions(0);
        dut.set_io$$externalMaintenance$$bits$$invalidateTranslations(0);
        dut.set_io$$tile$$maintenance$$ready(0);
        dut.set_io$$tile$$maintenanceStatus$$valid(0); dut.set_io$$tile$$maintenanceStatus$$bits$$epoch(0);
        dut.set_io$$tile$$maintenanceStatus$$bits$$privateOwnersDrained(1);
        dut.set_io$$tile$$maintenanceStatus$$bits$$dirtyWritebackCompleted(1);
        dut.set_io$$tile$$maintenanceStatus$$bits$$fetchQuiescent(1);
        dut.set_io$$tile$$maintenanceStatus$$bits$$invalidationsCompleted(0);
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(0);
        dut.set_io$$ddrReady(1); dut.set_io$$timerTick(0); dut.set_io$$sources(0);
        dut.set_io$$uartRx(1); dut.set_io$$externalUartIrq(0);
        dut.set_io$$program$$valid(0); dut.set_io$$program$$bits$$index(0); dut.set_io$$program$$bits$$data(0);
#if ENABLE_JTAG
        dut.set_io$$jtagLinkUp(1); dut.set_io$$jtagDmi$$request$$valid(0);
        dut.set_io$$jtagDmi$$request$$bits$$address(0); dut.set_io$$jtagDmi$$request$$bits$$data(0);
        dut.set_io$$jtagDmi$$request$$bits$$op(0); dut.set_io$$jtagDmi$$response$$ready(1);
#endif
#if ENABLE_NETWORK
#define STREAM(name) dut.set_io$$ethernetStreams##name##$$valid(0); \
    dut.set_io$$ethernetStreams##name##$$bits$$data(0); \
    dut.set_io$$ethernetStreams##name##$$bits$$keep(0); \
    dut.set_io$$ethernetStreams##name##$$bits$$last(0)
        STREAM($$rxData); STREAM($$rxStatus);
#undef STREAM
        dut.set_io$$ethernetStreams$$txData$$ready(1); dut.set_io$$ethernetStreams$$txControl$$ready(1);
#endif
#define TL_INIT(port) \
        dut.set_io$$tile##port##$$a$$valid(0); \
        dut.set_io$$tile##port##$$a$$bits$$opcode(4); dut.set_io$$tile##port##$$a$$bits$$param(0); \
        dut.set_io$$tile##port##$$a$$bits$$size(3); dut.set_io$$tile##port##$$a$$bits$$source(0); \
        dut.set_io$$tile##port##$$a$$bits$$address(0); dut.set_io$$tile##port##$$a$$bits$$mask(255); \
        dut.set_io$$tile##port##$$a$$bits$$data(0); dut.set_io$$tile##port##$$a$$bits$$corrupt(0); \
        dut.set_io$$tile##port##$$b$$ready(1); dut.set_io$$tile##port##$$d$$ready(1); \
        dut.set_io$$tile##port##$$c$$valid(0); dut.set_io$$tile##port##$$c$$bits$$opcode(4); \
        dut.set_io$$tile##port##$$c$$bits$$param(0); dut.set_io$$tile##port##$$c$$bits$$size(6); \
        dut.set_io$$tile##port##$$c$$bits$$source(0); dut.set_io$$tile##port##$$c$$bits$$address(0); \
        dut.set_io$$tile##port##$$c$$bits$$data(0); dut.set_io$$tile##port##$$c$$bits$$corrupt(0); \
        dut.set_io$$tile##port##$$e$$valid(0); dut.set_io$$tile##port##$$e$$bits$$sink(0)
        TL_INIT($$instructionFetch); TL_INIT($$coherent_0); TL_INIT($$coherent_1);
#undef TL_INIT
        dut.set_io$$tile$$lineGrant_0$$ready(1); dut.set_io$$tile$$lineGrant_1$$ready(1);
        request(0,0,false,0,3,false,0,false,false); request(1,0,false,0,3,false,0,false,false);
        dut.set_io$$tile$$scalar_0$$request$$valid(0); dut.set_io$$tile$$scalar_1$$request$$valid(0);
        dut.set_io$$tile$$scalar_0$$response$$ready(0); dut.set_io$$tile$$scalar_1$$response$$ready(0);
        driveEndpoints(); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    }
    void request(unsigned lane,uint64_t address,bool write,uint64_t data,unsigned size=3,
                 bool atomic=false,unsigned op=0,bool clear=false,bool lookup=true) {
#define SET(field,value) do { if(lane==0) dut.set_io$$tile$$scalar_0##field(value); \
                             else dut.set_io$$tile$$scalar_1##field(value); } while(0)
        SET($$request$$valid,1); SET($$request$$bits$$owner,nextOwner[lane]);
        SET($$request$$bits$$clearReservation,clear); SET($$request$$bits$$needsCoherenceLookup,lookup);
        SET($$request$$bits$$memory$$atomic,atomic); SET($$request$$bits$$memory$$atomicOp,op);
        SET($$request$$bits$$memory$$address,address); SET($$request$$bits$$memory$$write,write);
        SET($$request$$bits$$memory$$size,size); SET($$request$$bits$$memory$$data,data);
        SET($$request$$bits$$memory$$mask,((1U<<(1U<<size))-1U)<<(address&7));
        SET($$request$$bits$$memory$$virtualized,0); SET($$request$$bits$$memory$$precheckedLoad,0);
        SET($$request$$bits$$memory$$translationEpoch,0); SET($$request$$bits$$memory$$prefetchNextAllowed,0);
        SET($$request$$bits$$memory$$uncached,1);
#undef SET
    }
    void driveEndpoints() {
        dut.set_io$$ddrAxi$$ar$$ready(reads.size()<4);
        dut.set_io$$ddrAxi$$aw$$ready(writes.size()+writeReplies.size()<2);
        dut.set_io$$ddrAxi$$w$$ready(!writes.empty());
        bool r=!reads.empty() && reads.front().due<=cycles;
        dut.set_io$$ddrAxi$$r$$valid(r); dut.set_io$$ddrAxi$$r$$bits$$id(r?reads.front().id:0);
        dut.set_io$$ddrAxi$$r$$bits$$data(r?memory[(reads.front().address+reads.front().beat*(1U<<reads.front().size))&~7ULL]:0);
        dut.set_io$$ddrAxi$$r$$bits$$resp(0);
        dut.set_io$$ddrAxi$$r$$bits$$last(r && reads.front().beat+1==reads.front().beats);
        bool b=!holdB && !writeReplies.empty() && writeReplies.front().due<=cycles;
        dut.set_io$$ddrAxi$$b$$valid(b); dut.set_io$$ddrAxi$$b$$bits$$id(b?writeReplies.front().id:0);
        dut.set_io$$ddrAxi$$b$$bits$$resp(0);
        bool m=!msiReplies.empty() && msiReplies.front().due<=cycles;
        dut.set_io$$tile$$msi$$request$$ready(msiReplies.size()<8);
        dut.set_io$$tile$$msi$$response$$valid(m); dut.set_io$$tile$$msi$$response$$bits$$data(0);
        dut.set_io$$tile$$msi$$response$$bits$$error(0);
#define REGISTER(port,index) \
        dut.set_io##port##$$request$$ready(registerReplies[index].size()<8); \
        dut.set_io##port##$$response$$valid(!registerReplies[index].empty() && registerReplies[index].front().due<=cycles); \
        dut.set_io##port##$$response$$bits$$data(registerReplies[index].empty()?0:registerReplies[index].front().data); \
        dut.set_io##port##$$response$$bits$$error(0)
        REGISTER($$externalUartRegisters,0);
#if ENABLE_NETWORK
        REGISTER($$ethernetRegisters,1);
#endif
        REGISTER($$clockManagementRegisters,2);
#undef REGISTER
        dut.set_io$$tile$$coherent_1$$b$$ready(!holdProbe);
        if(autoClearRequested) {
            if(!autoClearAccepted) request(1,0,false,0,3,false,0,true,false);
            else dut.set_io$$tile$$scalar_1$$request$$valid(0);
            dut.set_io$$tile$$scalar_1$$response$$ready(1);
        }
        dut.set_io$$tile$$coherent_1$$e$$valid(ePending); dut.set_io$$tile$$coherent_1$$e$$bits$$sink(eSink);
        dut.set_io$$tile$$coherent_1$$c$$valid(probeActive);
        dut.set_io$$tile$$coherent_1$$c$$bits$$opcode(5); dut.set_io$$tile$$coherent_1$$c$$bits$$param(1);
        dut.set_io$$tile$$coherent_1$$c$$bits$$source(probeSource);
        dut.set_io$$tile$$coherent_1$$c$$bits$$address(probeAddress);
        dut.set_io$$tile$$coherent_1$$c$$bits$$data(dirtyBase+probeBeat);
    }
    void tick() {
        driveEndpoints();
        bool r=!reads.empty() && reads.front().due<=cycles;
        bool b=!holdB && !writeReplies.empty() && writeReplies.front().due<=cycles;
        bool w=!writes.empty();
        bool arReady=reads.size()<4, awReady=writes.size()+writeReplies.size()<2;
        bool msiReady=msiReplies.size()<8;
        bool m=!msiReplies.empty() && msiReplies.front().due<=cycles;
        std::array<bool,3> regReply, regReady;
        for(unsigned i=0;i<3;++i) {
            regReply[i]=!registerReplies[i].empty() && registerReplies[i].front().due<=cycles;
            regReady[i]=registerReplies[i].size()<8;
        }
        bool clearWasAccepted=autoClearAccepted;
        dut.step();
        if(autoClearRequested && !clearWasAccepted && dut.get_io$$tile$$scalar_1$$request$$ready()) {
            autoClearAccepted=true;
        }
        if(autoClearRequested && clearWasAccepted && dut.get_io$$tile$$scalar_1$$response$$valid()) {
            check(dut.get_io$$tile$$scalar_1$$response$$bits$$clearReservation() &&
                dut.get_io$$tile$$scalar_1$$response$$bits$$owner()==nextOwner[1],
                "post-status probe clear lost its real completion");
            nextOwner[1]=(nextOwner[1]+1)&15; ++scalarReplies; ++clearReplies; ++postStatusClears;
            autoClearRequested=false; autoClearAccepted=false;
            dut.set_io$$tile$$scalar_1$$request$$valid(0); dut.set_io$$tile$$scalar_1$$response$$ready(0);
        }
        if(r && dut.get_io$$ddrAxi$$r$$ready()) {
            if(++reads.front().beat==reads.front().beats) reads.pop_front();
        }
        if(b && dut.get_io$$ddrAxi$$b$$ready()) { writeReplies.pop_front(); ++axiB; }
        if(w && dut.get_io$$ddrAxi$$w$$valid()) {
            auto& x=writes.front(); uint64_t address=(x.address+x.beat*(1U<<x.size))&~7ULL;
            uint64_t data=dut.get_io$$ddrAxi$$w$$bits$$data(); unsigned strobe=dut.get_io$$ddrAxi$$w$$bits$$strb();
            for(unsigned byte=0;byte<8;++byte) if(strobe&(1U<<byte)) {
                uint64_t mask=255ULL<<(byte*8); memory[address]=(memory[address]&~mask)|(data&mask);
            }
            bool last=++x.beat==x.beats;
            check(bool(dut.get_io$$ddrAxi$$w$$bits$$last())==last,"AXI W burst length mismatch");
            if(last) { writeReplies.push_back({x.id,cycles+9}); writes.pop_front(); }
        }
        if(dut.get_io$$ddrAxi$$ar$$valid() && arReady) {
            check(dut.get_io$$ddrAxi$$ar$$bits$$burst()==1,"AXI AR burst type mismatch");
            reads.push_back({dut.get_io$$ddrAxi$$ar$$bits$$addr(),dut.get_io$$ddrAxi$$ar$$bits$$id(),
                unsigned(dut.get_io$$ddrAxi$$ar$$bits$$len()+1),0,dut.get_io$$ddrAxi$$ar$$bits$$size(),cycles+5});
            ++axiReads;
        }
        if(dut.get_io$$ddrAxi$$aw$$valid() && awReady) {
            check(dut.get_io$$ddrAxi$$aw$$bits$$burst()==1,"AXI AW burst type mismatch");
            writes.push_back({dut.get_io$$ddrAxi$$aw$$bits$$addr(),dut.get_io$$ddrAxi$$aw$$bits$$id(),
                unsigned(dut.get_io$$ddrAxi$$aw$$bits$$len()+1),0,dut.get_io$$ddrAxi$$aw$$bits$$size()}); ++axiWrites;
        }
        if(m && dut.get_io$$tile$$msi$$response$$ready()) msiReplies.pop_front();
        if(dut.get_io$$tile$$msi$$request$$valid() && msiReady) {
            check(dut.get_io$$tile$$msi$$request$$bits$$address()==0x24000000ULL &&
                dut.get_io$$tile$$msi$$request$$bits$$data()==11 && dut.get_io$$tile$$msi$$request$$bits$$write(),
                "shared fabric MSI routing mismatch");
            msiReplies.push_back({0,cycles+5}); ++msi;
        }
#define REGISTER(port,index,value) \
        if(regReply[index] && dut.get_io##port##$$response$$ready()) registerReplies[index].pop_front(); \
        if(dut.get_io##port##$$request$$valid() && regReady[index]) { \
            registerReplies[index].push_back({0,cycles+5,dut.get_io##port##$$request$$bits$$write()?0ULL:value}); ++registerRequests; }
        REGISTER($$externalUartRegisters,0,0xa5ULL);
#if ENABLE_NETWORK
        REGISTER($$ethernetRegisters,1,0x1234ULL);
#endif
        REGISTER($$clockManagementRegisters,2,0x5678ULL);
#undef REGISTER
        if(ePending && dut.get_io$$tile$$coherent_1$$e$$ready()) ePending=false;
        if(probeActive && dut.get_io$$tile$$coherent_1$$c$$ready()) {
            if(++probeBeat==8) { probeActive=false; privateDirty=false; }
        }
        if(dut.get_io$$tile$$coherent_1$$b$$valid() && !holdProbe) {
            check(privateDirty && !probeActive && dut.get_io$$tile$$coherent_1$$b$$bits$$address()==ramBase+0x2000,
                "coherence lookup missed dirty private owner");
            probeActive=true; probeBeat=0; probeAddress=dut.get_io$$tile$$coherent_1$$b$$bits$$address();
            probeSource=dut.get_io$$tile$$coherent_1$$b$$bits$$source(); ++probes;
            if(probeClearEnabled) {
                check(dut.get_io$$maintenancePending(), "directed DMA probe did not occur after tile-ready");
                autoClearRequested=true; probeClearEnabled=false;
            }
        }
        if(dut.get_io$$tile$$lineGrant_1$$valid()) {
            check(!dut.get_io$$tile$$lineGrant_1$$bits$$denied() && !dut.get_io$$tile$$lineGrant_1$$bits$$corrupt() &&
                dut.get_io$$tile$$lineGrant_1$$bits$$source()==0,"coherent LineGrant metadata mismatch");
            ePending=true; eSink=dut.get_io$$tile$$lineGrant_1$$bits$$sink(); ++grants;
        }
        check(!dut.get_io$$tile$$coherent_0$$b$$valid() && !dut.get_io$$tile$$lineGrant_0$$valid(),
            "coherent client identity was lost");
#if ENABLE_NETWORK
        if(captureNetworkTx && dut.get_io$$ethernetStreams$$txControl$$valid()) {
            check(dut.get_io$$ethernetStreams$$txControl$$bits$$keep()==15 &&
                dut.get_io$$ethernetStreams$$txControl$$bits$$data()==(networkControl==0?0xa0000000U:0) &&
                bool(dut.get_io$$ethernetStreams$$txControl$$bits$$last())==(networkControl==5),
                "network TX control ABI mismatch");
            ++networkControl;
        }
        if(captureNetworkTx && dut.get_io$$ethernetStreams$$txData$$valid()) {
            check(dut.get_io$$ethernetStreams$$txData$$bits$$keep()==15 &&
                bool(dut.get_io$$ethernetStreams$$txData$$bits$$last())==(networkTx.size()==15),
                "network TX payload extent mismatch");
            networkTx.push_back(dut.get_io$$ethernetStreams$$txData$$bits$$data());
        }
#endif
        ++cycles; check(cycles<40000,"bounded fabric completion failure");
    }
    void idle(unsigned count) { while(count--) tick(); }
    uint64_t access(unsigned lane,uint64_t address,bool write=false,uint64_t data=0,unsigned size=3,
                    bool atomic=false,unsigned op=0,bool clear=false,bool lookup=true,bool expectedError=false) {
#define SET(field,value) do { if(lane==0) dut.set_io$$tile$$scalar_0##field(value); \
                             else dut.set_io$$tile$$scalar_1##field(value); } while(0)
#define GET(field) (lane==0?dut.get_io$$tile$$scalar_0##field():dut.get_io$$tile$$scalar_1##field())
        request(lane,address,write,data,size,atomic,op,clear,lookup); SET($$response$$ready,0);
        do {tick();} while(!GET($$request$$ready));
        SET($$request$$valid,0); idle(3);
        if(expectedError) {
            while(!GET($$response$$valid)) tick();
            uint64_t held=GET($$response$$bits$$memory$$data);
            for(unsigned n=0;n<8;++n) {
                bool observedError=GET($$response$$bits$$memory$$error);
                if(networkHoleMutation) {
                    std::cerr<<"COMMON_NETWORK_OPTION_MUTANT_REACHED\n";
                    observedError=!observedError; networkHoleMutation=false;
                }
                check(GET($$response$$valid) && GET($$response$$bits$$owner)==nextOwner[lane] &&
                    observedError && !GET($$response$$bits$$memory$$pageFault) &&
                    GET($$response$$bits$$memory$$data)==held,"held hole response changed under backpressure");
                tick();
            }
        }
        SET($$response$$ready,1);
        do {tick();} while(!GET($$response$$valid));
        check(GET($$response$$bits$$owner)==nextOwner[lane] && bool(GET($$response$$bits$$clearReservation))==clear,
            "fabric scalar owner/kind mismatch");
        check(bool(GET($$response$$bits$$memory$$error))==expectedError &&
            !GET($$response$$bits$$memory$$pageFault),"fabric scalar access error");
        uint64_t answer=GET($$response$$bits$$memory$$data); SET($$response$$ready,0);
        nextOwner[lane]=(nextOwner[lane]+1)&15; ++scalarReplies; if(clear) ++clearReplies;
        return answer;
#undef SET
#undef GET
    }
    void expect(unsigned lane,uint64_t address,uint64_t value,unsigned size=3) {
        uint64_t actual=access(lane,address,false,0,size); if(inject) { actual^=1; inject=false; }
        check(actual==value,"FABRIC memory/MMIO independent oracle mismatch");
    }
    // Fixed external ABI oracles, not values derived from DUT configuration.
    void jtagOptionRun() {
#if ENABLE_JTAG
        dut.set_io$$jtagDmi$$response$$ready(0);
        dut.set_io$$jtagDmi$$request$$bits$$op(1);
        dut.set_io$$jtagDmi$$request$$bits$$address(0x40);
        dut.set_io$$jtagDmi$$request$$bits$$data(0);
        dut.set_io$$jtagDmi$$request$$valid(1);
        unsigned wait=0;
        do { check(++wait<=100,"JTAG option DMI request timeout"); tick(); }
        while(!dut.get_io$$jtagDmi$$request$$ready());
        dut.set_io$$jtagDmi$$request$$valid(0);
        wait=0;
        do { check(++wait<=100,"JTAG option DMI response timeout"); tick(); }
        while(!dut.get_io$$jtagDmi$$response$$valid());
        for(unsigned held=0;held<8;++held) {
            check(dut.get_io$$jtagDmi$$response$$valid() &&
                dut.get_io$$jtagDmi$$response$$bits$$status()==0 &&
                dut.get_io$$jtagDmi$$response$$bits$$data()==0x564c0101,
                "JTAG option held capability oracle mismatch");
            tick();
        }
        dut.set_io$$jtagDmi$$response$$ready(1); tick(); idle(2);
        check(!dut.get_io$$jtagDmi$$response$$valid(),"JTAG option duplicated DMI response");
        expect(0,0x10003030ULL,0x80200000ULL);
        expect(1,0x10003030ULL,0x80200000ULL);
#else
        // Absent device leaves a hole; it must not alias another peripheral or DDR.
        // Negative mode expects success and must reject the real error.
        const bool expectedError=!inject;
        access(0,0x10003000ULL,false,0,3,false,0,false,true,expectedError);
        access(1,0x10003008ULL,true,1,3,false,0,false,true,expectedError);
        check(registerRequests==0 && axiReads==0 && axiWrites==0,
            "disabled JTAG window reached another device");
#endif
        idle(8);
        check(!dut.get_io$$tile$$scalar_0$$response$$valid() &&
            !dut.get_io$$tile$$scalar_1$$response$$valid(),"JTAG option duplicated scalar response");
        check(dut.get_io$$allObligationsIdle(),"JTAG option retained accepted obligation");
        std::cout<<"COMMON_JTAG_OPTION_PASS enabled="<<ENABLE_JTAG<<" scalar="<<scalarReplies
                 <<" cycles="<<cycles<<"\n";
    }
    uint32_t dmi(unsigned address, unsigned op, uint32_t data=0) {
#if ENABLE_JTAG
        dut.set_io$$jtagDmi$$response$$ready(0);
        dut.set_io$$jtagDmi$$request$$bits$$address(address);
        dut.set_io$$jtagDmi$$request$$bits$$op(op);
        dut.set_io$$jtagDmi$$request$$bits$$data(data);
        dut.set_io$$jtagDmi$$request$$valid(1);
        do { tick(); } while(!dut.get_io$$jtagDmi$$request$$ready());
        dut.set_io$$jtagDmi$$request$$valid(0);
        do { tick(); } while(!dut.get_io$$jtagDmi$$response$$valid());
        uint32_t answer=dut.get_io$$jtagDmi$$response$$bits$$data();
        for(unsigned n=0;n<4;++n) {
            check(dut.get_io$$jtagDmi$$response$$valid() &&
                dut.get_io$$jtagDmi$$response$$bits$$status()==0 &&
                dut.get_io$$jtagDmi$$response$$bits$$data()==answer,"DMI held response changed");
            tick();
        }
        dut.set_io$$jtagDmi$$response$$ready(1); tick();
        dut.set_io$$jtagDmi$$response$$ready(0); return answer;
#else
        throw std::runtime_error("memory DMA test requires independent JTAG producer");
#endif
    }
    void irq4Setup() {
        access(0,0x0c000000,true,256,2);
        access(0,0x0c000010,true,4,2); // source 4, rising edge
        access(0,0x0c003010,true,11,2);
        access(0,0x0c001edc,true,4ULL<<32,2);
    }
    void finishHeldWrite(unsigned tag) {
        // Fresh uncached destinations below have no Home/private residency.
        // Require a real accepted AXI write before testing its retained B owner.
        unsigned limit=cycles+2000;
        while(writeReplies.empty()) { check(cycles<limit,"test did not reach retained AXI B"); tick(); }
        fence(tag);
        for(unsigned n=0;n<20;++n) {
            tick(); check(!dut.get_io$$tile$$fabricDrainedEpoch$$valid(),
                "maintenance acknowledged retained network/debug AXI B owner");
        }
        holdB=false;
        do { tick(); } while(!dut.get_io$$tile$$fabricDrainedEpoch$$valid());
        for(unsigned n=0;n<5;++n) {
            check(dut.get_io$$tile$$fabricDrainedEpoch$$bits()==tag,"DMA option drain epoch changed"); tick();
        }
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(1); tick();
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(0); idle(3); ++maintenance;
    }
    void memoryDmaOptionRun() {
#if ENABLE_NETWORK
        // Fixed independent network identity also gives the mutation a short oracle.
        expect(0,0x10002000,0x56444d4100010001ULL);
#if ENABLE_MEMORY_COPY_DMA
        run(); // Existing actual ordinary-DMA copies, dirty probes and owner/drain cases.
        irq4Setup(); unsigned before=msi;
        access(0,ramBase+0x7000,true,0x1234abcddcba4321ULL);
        access(0,0x10001000,true,ramBase+0x7000);
        access(0,0x10001008,true,ramBase+0x7100);
        access(0,0x10001010,true,8); access(0,0x10001018,true,5);
        while(access(0,0x10001020,false,0)!=2) {}
        expect(1,ramBase+0x7100,0x1234abcddcba4321ULL);
        idle(30); check(msi==before+1,"ordinary DMA IRQ4 did not reach MSI");
        access(0,0x10001018,true,2); idle(8);
#else
        irq4Setup();
        const unsigned registersBefore=registerRequests, readsBefore=axiReads, writesBefore=axiWrites;
        // Every former 64-bit register plus both byte endpoints stays a hole.
        for(unsigned offset=0;offset<40;offset+=8) {
            access(offset/8%2,0x10001000+offset,false,0,3,false,0,false,true,true);
            access((offset/8+1)%2,0x10001000+offset,true,5,3,false,0,false,true,true);
        }
        for(unsigned offset : {0U,39U}) {
            access(0,0x10001000+offset,false,0,0,false,0,false,true,true);
            access(1,0x10001000+offset,true,0xffULL<<((offset&7)*8),0,false,0,false,true,true);
        }
        idle(12);
        check(registerRequests==registersBefore && axiReads==readsBefore && axiWrites==writesBefore,
            "absent ordinary DMA aliased another endpoint");
        check(msi==0 && !dut.get_io$$tile$$scalar_0$$response$$valid() &&
            !dut.get_io$$tile$$scalar_1$$response$$valid(),"absent DMA produced IRQ or duplicate reply");
        check(dut.get_io$$allObligationsIdle(),"absent DMA retained owner");
        // External source 4 is independent and must not be masked with the removed DMA.
        dut.set_io$$sources(1U<<3); idle(30); dut.set_io$$sources(0); idle(12);
        check(msi==1,"DMA removal masked legitimate external IRQ source 4");

        // Real SBA write/read, not just the JTAG capability register.
        access(0,0x10003008,true,1); // arm loader
        dmi(0x39,2,ramBase+0x8000); holdB=true;
        dmi(0x3c,2,0xcafebabe); finishHeldWrite(51);
        check((dmi(0x38,1)&((7U<<12)|(1U<<21)|(1U<<22)))==0,"JTAG write failed/busy");
        expect(0,ramBase+0x8000,0xcafebabe,2);
        dmi(0x38,2,(2U<<17)|(1U<<20)); dmi(0x39,2,ramBase+0x8000);
        while(dmi(0x38,1)&(1U<<21)) {}
        check(dmi(0x3c,1)==0xcafebabe,"JTAG independent readback mismatch");

        // Network RX is an independent producer, with a real held DDR response.
        access(0,0x10002030,true,ramBase+0x9000); access(0,0x10002038,true,8);
        access(0,0x10002040,true,1); holdB=true;
        for(unsigned i=0;i<2;++i) {
            dut.set_io$$ethernetStreams$$rxData$$bits$$data(i?0x76543210:0xfedcba98);
            dut.set_io$$ethernetStreams$$rxData$$bits$$keep(15);
            dut.set_io$$ethernetStreams$$rxData$$bits$$last(i==1);
            dut.set_io$$ethernetStreams$$rxData$$valid(1);
            do { tick(); } while(!dut.get_io$$ethernetStreams$$rxData$$ready());
        }
        dut.set_io$$ethernetStreams$$rxData$$valid(0);
        const uint32_t status[6]={0x50000000,0,0,64,0,8};
        for(unsigned i=0;i<6;++i) {
            dut.set_io$$ethernetStreams$$rxStatus$$bits$$data(status[i]);
            dut.set_io$$ethernetStreams$$rxStatus$$bits$$keep(15);
            dut.set_io$$ethernetStreams$$rxStatus$$bits$$last(i==5);
            dut.set_io$$ethernetStreams$$rxStatus$$valid(1);
            do { tick(); } while(!dut.get_io$$ethernetStreams$$rxStatus$$ready());
        }
        dut.set_io$$ethernetStreams$$rxStatus$$valid(0); finishHeldWrite(52);
        expect(0,0x10002048,2); expect(1,ramBase+0x9000,0x76543210fedcba98ULL);

        // TX reads must still visit Home and probe a dirty private owner.
        for(unsigned i=0;i<8;++i) memory[0x2000+i*8]=0xabc00000+i;
        dut.set_io$$tile$$coherent_1$$a$$bits$$opcode(6); dut.set_io$$tile$$coherent_1$$a$$bits$$param(1);
        dut.set_io$$tile$$coherent_1$$a$$bits$$size(6); dut.set_io$$tile$$coherent_1$$a$$bits$$address(ramBase+0x2000);
        dut.set_io$$tile$$coherent_1$$a$$valid(1);
        do { tick(); } while(!dut.get_io$$tile$$coherent_1$$a$$ready());
        dut.set_io$$tile$$coherent_1$$a$$valid(0); while(grants!=1 || ePending) tick(); privateDirty=true;
        captureNetworkTx=true;
        access(0,0x10002010,true,ramBase+0x2000); access(0,0x10002018,true,64);
        access(0,0x10002020,true,1);
        while(access(0,0x10002028,false,0)!=2) {}
        captureNetworkTx=false;
        check(probes==1 && networkControl==6 && networkTx.size()==16,"network TX skipped dirty Home owner");
        for(unsigned i=0;i<16;++i) check(networkTx[i]==uint32_t((dirtyBase+i/2)>>((i&1)*32)),
            "network TX independent dirty payload mismatch");
        idle(12); check(msi==1,"absent ordinary DMA generated unexpected IRQ4");
#endif
        idle(12); check(dut.get_io$$allObligationsIdle(),"DMA option retained obligation");
        check(axiWrites==axiB && reads.empty() && writes.empty() && writeReplies.empty(),
            "DMA option DDR ledger did not drain");
        std::cout<<"COMMON_MEMORY_DMA_OPTION_PASS enabled="<<ENABLE_MEMORY_COPY_DMA
                 <<" epochs="<<maintenance<<" msi="<<msi<<" cycles="<<cycles<<"\n";
#else
        throw std::runtime_error("ordinary DMA option mode requires network enabled");
#endif
    }
    // Static composition tests use the same DDR, register, MSI and coherent
    // service above. Expectations below are fixed public ABI values, not parsed RTL.
    void networkOptionRun() {
#if ENABLE_NETWORK
        throw std::runtime_error("network option mode requires network disabled");
#else
        check(ENABLE_JTAG==ENABLE_MEMORY_COPY_DMA,
            "network option batch supports both remaining producers on or both off");
        networkHoleMutation=inject; inject=false;
        expect(0,0x10000000,0xa5,0);
        const unsigned registersBefore=registerRequests, readsBefore=axiReads, writesBefore=axiWrites;
        unsigned holes=0;
        auto hole=[&](uint64_t address,unsigned size) {
            access(holes%2,address,false,0,size,false,0,false,true,true);
            access((holes+1)%2,address,true,0x5aULL<<((address&7)*8),size,false,0,false,true,true);
            ++holes;
        };
        // Every former 64-bit packet-DMA CSR and its two byte endpoints.
        for(unsigned offset=0;offset<256;offset+=8) hole(0x10002000ULL+offset,3);
        hole(0x10002000ULL,0); hole(0x100020ffULL,0);
        // Sparse GMAC aperture interior and boundary samples, not an exhaustive scan.
        for(unsigned offset : {0U,8U,0x1000U,0x10000U,0x20000U,0x3fff8U})
            hole(0x10040000ULL+offset,3);
        hole(0x10040000ULL,0); hole(0x1007ffffULL,0);
        idle(12);
        check(registerRequests==registersBefore && axiReads==readsBefore && axiWrites==writesBefore,
            "absent network aperture aliased another endpoint");
        check(!dut.get_io$$tile$$scalar_0$$response$$valid() &&
            !dut.get_io$$tile$$scalar_1$$response$$valid(),"network hole duplicated scalar reply");
        check(dut.get_io$$allObligationsIdle(),"network holes retained accepted owner");
#if ENABLE_MEMORY_COPY_DMA
        // Original ordinary-DMA copies, scalar dirty lookup, late DMA dirty probe,
        // reservation clear, retained B and two epoch checks remain unchanged.
        run(false);
        check(probes==2 && grants==2 && maintenance==2 && postStatusClears==1,
            "network-off ordinary DMA did not exercise dirty/drain path");
#else
        access(0,ramBase+0x100,true,0x0123456789abcdefULL);
        expect(1,ramBase+0x100,0x0123456789abcdefULL);
        expect(0,0x10080000,0x5678);
        // All optional producers really absent; ordinary DMA and JTAG stay holes.
        access(0,0x10001000,false,0,3,false,0,false,true,true);
        access(1,0x10003000,false,0,3,false,0,false,true,true);
        fence(61);
        do { tick(); } while(!dut.get_io$$tile$$fabricDrainedEpoch$$valid());
        for(unsigned n=0;n<8;++n) {
            check(dut.get_io$$tile$$fabricDrainedEpoch$$valid() &&
                dut.get_io$$tile$$fabricDrainedEpoch$$bits()==61,"zero-producer drain reply changed");
            tick();
        }
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(1); tick();
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(0); idle(8); ++maintenance;
        check(!dut.get_io$$tile$$fabricDrainedEpoch$$valid(),"zero-producer drain replayed");
#endif
#if ENABLE_JTAG
        access(0,0x10003008,true,1); // real SBA producer, not capability-only
        dmi(0x39,2,ramBase+0x8000); holdB=true;
        dmi(0x3c,2,0xcafebabe); finishHeldWrite(62);
        check((dmi(0x38,1)&((7U<<12)|(1U<<21)|(1U<<22)))==0,"network-off JTAG write failed/busy");
        expect(0,ramBase+0x8000,0xcafebabe,2);
        // Reacquire the same line, then require JTAG's read to probe the dirty owner.
        unsigned grantsBefore=grants, probesBefore=probes;
        dut.set_io$$tile$$coherent_1$$a$$valid(1);
        do { tick(); } while(!dut.get_io$$tile$$coherent_1$$a$$ready());
        dut.set_io$$tile$$coherent_1$$a$$valid(0);
        while(grants!=grantsBefore+1 || ePending) tick(); privateDirty=true;
        dmi(0x38,2,(2U<<17)|(1U<<20)); dmi(0x39,2,ramBase+0x2008);
        while(dmi(0x38,1)&(1U<<21)) {}
        check(dmi(0x3c,1)==1 && probes==probesBefore+1,
            "network-off JTAG dirty-owner independent readback mismatch");
#endif
        // Removed internal network sources must remain quiet; external source
        // numbers 5/6 remain usable (do not mask the shared APLIC input bits).
        access(0,0x0c000000,true,256,2);
        for(unsigned source : {5U,6U}) {
            const unsigned shift=(source&1)*32;
            access(0,0x0c000000+source*4,true,4ULL<<shift,2);
            access(0,0x0c003000+source*4,true,11ULL<<shift,2);
            access(0,0x0c001edc,true,uint64_t(source)<<32,2);
        }
        unsigned beforeMsi=msi;
        idle(40); check(msi==beforeMsi,"absent network generated unsolicited IRQ5/6");
        for(unsigned source : {5U,6U}) {
            dut.set_io$$sources(1U<<(source-1)); idle(30);
            dut.set_io$$sources(0); idle(12);
            check(msi==++beforeMsi,"network removal masked external IRQ5/6");
        }
        idle(20);
        check(dut.get_io$$allObligationsIdle(),"network option retained obligation");
        check(axiWrites==axiB && reads.empty() && writes.empty() && writeReplies.empty() && msiReplies.empty(),
            "network option response ledger did not drain");
        std::cout<<"COMMON_NETWORK_OPTION_PASS producers="<<ENABLE_MEMORY_COPY_DMA
                 <<" holes="<<holes<<" probes="<<probes<<" grants="<<grants
                 <<" epochs="<<maintenance<<" msi="<<msi<<" cycles="<<cycles<<"\n";
#endif
    }
    void program(unsigned index,uint32_t value) {
        dut.set_io$$program$$valid(1); dut.set_io$$program$$bits$$index(index); dut.set_io$$program$$bits$$data(value);
        tick(); dut.set_io$$program$$valid(0);
    }
    void fetch(uint64_t address,uint64_t expected,unsigned source,unsigned size=3,bool denied=false) {
        dut.set_io$$tile$$instructionFetch$$a$$bits$$address(address);
        dut.set_io$$tile$$instructionFetch$$a$$bits$$source(source);
        dut.set_io$$tile$$instructionFetch$$a$$bits$$size(size);
        dut.set_io$$tile$$instructionFetch$$a$$bits$$mask(((1U<<(1U<<size))-1U)<<(address&7));
        dut.set_io$$tile$$instructionFetch$$a$$valid(1); dut.set_io$$tile$$instructionFetch$$d$$ready(0);
        do {tick();} while(!dut.get_io$$tile$$instructionFetch$$a$$ready());
        dut.set_io$$tile$$instructionFetch$$a$$valid(0); idle(4); dut.set_io$$tile$$instructionFetch$$d$$ready(1);
        do {tick();} while(!dut.get_io$$tile$$instructionFetch$$d$$valid());
        check(dut.get_io$$tile$$instructionFetch$$d$$bits$$source()==source &&
            dut.get_io$$tile$$instructionFetch$$d$$bits$$size()==size &&
            dut.get_io$$tile$$instructionFetch$$d$$bits$$opcode()==1 &&
            dut.get_io$$tile$$instructionFetch$$d$$bits$$data()==expected &&
            bool(dut.get_io$$tile$$instructionFetch$$d$$bits$$denied())==denied &&
            !dut.get_io$$tile$$instructionFetch$$d$$bits$$corrupt(),"128KiB ROM/fetch source oracle mismatch");
        ++romReads; if(size<3) ++romSubwordReads; if(denied) ++romDenied;
    }
    void fence(unsigned tag) {
#ifdef RUNTIME_MAINTENANCE
        if(tag==37) {
            // External prepare races an older architectural FENCE.I. The
            // ordinary epoch must finish without consuming external epoch 38.
            dut.set_io$$tile$$maintenance$$ready(1);
            dut.set_io$$externalMaintenance$$bits$$epoch(38);
            dut.set_io$$externalMaintenance$$valid(1);
            do {tick();} while(!dut.get_io$$externalMaintenance$$ready());
            dut.set_io$$externalMaintenance$$valid(0);
            dut.set_io$$tile$$maintenance$$ready(0);
#ifdef RUNTIME_CANCELLATION
            ++runtimePrepares;
#endif
        }
        if(tag==38) {
            dut.set_io$$tile$$maintenanceStatus$$bits$$holdUntilResume(1);
            dut.set_io$$runtimeResume$$bits(tag); tick();
            check(!dut.get_io$$runtimeResume$$ready(), "early resume was ready before completion");
            if(runtimeNegative=="--early-resume") {
                dut.set_io$$runtimeResume$$bits(tag); dut.set_io$$runtimeResume$$valid(1);
                tick(); throw std::runtime_error("early resume assertion did not fire");
            }
        }
#endif
        dut.set_io$$tile$$maintenanceStatus$$bits$$epoch(tag); dut.set_io$$tile$$maintenanceStatus$$valid(1);
        do {tick();} while(!dut.get_io$$tile$$maintenanceStatus$$ready());
        dut.set_io$$tile$$maintenanceStatus$$valid(0);
    }
#ifdef RUNTIME_CANCELLATION
    void rejectCancel(unsigned tag) {
        dut.set_io$$runtimeCancel$$bits(tag); dut.set_io$$runtimeCancel$$valid(1);
        for(unsigned i=0;i<4;++i) { tick(); check(!dut.get_io$$runtimeCancel$$ready(), "invalid cancel was accepted"); }
        dut.set_io$$runtimeCancel$$valid(0);
    }
    void acceptCancel(unsigned tag) {
        dut.set_io$$runtimeCancel$$bits(tag); dut.set_io$$runtimeCancel$$valid(1);
        tick(); check(dut.get_io$$runtimeCancel$$ready(), "matching cancel was not accepted");
        dut.set_io$$runtimeCancel$$valid(0); ++runtimeCancels;
    }
    void prepareRuntime(unsigned tag) {
        dut.set_io$$tile$$maintenance$$ready(1);
        dut.set_io$$externalMaintenance$$bits$$epoch(tag); dut.set_io$$externalMaintenance$$valid(1);
        do {tick();} while(!dut.get_io$$externalMaintenance$$ready());
        dut.set_io$$externalMaintenance$$valid(0); dut.set_io$$tile$$maintenance$$ready(0); ++runtimePrepares;
        rejectCancel(tag-1);
        check(!dut.get_io$$tile$$maintenanceResume$$valid() && !dut.get_io$$runtimeComplete$$valid(),
              "stale cancel altered a new runtime owner");
    }
    void submitStatus(unsigned tag, bool hold) {
        dut.set_io$$tile$$maintenanceStatus$$bits$$holdUntilResume(hold);
        dut.set_io$$tile$$maintenanceStatus$$bits$$epoch(tag); dut.set_io$$tile$$maintenanceStatus$$valid(1);
        do {tick();} while(!dut.get_io$$tile$$maintenanceStatus$$ready());
        dut.set_io$$tile$$maintenanceStatus$$valid(0);
    }
    void consumeDrain(unsigned tag) {
        do {tick();} while(!dut.get_io$$tile$$fabricDrainedEpoch$$valid());
        check(dut.get_io$$tile$$fabricDrainedEpoch$$bits()==tag, "runtime drain epoch mismatch");
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(1); tick();
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(0);
    }
    void finishRuntimeRelease(unsigned tag, bool canceled, bool parkedAcquire=false) {
        do {tick();} while(!dut.get_io$$tile$$maintenanceResume$$valid());
        for(unsigned i=0;i<10;++i) {
            tick();
            check(dut.get_io$$tile$$maintenanceResume$$valid() &&
                  dut.get_io$$tile$$maintenanceResume$$bits()==tag, "held tile resume changed");
            check(dut.get_io$$maintenancePending() && !dut.get_io$$runtimeHeld$$valid() &&
                  !dut.get_io$$runtimeComplete$$valid(), "release queue opened Home or fabricated terminal");
            if(parkedAcquire) check(!dut.get_io$$tile$$coherent_1$$a$$ready(), "Home opened before tile resumed");
        }
        rejectCancel(tag); rejectCancel(tag-1);
        if(runtimeNegative=="--duplicate-resume") {
            dut.set_io$$runtimeResume$$bits(tag); dut.set_io$$runtimeResume$$valid(1); tick();
            throw std::runtime_error("duplicate resume assertion did not fire");
        }
        dut.set_io$$tile$$maintenanceResume$$ready(1); tick();
        check(dut.get_io$$tile$$maintenanceResume$$valid(), "tile resume handshake disappeared"); ++tileResumes;
        dut.set_io$$tile$$maintenanceResume$$ready(0);
        for(unsigned i=0;i<8;++i) {
            tick(); check(dut.get_io$$maintenancePending() && !dut.get_io$$runtimeComplete$$valid() &&
                          !dut.get_io$$tile$$maintenanceResume$$valid(), "resume dequeue released Home or replayed");
            if(parkedAcquire) check(!dut.get_io$$tile$$coherent_1$$a$$ready(), "Home opened before resumed ACK");
        }
        // A delayed or stale acknowledgement cannot release the external owner.
        dut.set_io$$tile$$maintenanceResumed$$bits(tag-1); dut.set_io$$tile$$maintenanceResumed$$valid(1);
        tick(); check(!dut.get_io$$tile$$maintenanceResumed$$ready() && !dut.get_io$$runtimeComplete$$valid(),
                      "stale resumed ACK released runtime owner");
        dut.set_io$$tile$$maintenanceResumed$$bits(tag); tick();
        check(dut.get_io$$tile$$maintenanceResumed$$ready(), "matching resumed ACK was not accepted"); ++tileResumed;
        dut.set_io$$tile$$maintenanceResumed$$valid(0);
        if(parkedAcquire) {
            do {tick();} while(!dut.get_io$$tile$$coherent_1$$a$$ready());
            dut.set_io$$tile$$coherent_1$$a$$valid(0);
            while(grants!=3 || ePending) tick();
        }
        do {tick();} while(!dut.get_io$$runtimeComplete$$valid());
        // Even after CPU release, a new external prepare must wait for terminal
        // consumption. Ordinary FENCE status, unlike prepare, may still drain.
        dut.set_io$$tile$$maintenance$$ready(1);
        dut.set_io$$externalMaintenance$$bits$$epoch(tag+1); dut.set_io$$externalMaintenance$$valid(1);
        for(unsigned i=0;i<12;++i) {
            tick();
            check(dut.get_io$$runtimeComplete$$valid() && dut.get_io$$runtimeComplete$$bits$$epoch()==tag &&
                  bool(dut.get_io$$runtimeComplete$$bits$$canceled())==canceled, "terminal changed under backpressure");
            check(!dut.get_io$$externalMaintenance$$ready() && !dut.get_io$$tile$$maintenance$$valid(),
                  "new prepare crossed unconsumed terminal");
            check(!dut.get_io$$maintenancePending() && !dut.get_io$$runtimeHeld$$valid(),
                  "resumed epoch still held Home");
        }
        dut.set_io$$externalMaintenance$$valid(0); dut.set_io$$tile$$maintenance$$ready(0);
        if(tag==50) {
            submitStatus(91, false); consumeDrain(91); idle(3);
            check(dut.get_io$$runtimeComplete$$valid() && dut.get_io$$runtimeComplete$$bits$$epoch()==tag &&
                  bool(dut.get_io$$runtimeComplete$$bits$$canceled())==canceled,
                  "ordinary FENCE corrupted held runtime terminal");
        }
        rejectCancel(tag);
        dut.set_io$$runtimeComplete$$ready(1); tick();
        check(dut.get_io$$runtimeComplete$$valid(), "terminal handshake disappeared"); ++terminals;
        dut.set_io$$runtimeComplete$$ready(0); idle(3);
        check(!dut.get_io$$runtimeComplete$$valid() && !dut.get_io$$tile$$maintenanceResume$$valid(),
              "runtime terminal or tile resume replayed");
        rejectCancel(tag);
        dut.set_io$$tile$$maintenanceStatus$$bits$$holdUntilResume(0);
        // Real scalar traffic continues with its owner, response and data intact.
        access(0,ramBase+0x7000,true,0xabc00000ULL+tag); expect(1,ramBase+0x7000,0xabc00000ULL+tag);
    }
    void cancellationCases() {
        rejectCancel(50); // idle: no matching external owner yet.
        prepareRuntime(50); acceptCancel(50); rejectCancel(50);
        submitStatus(50, false); consumeDrain(50); idle(6);
        check(!dut.get_io$$tile$$maintenanceResume$$valid() && !dut.get_io$$runtimeComplete$$valid(),
              "early cancel released an older ordinary FENCE instead of runtime owner");
        submitStatus(50, true); consumeDrain(50); finishRuntimeRelease(50, true);

        // A real accepted DMA write and its final AXI B response are retained.
        prepareRuntime(51);
        access(0,0x10001000,true,ramBase+0x4000); access(0,0x10001008,true,ramBase+0x8000);
        access(0,0x10001010,true,64); holdB=true; access(0,0x10001018,true,1);
        submitStatus(51, true);
        while(writeReplies.empty()) tick();
        acceptCancel(51); rejectCancel(51);
        for(unsigned i=0;i<40;++i) {
            tick(); check(!dut.get_io$$tile$$fabricDrainedEpoch$$valid() &&
                          !dut.get_io$$tile$$maintenanceResume$$valid() && !dut.get_io$$runtimeComplete$$valid(),
                          "cancel fabricated success while AXI B owner remained stalled");
        }
        check(axiWrites>axiB && !writeReplies.empty(), "cancel erased the real stalled DDR owner");
        holdB=false; consumeDrain(51); finishRuntimeRelease(51, true);
        for(unsigned i=0;i<8;++i) expect(i&1,ramBase+0x8000+i*8,0x1234567800000000ULL+i);

        // Cancel on the same edge as the real fabric completion handshake;
        // prior completionConsumed is still false, so release cannot go early.
        prepareRuntime(52); submitStatus(52, true);
        do {tick();} while(!dut.get_io$$tile$$fabricDrainedEpoch$$valid());
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(1); acceptCancel(52);
        check(!dut.get_io$$tile$$maintenanceResume$$valid() && !dut.get_io$$runtimeComplete$$valid(),
              "same-edge cancel bypassed real drain consumption");
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(0); finishRuntimeRelease(52, true);

        prepareRuntime(53); submitStatus(53, true); consumeDrain(53); idle(3);
        dut.set_io$$runtimeResume$$bits(53); dut.set_io$$runtimeResume$$valid(1);
        acceptCancel(53);
        check(!dut.get_io$$runtimeResume$$ready(), "simultaneous cancel did not win over normal resume");
        dut.set_io$$runtimeResume$$valid(0); finishRuntimeRelease(53, true);

        prepareRuntime(54); submitStatus(54, true); consumeDrain(54); idle(3);
        dut.set_io$$runtimeCancel$$bits(53); dut.set_io$$runtimeCancel$$valid(1);
        dut.set_io$$runtimeResume$$bits(54); dut.set_io$$runtimeResume$$valid(1); tick();
        check(!dut.get_io$$runtimeCancel$$ready() && dut.get_io$$runtimeResume$$ready(),
              "wrong cancel blocked valid normal resume"); ++runtimeResumes;
        dut.set_io$$runtimeCancel$$valid(0); dut.set_io$$runtimeResume$$valid(0); finishRuntimeRelease(54, false);

        prepareRuntime(55); submitStatus(55, true); consumeDrain(55); idle(8);
        check(dut.get_io$$runtimeHeld$$valid() && dut.get_io$$runtimeHeld$$bits()==55, "held cancel fixture not held");
        acceptCancel(55); finishRuntimeRelease(55, true);
        check(runtimePrepares==7 && runtimeCancels==5 && runtimeResumes==2 && tileResumes==7 &&
              tileResumed==7 && terminals==7, "runtime cancellation exact-count ledger mismatch");
        std::cout<<"RUNTIME_CANCELLATION_PASS prepares="<<runtimePrepares<<" cancels="<<runtimeCancels
                 <<" normal_resumes="<<runtimeResumes<<" tile_resumes="<<tileResumes<<" resumed_acks="<<tileResumed
                 <<" terminals="<<terminals<<" older_fence=1 equal_numeric_epoch=1 actual_ddr_stall=1 simultaneous=1 terminal_backpressure=1"
                 <<" terminal_fence=1 stale_duplicate_reject=1 resumed_traffic=1\n";
    }
#endif
    void run(bool report=true) {
        program(0,0x11223344); program(1,0x55667788); program(32766,0xdecafbad); program(32767,0x89abcdef);
        fetch(0x80000000,0x5566778811223344ULL,15); fetch(0x8001fff8,0x89abcdefdecafbadULL,9);
        // I1's separately authorized fetchSpan reuses the containing 64-bit
        // word after a narrow Get. Both nonzero banks must arrive, including
        // when the original TL extent selects only the upper bank.
        for(unsigned size=0;size<3;++size) {
            fetch(0x80000000,0x5566778811223344ULL,3+size,size);
            fetch(0x80000004,0x5566778811223344ULL,6+size,size);
        }
        fetch(0x8001fffc,0x89abcdefdecafbadULL,10,2);
        fetch(0x80020000,0,11,2,true); fetch(0x80020000,0,12,3,true);
        expect(0,0x80000000,0x5566778811223344ULL);
        expect(0,0x80000000,0x5566778811223344ULL,1);
        expect(0,0x80000004,0x5566778811223344ULL,2);
        access(1,ramBase+0x100,true,0x0123456789abcdefULL); expect(0,ramBase+0x100,0x0123456789abcdefULL);
        expect(0,0x10000000,0xa5,0);
#if ENABLE_NETWORK
        expect(1,0x10060000,0x1234);
#endif
        expect(0,0x10080000,0x5678);
        access(0,0x0200bff8,true,100); dut.set_io$$timerTick(1); idle(7); dut.set_io$$timerTick(0);
        expect(1,0x0200bff8,107); access(0,0x02004000,true,106); idle(3);
        check(dut.get_io$$tile$$timerInterrupt() && !dut.get_io$$tile$$softwareInterrupt(),"fabric timer/software interrupt mismatch");
        // Existing APLIC/IMSIC addresses, routed through the common scalar MMIO fabric.
        access(0,0x0c000000,true,256,2); access(0,0x0c00000c,true,4ULL<<32,2);
        access(0,0x0c00300c,true,11ULL<<32,2); access(0,0x0c001edc,true,3ULL<<32,2);
        access(0,0x0c001cdc,true,3ULL<<32,2); idle(20); check(msi==1,"APLIC request did not reach tile MSI");
        // A real LR owns its reply before an ordered clear; the following SC must fail.
        check(access(1,ramBase+0x100,false,0,3,true,2)==0x0123456789abcdefULL,"LR value mismatch");
        access(1,0,false,0,3,false,0,true); check(access(1,ramBase+0x100,true,0xf00d,3,true,3)==1,"SC crossed reservation clear");
        expect(0,ramBase+0x100,0x0123456789abcdefULL);
        // Dirty private ownership must be looked up for an uncached/PTW-style read.
        for(unsigned i=0;i<8;++i) memory[0x2000+i*8]=0xabc00000+i;
        dut.set_io$$tile$$coherent_1$$a$$bits$$opcode(6); dut.set_io$$tile$$coherent_1$$a$$bits$$param(1);
        dut.set_io$$tile$$coherent_1$$a$$bits$$size(6); dut.set_io$$tile$$coherent_1$$a$$bits$$address(ramBase+0x2000);
        dut.set_io$$tile$$coherent_1$$a$$valid(1);
        do {tick();} while(!dut.get_io$$tile$$coherent_1$$a$$ready());
        dut.set_io$$tile$$coherent_1$$a$$valid(0); while(grants!=1 || ePending) tick(); privateDirty=true;
        expect(1,ramBase+0x2000,dirtyBase); check(probes==1,"scalar provenance skipped dirty owner lookup");
        for(unsigned i=0;i<8;++i) check(memory[0x2000+i*8]==dirtyBase+i,"dirty writeback lost real DDR data");
        for(unsigned i=0;i<8;++i) access(i&1,ramBase+0x4000+i*8,true,0x1234567800000000ULL+i);
        access(0,0x10001000,true,ramBase+0x4000); access(0,0x10001008,true,ramBase+0x5000);
        access(0,0x10001010,true,64); holdB=true; access(0,0x10001018,true,1); fence(37);
        idle(25); check(!dut.get_io$$tile$$fabricDrainedEpoch$$valid(),"maintenance acknowledged pending DMA DDR write");
        dut.set_io$$transportCpuEmptySynchronized(0); holdB=false; idle(180);
        check(!dut.get_io$$tile$$fabricDrainedEpoch$$valid(),"maintenance ignored CPU crossing owners");
        dut.set_io$$transportCpuEmptySynchronized(1); dut.set_io$$fabricTransportEmpty(0); idle(20);
        check(!dut.get_io$$tile$$fabricDrainedEpoch$$valid(),"maintenance ignored fabric crossing owners");
        dut.set_io$$fabricTransportEmpty(1);
        do {tick();} while(!dut.get_io$$tile$$fabricDrainedEpoch$$valid());
        for(unsigned i=0;i<8;++i) {
            check(dut.get_io$$tile$$fabricDrainedEpoch$$bits()==37,"held maintenance epoch changed"); tick();
        }
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(1); tick(); dut.set_io$$tile$$fabricDrainedEpoch$$ready(0); ++maintenance;
        expect(0,0x10001020,2);
        for(unsigned i=0;i<8;++i) expect(i&1,ramBase+0x5000+i*8,0x1234567800000000ULL+i);
        // Older DMA can emit a coherence probe after tile-ready. The tile's
        // resulting reservation-clear event is protocol completion traffic and
        // must keep draining despite a pending maintenance epoch.
        dut.set_io$$tile$$coherent_1$$a$$valid(1);
        do {tick();} while(!dut.get_io$$tile$$coherent_1$$a$$ready());
        dut.set_io$$tile$$coherent_1$$a$$valid(0);
        while(grants!=2 || ePending) tick(); privateDirty=true;
        access(0,0x10001000,true,ramBase+0x2000); access(0,0x10001008,true,ramBase+0x6000);
        access(0,0x10001010,true,64);
        holdProbe=true; holdB=true; access(0,0x10001018,true,1); fence(38);
        probeClearEnabled=true; holdProbe=false; idle(25);
        check(postStatusClears==1 && !autoClearRequested,
            "post-status probe clear was blocked by maintenance admission");
        check(!dut.get_io$$tile$$fabricDrainedEpoch$$valid(), "late-probe epoch ignored pending DDR write");
        holdB=false; do {tick();} while(!dut.get_io$$tile$$fabricDrainedEpoch$$valid());
        check(dut.get_io$$tile$$fabricDrainedEpoch$$bits()==38,"stale drain epoch replayed");
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(1); tick(); dut.set_io$$tile$$fabricDrainedEpoch$$ready(0); ++maintenance;
#ifdef RUNTIME_MAINTENANCE
        // Completion consumption must not reopen Home or regenerate completion.
        idle(12);
        check(dut.get_io$$runtimeHeld$$valid() && dut.get_io$$runtimeHeld$$bits()==38 &&
              dut.get_io$$maintenancePending(), "runtime completion released the epoch barrier");
        check(!dut.get_io$$tile$$fabricDrainedEpoch$$valid(), "runtime completion replayed");
        // A newer Acquire must park at Home, without acquiring an owner.
        dut.set_io$$tile$$coherent_1$$a$$valid(1);
        for(unsigned i=0;i<12;++i) {
            tick(); check(!dut.get_io$$tile$$coherent_1$$a$$ready(), "held Home accepted a newer Acquire");
            check(dut.get_io$$runtimeHeld$$valid(), "runtime hold vanished without resume");
        }
        // Keep the parked Decoupled offer stable until actual acceptance.
        dut.set_io$$runtimeResume$$bits(37); tick();
        check(!dut.get_io$$runtimeResume$$ready() && dut.get_io$$runtimeHeld$$valid(),
              "stale resume epoch could release the barrier");
        dut.set_io$$runtimeResume$$bits(runtimeNegative=="--wrong-resume" ? 37 : 38);
        dut.set_io$$runtimeResume$$valid(1); tick();
        if(runtimeNegative=="--wrong-resume") throw std::runtime_error("wrong resume assertion did not fire");
        check(dut.get_io$$runtimeResume$$ready(), "matching runtime resume was not accepted");
        dut.set_io$$runtimeResume$$valid(0);
#ifdef RUNTIME_CANCELLATION
        ++runtimeResumes;
        finishRuntimeRelease(38, false, true);
#else
        do {tick();} while(!dut.get_io$$tile$$coherent_1$$a$$ready());
        dut.set_io$$tile$$coherent_1$$a$$valid(0);
        while(grants!=3 || ePending) tick();
        idle(8);
        check(!dut.get_io$$runtimeHeld$$valid() && !dut.get_io$$maintenancePending(),
              "matching resume did not release the barrier");
        check(dut.get_io$$tile$$maintenanceResume$$valid() &&
              dut.get_io$$tile$$maintenanceResume$$bits()==38, "tile resume owner was not held");
        check(!dut.get_io$$externalMaintenance$$ready() && !dut.get_io$$tile$$maintenanceStatus$$ready(),
              "new maintenance crossed queued tile resume");
        check(!dut.get_io$$runtimeResume$$ready(), "duplicate resume could be accepted");
        if(runtimeNegative=="--duplicate-resume") {
            dut.set_io$$runtimeResume$$valid(1); tick();
            throw std::runtime_error("duplicate resume assertion did not fire");
        }
        dut.set_io$$tile$$maintenanceResume$$ready(1); tick();
        dut.set_io$$tile$$maintenanceResume$$ready(0); idle(2);
        check(!dut.get_io$$tile$$maintenanceResume$$valid(), "tile resume replayed");
#endif
        dut.set_io$$tile$$maintenanceStatus$$bits$$holdUntilResume(0);
#endif
        for(unsigned i=0;i<8;++i) expect(i&1,ramBase+0x6000+i*8,dirtyBase+i);
#ifdef RUNTIME_MAINTENANCE
        // A normal FENCE still auto-releases after the runtime epoch.
        fence(39); do {tick();} while(!dut.get_io$$tile$$fabricDrainedEpoch$$valid());
        check(dut.get_io$$tile$$fabricDrainedEpoch$$bits()==39, "post-runtime epoch mismatch");
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(1); tick();
        dut.set_io$$tile$$fabricDrainedEpoch$$ready(0); idle(2);
        check(!dut.get_io$$maintenancePending() && !dut.get_io$$runtimeHeld$$valid(),
              "ordinary FENCE inherited runtime hold");
        std::cout<<"RUNTIME_EPOCH_HOLD_PASS held=1 acquire_blocked=1 explicit_resume=1 fence_after=1\n";
#endif
#ifdef RUNTIME_CANCELLATION
        cancellationCases();
#endif
        idle(8); check(dut.get_io$$allObligationsIdle(),"fabric retained an accepted obligation");
        check(axiWrites==axiB && reads.empty() && writes.empty() && writeReplies.empty(),"DDR real response ledger mismatch");
        if(report) std::cout<<"COMMON_MACHINE_FABRIC_PASS cycles="<<cycles<<" scalar="<<scalarReplies<<" rom="<<romReads
                 <<" rom_subword="<<romSubwordReads<<" rom_denied="<<romDenied
                 <<" axi_reads="<<axiReads<<" axi_writes="<<axiWrites<<" axi_b="<<axiB<<" registers="<<registerRequests
                 <<" msi="<<msi<<" probes="<<probes<<" grants="<<grants<<" clear="<<clearReplies
                 <<" epochs="<<maintenance<<" dma_words=16 post_status_clear="<<postStatusClears<<"\n";
    }
};
int main(int argc,char**argv) {
    try {
        auto d=std::make_unique<Driver>();
        if(argc>1 && std::string(argv[1])=="--network-option-only") {
            check(argc==2 || (argc==3 && std::string(argv[2])=="--inject-mismatch"),
                "unexpected network option test arguments");
            d->inject=argc==3; d->networkOptionRun();
        } else if(argc>1 && std::string(argv[1])=="--memory-dma-option-only") {
            check(argc==2 || (argc==3 && std::string(argv[2])=="--inject-mismatch"),
                "unexpected memory DMA option test arguments");
            d->inject=argc==3; d->memoryDmaOptionRun();
        } else if(argc>1 && std::string(argv[1])=="--jtag-option-only") {
            check(argc==2 || (argc==3 && std::string(argv[2])=="--inject-mismatch"),
                "unexpected JTAG option test arguments");
            d->inject=argc==3; d->jtagOptionRun();
        } else {
            d->inject=argc>1 && std::string(argv[1])=="--inject-mismatch";
            d->runtimeNegative=argc>1 ? argv[1] : ""; d->run();
        }
    }
    catch(const std::exception& e) { std::cerr<<e.what()<<"\n"; return 1; }
}
