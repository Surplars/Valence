/* Host oracle: independent CSR map, 32-bit bus lanes and carry/reset timelines. */
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "valence_media_policy.h"

static const unsigned expected_offsets[] = {
    0x40,0x48,0x50,0x58,0x60,0x68,0xb0,0xb8,0xc0,0xc8,0xd0,0xd8,0xe0,0xe8,
    0xf0,0xf8,0x100,0x108,0x120,0x128,0xa0,0xa4,0xa8,0xac,0x110,0x114,0x98
};
static const char *expected_names[] = {
    "mac_tx_frames","mac_rx_frames","mac_rx_drops","mac_rx_bad_fcs","mac_tx_bytes","mac_rx_bytes",
    "rx_drop_bank_full","rx_drop_admission_closed","rx_drop_preamble","rx_drop_fcs","rx_drop_length",
    "rx_drop_address","rx_drop_phy_error","rx_drop_link_abort","tx_link_aborted_frames",
    "rx_fifo_stall_cycles","tx_fifo_stall_cycles","rx_odd_nibble_tails","rx_ingress_overflows",
    "rx_ingress_wholly_skipped","phy_no_ack","phy_verify_failures","phy_link_changes",
    "phy_completed_polls","phy_unsupported_modes","media_transition_timeouts","media_status_v1"
};
static void require(int ok,const char *why) {
    if(!ok){fprintf(stderr,"MEDIA_STATS_FAIL %s\n",why);exit(1);}
}
struct probe_bus { unsigned capability,version,reads; };
static unsigned probe_word(void *context,unsigned offset) {
    struct probe_bus *b=context;b->reads++;
    require((b->capability&0xc00)==0xc00,"probe accessed absent media extension");
    require(offset==0x9c&&b->reads==1,"probe touched wrong version lane or reread status");
    return b->version<<24;
}
struct bus {
    unsigned offset,width,calls,pattern,old_hardware;
    uint64_t value,low_samples[32];
    unsigned lows,carry_events,reset_events;
};
static unsigned read_word(void *context,unsigned offset) {
    struct bus *b=context;uint64_t old=b->value;unsigned call=b->calls++;
    require(b->calls<90,"bus retry failed to converge");
    require(!(offset&3),"unaligned 32-bit bus read");
    require(!b->old_hardware||offset<=0x6c,"legacy hardware extension offset probed");
    if(b->width==32){
        require(offset==b->offset && b->calls==1,"packed32 counter used wrong lane or repeated sample");
        return (uint32_t)b->value;
    }
    require(offset==b->offset+((call%3)==1?0:4),"64-bit read is not high-low-high");
    if(b->pattern==1)b->value++;
    if(b->pattern>=2&&b->pattern<=4){
        if(call==b->pattern-2){b->value=0;b->reset_events++;}
        else b->value++;
    }
    if(b->pattern==5){
        // Multiple noncoherent read attempts must retry, not combine halves.
        if(call<6)b->value+=UINT64_C(0x100000003);
        else b->value++;
    }
    b->carry_events+=(uint32_t)(old>>32)!=(uint32_t)(b->value>>32);
    if(offset==b->offset){
        require(b->lows<32,"oracle sample capacity");b->low_samples[b->lows++]=b->value;
        return (uint32_t)b->value;
    }
    return b->value>>32;
}
int main(int argc,char **argv) {
    const int inject=argc==2&&!strcmp(argv[1],"--inject-mismatch");
    unsigned cases=0,cap_cases=0,retries=0,carry_cases=0,reset_cases=0;
    const uint64_t values[]={0,1,0x7fffffffULL,0xfffffffdULL,0xffffffffULL,0x100000000ULL,
        0x12345678abcdef01ULL,0xfffffffffffffffdULL,0xffffffffffffffffULL};
    for(unsigned cap=0;cap<8192;cap++)for(unsigned version=0;version<4;version++){
        unsigned expected=((cap&0x1c00)==0x1c00&&version==1)?27:6;
        require(vg_media_stat_count(cap,version)==expected,"capability/version gate mismatch");cap_cases++;
        struct probe_bus probe={.capability=cap,.version=version};
        int mode=!(cap&0x800)?0:((cap&0x400)&&version==1?1:-1);
        require(vg_managed_media_probe(cap,probe_word,&probe)==mode,"managed probe policy mismatch");
        require(probe.reads==((cap&0xc00)==0xc00),"probe did not respect CAP MMIO boundary");
    }
    require(vg_media_stat_count(0x1c00,255)==6,"unknown future version exposed counters");
    for(unsigned i=0;i<27;i++){
        const struct vg_media_stat_descriptor *d=vg_media_stat(i);
        unsigned width=(i>=20&&i<26)?32:64;
        require(!strcmp(d->name,expected_names[i])&&strlen(d->name)<32,"statistic name/length mismatch");
        require(d->offset==expected_offsets[i]&&d->width==width,"CSR descriptor map mismatch");
        for(unsigned j=0;j<i;j++)require(strcmp(vg_media_stat(j)->name,d->name)!=0,"duplicate stat name");
        for(unsigned v=0;v<sizeof(values)/sizeof(values[0]);v++){
            struct bus b={.offset=expected_offsets[i],.width=width,.value=values[v]};
            uint64_t expected=width==32?(uint32_t)values[v]:values[v];
            if(inject&&i==0&&v==0)expected^=1;
            require(vg_media_stat_read(read_word,&b,i)==expected,"independent counter value mismatch");cases++;
        }
        if(width==64)for(unsigned p=1;p<=5;p++)for(unsigned v=0;v<sizeof(values)/sizeof(values[0]);v++){
            struct bus b={.offset=expected_offsets[i],.width=64,.pattern=p,.value=values[v]};
            uint64_t actual=vg_media_stat_read(read_word,&b,i);unsigned found=0;
            for(unsigned k=0;k<b.lows;k++)found|=actual==b.low_samples[k];
            require(found,"counter value never existed at any low-half sample");
            require(b.calls%3==0,"incomplete high-low-high attempt");
            retries+=b.calls>3;carry_cases+=b.carry_events!=0;reset_cases+=b.reset_events!=0;cases++;
        }
    }
    for(unsigned cap=0;cap<8192;cap++)if(vg_media_stat_count(cap,0)==6){
        for(unsigned i=0;i<6;i++){
            struct bus b={.offset=expected_offsets[i],.width=64,.value=0x3456789abcdef012ULL,.old_hardware=1};
            require(vg_media_stat_read(read_word,&b,i)==b.value,"legacy snapshot mismatch");
        }
    }
    require(retries&&carry_cases&&reset_cases,"carry/reset/retry coverage absent");
    printf("MEDIA_STATS_PASS cases=%u capability_cases=%u probe_mmio_cases=%u descriptors=27 legacy=6 retry_cases=%u carry_cases=%u reset_cases=%u bus_bits=32 writes=0 mdio_transactions=0\n",cases,cap_cases,cap_cases,retries,carry_cases,reset_cases);
    return 0;
}
