// Reuse the finite protocol driver, not its expected-result model.
#define main aia_guest_legacy_main
#include "aia_guest.cpp"
#undef main

constexpr uint64_t machineDomain=0x0c000000,supervisorDomain=0x0c004000;
static void configure(Driver&t,bool supervisor,unsigned source,unsigned identity){
    const unsigned port=supervisor?1:0;
    const uint64_t base=supervisor?supervisorDomain:machineDomain;
    if(supervisor)t.bus(0,machineDomain+4*source,true,0x400);
    t.bus(port,base+4*source,true,1);
    t.bus(port,base+0x3000+4*source,true,(supervisor?((source%2+1)<<12):0)|identity);
    t.bus(port,base+0x1edc,true,source);t.bus(port,base,true,256);
    t.bus(port,base+0x1cdc,true,source);t.idle();
}
static void mirrored(bool olderSupervisor,bool negative){
    Driver t(false);t.allow=false;
    configure(t,olderSupervisor,1,11);configure(t,olderSupervisor,2,12);
    const unsigned olderPort=olderSupervisor?1:0,genPort=1-olderPort;
    const uint64_t olderBase=olderSupervisor?supervisorDomain:machineDomain;
    const uint64_t genBase=olderSupervisor?machineDomain:supervisorDomain;
    check(t.bus(olderPort,olderBase+0x1c00,false)==0,"older MSIs not irrevocably forwarded");
    // Configuration revocation cannot make either queued older MSI disappear.
    for(unsigned source:{1,2})t.bus(0,machineDomain+4*source,true,0);
    t.bus(genPort,genBase+0x3000,true,13);
    check(t.bus(genPort,genBase+0x3000,false)==0x100d,"cross-domain genmsi not busy");
    t.bus(genPort,genBase+0x3000,true,14);
    check(t.bus(genPort,genBase+0x3000,false)==0x100d,"busy genmsi replaced during global drain");
    // A new real edge during synchronization stays pending, then forwards once.
    if(olderSupervisor)t.bus(0,machineDomain+12,true,0x400);
    t.bus(olderPort,olderBase+12,true,4);
    t.bus(olderPort,olderBase+0x300c,true,(olderSupervisor?0x1000:0)|15);
    t.bus(olderPort,olderBase+0x1edc,true,3);
    t.d.set_io$$sources(4);t.idle();
    check(t.bus(olderPort,olderBase+0x1c00,false)==8,"pause lost new pending edge");
    t.d.set_io$$allowMsiResponse(0);t.allow=true;t.idle(30);
    check(t.sent.size()==2&&t.sent[0].data==11&&t.sent[1].data==12,"old-domain output ordering");
    check(t.bus(genPort,genBase+0x3000,false)==0x100d,"genmsi bypassed outstanding responses");
    t.d.set_io$$allowMsiResponse(1);t.idle(30);
    check(t.sent.size()==4&&t.sent[negative?1:2].data==13,"independent cross-domain genmsi order");
    check(t.sent[2].address==(genPort?0x28000000:0x24000000),"generated MSI own domain address");
    check(t.bus(genPort,genBase+0x3000,false)==13,"genmsi busy did not retire");
    check(t.sent[3].data==15,"new edge bypassed synchronization or was lost");
    t.idle();check(t.sent.size()==4,"new held edge forwarded more than once");
    std::cout<<"GENMSI_MIRROR_PASS older="<<(olderSupervisor?'S':'M')<<" cycles="<<t.cycle<<"\n";
}
static void simultaneous(){
    Driver t(false);t.allow=false;
    configure(t,false,1,21);configure(t,false,2,22);
    configure(t,true,3,23);configure(t,true,4,24);
    check(t.bus(0,machineDomain+0x1c00,false)==0&&t.bus(1,supervisorDomain+0x1c00,false)==0,
          "dual-domain old queues not full");
#define OFFER(name,base,id) \
    t.d.set_io$$##name##$$request$$valid(1); \
    t.d.set_io$$##name##$$request$$bits$$address(base+0x3000); \
    t.d.set_io$$##name##$$request$$bits$$write(1);t.d.set_io$$##name##$$request$$bits$$data(id); \
    t.d.set_io$$##name##$$request$$bits$$size(2);t.d.set_io$$##name##$$request$$bits$$byteEnable(15)
    OFFER(machine,machineDomain,13);OFFER(supervisor,supervisorDomain,14);t.tick();
#undef OFFER
    check(t.d.get_io$$machine$$request$$ready()&&t.d.get_io$$supervisor$$request$$ready(),
          "simultaneous genmsi writes not accepted");t.idle(3);
    check(t.bus(0,machineDomain+0x3000,false)==0x100d&&t.bus(1,supervisorDomain+0x3000,false)==0x100e,
          "simultaneous genmsi busy owners");
    t.d.set_io$$allowMsiResponse(0);t.allow=true;t.idle(30);
    for(auto m:t.sent)check(m.data>=21&&m.data<=24,"genmsi overtook blocked old response");
    t.d.set_io$$allowMsiResponse(1);t.idle(50);
    check(t.sent.size()==6,"simultaneous generated MSI count");
    unsigned seen=0;for(unsigned i=0;i<4;++i){check(t.sent[i].data>=21&&t.sent[i].data<=24,"old dual-domain prefix");seen|=1U<<(t.sent[i].data-21);}
    check(seen==15,"old dual-domain identities lost/duplicated");
    check((t.sent[4].data==13&&t.sent[5].data==14)||(t.sent[4].data==14&&t.sent[5].data==13),
          "simultaneous genmsi suffix");
    // Forwarding resumes after synchronization; no sticky global pause remains.
    t.bus(0,machineDomain+0x1cdc,true,1);t.idle();check(t.sent.size()==7&&t.sent.back().data==21,"forwarding did not resume");
    std::cout<<"GENMSI_SIMULTANEOUS_PASS msis=7 cycles="<<t.cycle<<"\n";
}
int main(int argc,char**argv){try{
    mirrored(true,argc>1);mirrored(false,false);simultaneous();
    std::cout<<"AIA_GENMSI_ORDER_PASS mirrored=2 simultaneous=1 held_responses=1 busy_ignore=1 revoked_queues=1\n";
}catch(const std::exception&e){std::cerr<<"AIA_GENMSI_ORDER_FAIL "<<e.what()<<'\n';return 1;}}
