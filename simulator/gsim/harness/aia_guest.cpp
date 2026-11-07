#include "AiaGuestGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
struct Message { uint64_t address, data; };
struct Driver {
    SAiaGuestGsim d;
    std::vector<Message> sent;
    bool allow = true;
    bool wrongAddress = false;
    unsigned cycle = 0;
    Driver(bool negative) : wrongAddress(negative) {
        d.set_io$$sources(0); d.set_io$$allowMsi(1); d.set_io$$allowMsiResponse(1);
        defaults(); d.set_reset(1); tick(); tick(); d.set_reset(0); idle(3);
    }
    void defaults() {
        d.set_io$$machine$$request$$valid(0); d.set_io$$machine$$response$$ready(1);
        d.set_io$$supervisor$$request$$valid(0); d.set_io$$supervisor$$response$$ready(1);
        d.set_io$$injection$$request$$valid(0); d.set_io$$injection$$response$$ready(1);
        d.set_io$$csrRequest$$valid(0); d.set_io$$csrResponse$$ready(1);
    }
    void tick() {
        d.set_io$$allowMsi(allow); d.step(); ++cycle;
        if (d.get_io$$msiFire()) sent.push_back({d.get_io$$msiAddress(),d.get_io$$msiData()});
        check(!d.get_io$$msiError(), "unexpected MSI bus error");
    }
    void idle(unsigned count = 12) { defaults(); while (count--) tick(); }
    uint64_t bus(unsigned port, uint64_t address, bool write, uint64_t data = 0,
                 bool expectError = false, unsigned size = 2, unsigned mask = 15) {
        bool accepted = false;
        for (unsigned n = 0; n < 200; ++n) {
#define DRIVE(name) \
            d.set_io$$##name##$$request$$valid(!accepted); \
            d.set_io$$##name##$$request$$bits$$address(address); \
            d.set_io$$##name##$$request$$bits$$write(write); \
            d.set_io$$##name##$$request$$bits$$size(size); \
            d.set_io$$##name##$$request$$bits$$data(data); \
            d.set_io$$##name##$$request$$bits$$byteEnable(mask)
            switch (port) { case 0: DRIVE(machine); break; case 1: DRIVE(supervisor); break;
                default: DRIVE(injection); break; }
#undef DRIVE
            tick();
            bool ready, valid, error; uint64_t value;
#define SAMPLE(name) \
            ready = d.get_io$$##name##$$request$$ready(); \
            valid = d.get_io$$##name##$$response$$valid(); \
            error = d.get_io$$##name##$$response$$bits$$error(); \
            value = d.get_io$$##name##$$response$$bits$$data()
            switch (port) { case 0: SAMPLE(machine); break; case 1: SAMPLE(supervisor); break;
                default: SAMPLE(injection); break; }
#undef SAMPLE
            if (!accepted && ready) accepted = true;
            if (valid) { check(accepted && error == expectError, "MMIO completion/error mismatch");
                defaults(); return value; }
        }
        throw std::runtime_error("MMIO timeout");
    }
    uint64_t csr(unsigned file, unsigned selector, unsigned op = 0, uint64_t data = 0,
                 bool topei = false, bool expectError = false, unsigned hold = 0) {
        bool accepted = false; bool heldValid = false; uint64_t heldValue = 0;
        for (unsigned n = 0; n < 200; ++n) {
            d.set_io$$csrRequest$$valid(!accepted);
            d.set_io$$csrRequest$$bits$$file(file); d.set_io$$csrRequest$$bits$$selector(selector);
            d.set_io$$csrRequest$$bits$$operation(op); d.set_io$$csrRequest$$bits$$data(data);
            d.set_io$$csrRequest$$bits$$topei(topei); d.set_io$$csrResponse$$ready(n >= hold);
            tick();
            if (!accepted && d.get_io$$csrRequest$$ready()) accepted = true;
            if (d.get_io$$csrResponse$$valid()) {
                const uint64_t value = d.get_io$$csrResponse$$bits$$data();
                check(accepted && bool(d.get_io$$csrResponse$$bits$$error()) == expectError,
                      "CSR completion/error mismatch");
                if (heldValid) check(value == heldValue, "CSR response changed under backpressure");
                if (n >= hold) { defaults(); return value; }
                heldValid = true; heldValue = value;
            }
        }
        throw std::runtime_error("CSR timeout");
    }
    uint64_t revokeRead(unsigned source, unsigned childOffset) {
        // Launch the child read in the very next cycle after root write accepts,
        // without waiting for the root response or allowing a cleanup cycle.
        d.set_io$$machine$$request$$valid(1);
        d.set_io$$machine$$request$$bits$$address(0x0c000000+4*source);
        d.set_io$$machine$$request$$bits$$write(1); d.set_io$$machine$$request$$bits$$data(0);
        d.set_io$$machine$$request$$bits$$size(2); d.set_io$$machine$$request$$bits$$byteEnable(15);
        tick(); check(d.get_io$$machine$$request$$ready(),"revocation write unexpectedly blocked");
        d.set_io$$machine$$request$$valid(0);
        d.set_io$$supervisor$$request$$valid(1);
        d.set_io$$supervisor$$request$$bits$$address(0x0c004000+childOffset);
        d.set_io$$supervisor$$request$$bits$$write(0);
        d.set_io$$supervisor$$request$$bits$$size(2); d.set_io$$supervisor$$request$$bits$$byteEnable(15);
        tick(); check(d.get_io$$supervisor$$request$$ready(),"immediate child read unexpectedly blocked");
        d.set_io$$supervisor$$request$$valid(0);
        for(unsigned n=0;n<20;++n) {
            tick();
            if(d.get_io$$supervisor$$response$$valid()) {
                check(!d.get_io$$supervisor$$response$$bits$$error(),"immediate child read error");
                return d.get_io$$supervisor$$response$$bits$$data();
            }
        }
        throw std::runtime_error("immediate child read timeout");
    }
    void expect(unsigned index, unsigned guest, unsigned id, bool machine = false) {
        check(index < sent.size(), "expected MSI not forwarded");
        uint64_t address = machine ? 0x24000000 : 0x28000000 + (uint64_t(guest) << 12);
        if (wrongAddress && guest) address ^= 0x1000;
        check(sent[index].address == address && sent[index].data == id,
              "independent guest MSI destination oracle");
    }
};

#ifdef AIA_GUEST_BOUNDARY
static void boundary(Driver &t) {
    constexpr unsigned guests=AIA_GUEST_BOUNDARY;
    constexpr uint64_t M=0x0c000000,S=0x0c004000,I=0x28000000;
    unsigned bits=0,pages=1;while(pages<guests+1){pages*=2;++bits;}
    check(t.bus(0,M+0x1bcc,false)==uint64_t(bits)<<20,"boundary guest geometry");
    t.bus(0,M+4,true,0x400);t.bus(1,S+4,true,1);
    t.bus(1,S+0x1edc,true,1);t.bus(1,S,true,0x100);
    for(unsigned guest=0;guest<=guests;++guest) {
        const unsigned file=guest+1,id=guest%63+1;
        t.csr(file,0xc0,1,UINT64_MAX);t.csr(file,0x70,1,1);
        t.bus(1,S+0x3004,true,(guest<<12)|id);
        check(t.bus(1,S+0x3004,false)==((guest<<12)|id),"boundary GuestIndex readback");
        t.bus(1,S+0x1cdc,true,1);t.idle();t.expect(guest,guest,id);
        check(t.d.get_io$$interrupts()==(static_cast<unsigned __int128>(1)<<file),
              "boundary file IRQ isolation including bit64");
        check(t.csr(file,0,1,0,true,false,5)==uint64_t(id)*0x10001,
              "boundary guest claim");t.idle(2);
        check(t.d.get_io$$interrupts()==0,"boundary claim did not clear IRQ");
    }
    if(guests<63) {
        t.bus(1,S+0x3004,true,((guests+1)<<12)|17);
        check(t.bus(1,S+0x3004,false)==((guests<<12)|17),"boundary invalid GuestIndex WLRL");
    }
    // Snapshot the last valid guest index even while software retargets to S.
    t.bus(1,S+0x3004,true,(guests<<12)|63);t.allow=false;
    t.bus(1,S+0x1cdc,true,1);t.idle();
    check(t.d.get_io$$msiValid(),"boundary MSI did not stall");
    const auto address=t.d.get_io$$msiAddress(),data=t.d.get_io$$msiData();
    t.bus(1,S+0x3004,true,31);t.idle();
    check(t.d.get_io$$msiAddress()==address&&t.d.get_io$$msiData()==data,"boundary queued guest changed");
    t.allow=true;t.idle();t.expect(guests+1,guests,63);
    check(t.csr(guests+1,0,1,0,true)==UINT64_C(0x3f003f),"boundary last guest claim");
    t.bus(1,S+0x3000,true,(guests<<12)|31);t.idle();t.expect(guests+2,0,31);
    check(t.csr(1,0,1,0,true)==UINT64_C(0x1f001f),"boundary genmsi must target own S file");
    for(unsigned page=guests+1;page<pages;++page) {
        t.bus(2,I+4096*page,true,19);check(t.bus(2,I+4096*page,false)==0,"boundary padding page");
    }
    t.csr(guests+2,0x80,0,0,false,true);t.idle();
    check(t.d.get_io$$interrupts()==0,"boundary padding changed IRQ");
    check(t.sent.size()==guests+3,"boundary MSI count");
    std::cout<<"AIA_GUEST_BOUNDARY_PASS guest_files="<<guests<<" msis="<<t.sent.size()
             <<" cycles="<<t.cycle<<" irq_bits="<<guests+2<<" stalled_target=1 claim=1 genmsi=1\n";
}
#endif

int main(int argc, char **argv) { try {
    bool negative = argc > 1 && std::string(argv[1]) == "--wrong-address";
    Driver t(negative);
#ifdef AIA_GUEST_BOUNDARY
    boundary(t);return 0;
#endif
    constexpr uint64_t M=0x0c000000, S=0x0c004000, I=0x28000000;
    check(t.bus(0,M+0x1bc4,false)==0x80000000,"machine address config lock");
    check(t.bus(0,M+0x1bc8,false)==0x28000,"supervisor address config base");
    check(t.bus(0,M+0x1bcc,false)==0x200000,"supervisor address config guest stride/reserved bits");
    for(unsigned off : {0x1bc0,0x1bc4,0x1bc8,0x1bcc})
        check(t.bus(1,S+off,false)==0,"supervisor exposed machine-only MSI config");
    // Unowned child sources must ignore every configuration, not merely suppress IRQ.
    t.bus(1,S+4,true,1); t.bus(1,S+0x3004,true,0x1005); t.bus(1,S+0x1edc,true,1);
    t.bus(1,S+0x1cdc,true,1);
    for(unsigned off : {4,0x3004,0x1e00,0x1c00})
        check(t.bus(1,S+off,false)==0,"nondelegated source was not read-only zero");
    for(unsigned id : {1,2,3}) t.bus(0,M+4*id,true,0x400);
    t.bus(1,S+4,true,1); t.bus(1,S+0x3004,true,0x1005); t.bus(1,S+0x1edc,true,1);
    t.bus(1,S,true,0x100);
    t.csr(2,0x70,1,1); t.csr(2,0xc0,1,uint64_t(1)<<5);
    t.bus(1,S+0x1cdc,true,1); t.idle();
    t.expect(0,1,5); check(t.d.get_io$$interrupts()==4,"guest1 not isolated from M/S/guest2");
    check(t.csr(2,0,0,0,true)==0x50005,"guest1 TOPEI identity");
    t.csr(2,0x70,1,0); t.idle(); check(t.d.get_io$$interrupts()==0,"delivery disable ignored");
    check(t.csr(2,0,0,0,true)==0x50005,"delivery incorrectly affected TOPEI");
    t.csr(2,0x72,1,5); check(t.csr(2,0,0,0,true)==0,"threshold boundary ignored");
    t.csr(2,0x72,1,6); check(t.csr(2,0,1,0,true,false,8)==0x50005,"held claim lost identity");
    check(t.csr(2,0x80)==0,"claim did not clear guest pending");
    t.csr(2,0x72,1,0); t.csr(2,0x70,1,1);
    // Snapshot GuestIndex and EIID at forwarding, including a queued owner.
    t.allow=false;
    t.bus(1,S+0x1cdc,true,1); t.idle();
    check(t.d.get_io$$msiValid(),"blocked MSI not retained");
    const auto address=t.d.get_io$$msiAddress(), data=t.d.get_io$$msiData();
    t.bus(1,S+0x3004,true,0x2041); t.idle(8);
    check(t.d.get_io$$msiValid() && t.d.get_io$$msiAddress()==address && t.d.get_io$$msiData()==data,
          "retarget changed blocked MSI owner");
    t.allow=true; t.idle(); t.expect(1,1,5);
    t.csr(3,0x70,1,1); t.csr(3,0xc2,1,2);
    t.bus(1,S+0x1cdc,true,1); t.idle(); t.expect(2,2,65);
    check(t.d.get_io$$interrupts()==12,"guest files did not retain independent interrupts");
    check(t.csr(2,0,1,0,true)==0x50005 && t.csr(3,0,1,0,true)==0x410041,"separate guest claims");
    // WLRL invalid guest retains guest2 but updates the EIID WARL field.
    t.bus(1,S+0x3004,true,0x3f806);
    check(t.bus(1,S+0x3004,false)==0x2006,"guest target WLRL/reserved mask");
    t.csr(3,0xc0,1,uint64_t(1)<<6);
    t.bus(1,S+0x1cdc,true,1); t.idle(); t.expect(3,2,6); t.csr(3,0,1,0,true);
    // S genmsi ignores bits that would be GuestIndex in target and bypasses domain IE.
    t.bus(1,S,true,0); t.bus(1,S+0x3000,true,0x2007); t.idle(); t.expect(4,0,7);
    check(t.csr(1,0x80)==(uint64_t(1)<<7),"S genmsi did not target supervisor file");
    check((t.bus(1,S+0x3000,false)&0x1000)==0,"genmsi busy did not clear");
    // M target cannot select a guest file.
    t.bus(0,M+16,true,1); t.bus(0,M+0x3010,true,0x2008);
    check(t.bus(0,M+0x3010,false)==8,"machine GuestIndex not read-only zero");
    t.bus(0,M+0x1edc,true,4); t.bus(0,M,true,0x100); t.bus(0,M+0x1cdc,true,4);
    t.idle(); t.expect(5,0,8,true); check(t.csr(0,0x80)==256,"machine MSI missing");
    // Revocation must erase the child configuration so it cannot reappear on redelegation.
    t.bus(0,M+4,true,0); t.idle();
    for(unsigned off : {4,0x3004,0x1e00,0x1c00})
        check(t.bus(1,S+off,false)==0,"revoked source retained readable state");
    t.bus(0,M+4,true,0x400); t.idle();
    for(unsigned off : {4,0x3004,0x1e00,0x1c00})
        check(t.bus(1,S+off,false)==0,"redelegated source resurrected stale state");
    // Injections exercise actual guest pages, padding, endianness and illegal accesses.
    t.bus(2,I+0x1004,true,0x09000000); check(t.csr(2,0x80)==512,"BE guest MSI decode");
    t.bus(2,I+0x1000,true,0); t.bus(2,I+0x1000,true,128);
    t.bus(2,I+0x3000,true,9); check(t.csr(2,0x80)==512,"invalid/padding MSI leaked");
    check(t.bus(2,I+0x3000,false)==0,"padding IMSIC page not zero");
    t.bus(2,I+0x1001,true,9,true); t.bus(2,I+0x1000,true,9,true,3,255);
    t.bus(2,I+0x1000,true,9,true,2,1);
    check(t.csr(2,0x80)==512,"faulting MSI changed pending");
    t.csr(4,0x80,0,0,false,true); t.csr(2,0x81,0,0,false,true);
    check(t.csr(2,0x71)==0,"reserved guest selector not zero");
    // Sample child bitmaps in the FIRST cycle after root revocation. There must
    // not be a one-cycle leak while the child's stored configuration clears.
    t.bus(1,S,true,0);
    for(unsigned off : {0x1e00,0x1c00}) {
        t.bus(0,M+8,true,0x400); t.bus(1,S+8,true,1);
        t.bus(1,S+0x1edc,true,2); t.bus(1,S+0x1cdc,true,2);
        check(t.bus(1,S+off,false)&4,"immediate revocation test was not armed");
        check(t.revokeRead(2,off)==0,"first-cycle revoked source bitmap leak");
    }
    // Revocation does not cancel an MSI already forwarded into the queue.
    // Software uses genmsi synchronization before reassigning the old guest file.
    t.bus(1,S,true,0x100); t.bus(1,S+12,true,1);
    t.bus(1,S+0x300c,true,0x100b); t.bus(1,S+0x1edc,true,3);
    t.allow=false; t.bus(1,S+0x1cdc,true,3); t.idle();
    check(t.d.get_io$$msiValid(),"revocation test did not reach blocked MSI");
    t.bus(0,M+12,true,0); t.idle();
    check(t.bus(1,S+12,false)==0 && t.bus(1,S+0x300c,false)==0,
          "revoked queued source retained configuration");
    t.allow=true; t.idle(); t.expect(6,1,11);
    check(t.csr(2,0x80)==(512+2048),"revocation erased queued guest MSI");
    t.bus(0,M+12,true,0x400); t.idle();
    check(t.bus(1,S+12,false)==0 && t.bus(1,S+0x300c,false)==0,
          "queued revocation resurrected stale source");
    // A generated synchronization MSI must stay behind previously queued guest
    // traffic to this hart. Writes while Busy must not replace its identity.
    t.bus(1,S+12,true,1); t.bus(1,S+0x300c,true,0x200c); t.bus(1,S+0x1edc,true,3);
    t.allow=false; t.bus(1,S+0x1cdc,true,3); t.idle();
    t.bus(1,S+0x3000,true,13); t.idle();
    check(t.bus(1,S+0x3000,false)==0x100d,"queued genmsi did not remain busy");
    t.bus(1,S+0x3000,true,14);
    check(t.bus(1,S+0x3000,false)==0x100d,"busy genmsi write replaced owner");
    t.allow=true; t.idle(); t.expect(7,2,12); t.expect(8,0,13);
    check(t.bus(1,S+0x3000,false)==13,"completed genmsi busy/result");
    check(t.csr(3,0x80)==4096 && t.csr(1,0x80)==((uint64_t(1)<<13)|128),
          "ordered genmsi/guest destinations");
    check(t.sent.size()==9,"duplicate or unexpected MSI");
    std::cout<<"AIA_GUEST_PASS messages=9 guest_files=2 cycles="<<t.cycle
             <<" delegation_reset=1 queued_revocation=1 first_cycle_revoke=1 genmsi_order=1 stalled_target=1 csr_stall=1 endian=1 padding=1\n";
    return 0;
} catch(const std::exception &e) { std::cerr<<"AIA_GUEST_FAIL "<<e.what()<<'\n'; return 1; } }
