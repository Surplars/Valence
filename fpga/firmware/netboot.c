#include "netboot.h"
#include "crc32.h"

static uint16_t be16(const uint8_t *p) { return (uint16_t)p[0] << 8 | p[1]; }
static uint32_t be32(const uint8_t *p) {
    return (uint32_t)p[0]<<24 | (uint32_t)p[1]<<16 | (uint32_t)p[2]<<8 | p[3];
}
static uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static void w16(uint8_t *p,unsigned v) { p[0]=v>>8; p[1]=v; }
static void w32(uint8_t *p,uint32_t v) { p[0]=v>>24; p[1]=v>>16; p[2]=v>>8; p[3]=v; }
static void copy(uint8_t *d,const uint8_t *s,unsigned n) { while(n--) *d++=*s++; }
static int equal(const uint8_t *a,const uint8_t *b,unsigned n) {
    while(n--) if(*a++!=*b++) return 0;
    return 1;
}
static uint32_t sum16(uint32_t sum,const uint8_t *p,unsigned n) {
    while(n>=2) { sum+=be16(p); p+=2; n-=2; }
    if(n) sum+=(uint32_t)*p<<8;
    return sum;
}
static uint16_t checksum(uint32_t sum) {
    while(sum>>16) sum=(sum&65535)+(sum>>16);
    return (uint16_t)~sum;
}
uint32_t nb_crc_update(uint32_t crc,const uint8_t *p,unsigned n) {
    return firmware_crc_update(crc,p,n);
}
static void stage(struct nb_ops *o,enum nb_stage value) {
    if(o->stats) o->stats->stage=value;
    if(o->stage) o->stage(o->context,value);
}
static int fail(struct nb_ops *o,enum nb_failure value) {
    if(o->stats) o->stats->failure=value;
    return 0;
}
static int receive_for(struct nb_ops *o,uint64_t budget) {
    uint64_t start=o->stats?o->now(o->context):0;
    int n=o->recv(o->context,budget);
    if(n>0 && o->received_frame) o->rx=o->received_frame(o->context);
    if(o->stats) {
        o->stats->rx_ticks+=o->now(o->context)-start;
        ++o->stats->rx_calls;
        if(n>0) ++o->stats->rx_frames;
        if(!n) ++o->stats->rx_timeouts;
    }
    return n;
}
static int receive_frame(struct nb_ops *o) { return receive_for(o,o->hz/10); }
static uint32_t stream_crc(struct nb_ops *o,uint32_t crc,const uint8_t *p,unsigned n) {
    uint64_t start=o->stats?o->now(o->context):0;
    uint32_t result=nb_crc_update(crc,p,n);
    if(o->stats) o->stats->crc_ticks+=o->now(o->context)-start;
    return result;
}
static void ethernet(struct nb_ops *o,const uint8_t *to,unsigned type) {
    copy(o->tx,to,6); copy(o->tx+6,o->mac,6); w16(o->tx+12,type);
}
static int send_frame(struct nb_ops *o,unsigned size) {
    /* Ethernet padding is outside IP/UDP/TFTP lengths. */
    while(size<60) o->tx[size++]=0;
    uint64_t start=o->stats?o->now(o->context):0;
    int result=o->send(o->context,size);
    if(o->stats) { o->stats->tx_ticks+=o->now(o->context)-start; ++o->stats->tx_frames; }
    return result;
}
static int arp_send(struct nb_ops *o,const uint8_t *to,uint32_t target,unsigned op) {
    static const uint8_t broadcast[6]={255,255,255,255,255,255};
    uint8_t *a=o->tx+14;
    ethernet(o,op==1?broadcast:to,0x806);
    w16(a,1); w16(a+2,0x800); a[4]=6; a[5]=4; w16(a+6,op);
    copy(a+8,o->mac,6); w32(a+14,o->ip);
    for(unsigned i=0;i<6;++i) a[18+i]=op==1?0:to[i];
    w32(a+24,target);
    return send_frame(o,42);
}
/* Returns 1 for a valid peer ARP reply, answers requests for our static IP. */
static int arp_receive(struct nb_ops *o,unsigned n,uint8_t peer[6]) {
    const uint8_t *a=o->rx+14;
    if(n<42 || be16(o->rx+12)!=0x806 || be16(a)!=1 || be16(a+2)!=0x800 ||
       a[4]!=6 || a[5]!=4 || !equal(o->rx+6,a+8,6)) return 0;
    if(be16(a+6)==1 && be32(a+24)==o->ip) {
        arp_send(o,a+8,be32(a+14),2);
    } else if(be16(a+6)==2 && be32(a+14)==o->server_ip && be32(a+24)==o->ip &&
              equal(a+18,o->mac,6) && equal(o->rx,o->mac,6)) {
        copy(peer,a+8,6); return 1;
    }
    return 0;
}
static int udp_send(struct nb_ops *o,const uint8_t peer[6],uint16_t port,unsigned size) {
    uint8_t *ip=o->tx+14,*u=ip+20;
    ethernet(o,peer,0x800);
    for(unsigned i=0;i<28;++i) ip[i]=0;
    ip[0]=0x45; w16(ip+2,28+size); w16(ip+6,0x4000); ip[8]=64; ip[9]=17;
    w32(ip+12,o->ip); w32(ip+16,o->server_ip);
    w16(ip+10,checksum(sum16(0,ip,20)));
    w16(u,49152); w16(u+2,port); w16(u+4,8+size);
    uint32_t sum=sum16(0,ip+12,8)+17+8+size;
    uint16_t crc=checksum(sum16(sum,u,8+size));
    w16(u+6,crc?crc:65535);
    return send_frame(o,42+size);
}
/* Bounds, IPv4 header checksum, fragment rejection and UDP checksum BEFORE parsing. */
static const uint8_t *udp_receive(struct nb_ops *o,unsigned n,const uint8_t peer[6],
                                  uint16_t *port,unsigned *size) {
    const uint8_t *ip=o->rx+14;
    if(n<42 || !equal(o->rx,o->mac,6) || !equal(o->rx+6,peer,6) ||
       be16(o->rx+12)!=0x800 || ip[0]>>4!=4 || (ip[0]&15)<5) return 0;
    unsigned h=(ip[0]&15)*4, total=be16(ip+2);
    if(total<h+8 || total>n-14 || ip[9]!=17 || (be16(ip+6)&0x3fff) ||
       be32(ip+12)!=o->server_ip || be32(ip+16)!=o->ip ||
       checksum(sum16(0,ip,h))) return 0;
    const uint8_t *u=ip+h; unsigned len=be16(u+4);
    if(len!=total-h || len<8 || be16(u+2)!=49152 || !be16(u)) return 0;
    if(be16(u+6) && checksum(sum16(sum16(0,ip+12,8)+17+len,u,len))) return 0;
    *port=be16(u); *size=len-8;
    return u+8;
}
static unsigned option(uint8_t *p,const char *name,unsigned value) {
    unsigned n=0, digits=0; uint8_t reverse[5];
    do { p[n++]=(uint8_t)*name; } while(*name++);
    do { reverse[digits++]=(uint8_t)('0'+value%10); value/=10; } while(value);
    while(digits) p[n++]=reverse[--digits];
    p[n++]=0; return n;
}
static int tftp_send(struct nb_ops *o,const uint8_t peer[6],uint16_t port,
                     const char *file,int rrq,uint16_t block) {
    uint8_t *p=o->tx+42; unsigned n=2;
    w16(p,rrq?1:4);
    if(rrq) {
        while(*file && n<129) p[n++]=(uint8_t)*file++;
        if(*file) return -1;
        p[n++]=0; const char *mode="octet";
        do { p[n++]=(uint8_t)*mode; } while(*mode++);
        if(o->request_blksize) n+=option(p+n,"blksize",o->request_blksize);
        if(o->request_windowsize) n+=option(p+n,"windowsize",o->request_windowsize);
    } else { w16(p+2,block); n=4; if(o->stats) ++o->stats->acks; }
    return udp_send(o,peer,port,n);
}
static void tftp_error(struct nb_ops *o,const uint8_t peer[6],uint16_t port,unsigned code) {
    uint8_t *p=o->tx+42; w16(p,5); w16(p+2,code);
    const char *s=code==8?"invalid TFTP options":"invalid Valence image"; unsigned n=4;
    do { p[n++]=(uint8_t)*s; } while(*s++);
    udp_send(o,peer,port,n);
}
static int option_name(const uint8_t *p,unsigned n,const char *name) {
    for(unsigned i=0;i<n;++i) {
        unsigned c=p[i]; if(c>='A' && c<='Z') c+='a'-'A';
        if(!*name || c!=(unsigned)*name++) return 0;
    }
    return !*name;
}
/* Reject duplicates, unrequested options, malformed pairs and values above the
 * requested bounds. Defaults apply independently to omitted options. */
static int tftp_options(struct nb_ops *o,const uint8_t *p,unsigned bytes,
                        unsigned *block_size,unsigned *window_size) {
    unsigned at=2, seen=0;
    *block_size=512; *window_size=1;
    while(at<bytes) {
        unsigned key=at; while(at<bytes && p[at]) ++at;
        if(at==bytes || at==key) return 0;
        unsigned key_size=at++-key, value=0, digits=0;
        while(at<bytes && p[at]) {
            if(p[at]<'0' || p[at]>'9' || value>6553) return 0;
            value=value*10+p[at++]-'0'; ++digits;
        }
        if(at==bytes || !digits || value>65535) return 0;
        ++at;
        if(option_name(p+key,key_size,"blksize")) {
            if((seen&1) || !o->request_blksize || value<512 || value>o->request_blksize) return 0;
            seen|=1; *block_size=value;
        } else if(option_name(p+key,key_size,"windowsize")) {
            if((seen&2) || !o->request_windowsize || !value || value>o->request_windowsize) return 0;
            seen|=2; *window_size=value;
        } else return 0;
    }
    return seen!=0;
}
/* Final ACK loss must not force a second image download. Remain responsive for
 * a fixed two-second interval, never prolonged by duplicate traffic. No store,
 * header parse or CRC update is permitted after the validated short DATA. */
static int final_ack(struct nb_ops *o,const uint8_t peer[6],uint16_t port,
                     const char *file,uint16_t block,unsigned final_size) {
    uint64_t start=o->now(o->context), duration=o->hz*NB_TFTP_FINAL_ACK_SECONDS;
    for(;;) {
        uint64_t elapsed=o->now(o->context)-start;
        if(elapsed>=duration) break;
        uint64_t left=duration-elapsed;
        int n=receive_for(o,left<o->hz/10?left:o->hz/10);
        if(n<0) return fail(o,NB_RX_ABORTED);
        if(n<=0 || o->now(o->context)-start>=duration) continue;
        unsigned bytes=0; uint16_t from=0;
        const uint8_t *p=udp_receive(o,(unsigned)n,peer,&from,&bytes);
        if(p && from==port && bytes==final_size+4 && be16(p)==3 && be16(p+2)==block) {
            if(o->stats) ++o->stats->duplicates;
            if(tftp_send(o,peer,port,file,0,block)<0) return fail(o,NB_SEND_FAILED);
        }
    }
    if(o->stats) o->stats->final_ack_ticks=o->now(o->context)-start;
    return 1;
}
int nb_tftp(struct nb_ops *o,const char *file,uint32_t *entry,uint32_t *length) {
    if((o->request_blksize && (o->request_blksize<512 || o->request_blksize>NB_TFTP_BLOCK_MAX)) ||
       o->request_windowsize>NB_TFTP_WINDOW_MAX) return fail(o,NB_BAD_OPTIONS);
    uint8_t peer[6]={0};
    unsigned retries=0, received=0;
    uint64_t sent=o->now(o->context);
    stage(o,NB_ARP);
    if(arp_send(o,peer,o->server_ip,1)<0) return fail(o,NB_SEND_FAILED);
    int found=0;
    while(!found) {
        int n=receive_frame(o);
        if(n<0) return fail(o,NB_RX_ABORTED);
        if(n>0) found=arp_receive(o,(unsigned)n,peer);
        if(!found && o->now(o->context)-sent>=o->hz) {
            if(++retries==5) return fail(o,NB_RETRY_LIMIT);
            if(o->stats) ++o->stats->retries;
            if(arp_send(o,peer,o->server_ip,1)<0) return fail(o,NB_SEND_FAILED);
            sent=o->now(o->context);
        }
    }
    uint16_t port=69, next=1, previous=0;
    uint32_t size=0, target=0, wanted=0, running=0xffffffffU;
    int has_header=0, locked=0, negotiated=0;
    unsigned block_size=512, window_size=1, in_window=0;
    if(o->stats) { o->stats->block_size=block_size; o->stats->window_size=window_size; }
    retries=0; sent=o->now(o->context);
    stage(o,NB_RX);
    if(tftp_send(o,peer,port,file,1,0)<0) return fail(o,NB_SEND_FAILED);
    for(;;) {
        int n=receive_frame(o);
        if(n<0) return fail(o,NB_RX_ABORTED);
        unsigned bytes=0; uint16_t from=0;
        const uint8_t *p=0;
        if(n>0) {
            if(be16(o->rx+12)==0x806) arp_receive(o,(unsigned)n,peer);
            else p=udp_receive(o,(unsigned)n,peer,&from,&bytes);
        }
        if(p && bytes>=2 && (!locked || from==port)) {
            unsigned op=be16(p);
            if(op==5 && bytes>=4) return fail(o,NB_SERVER_ERROR);
            if(op==6 && !has_header) {
                unsigned proposed_block, proposed_window;
                if(!tftp_options(o,p,bytes,&proposed_block,&proposed_window) ||
                   (negotiated && (proposed_block!=block_size || proposed_window!=window_size))) {
                    tftp_error(o,peer,from,8); return fail(o,NB_BAD_OPTIONS);
                }
                if(!negotiated) { sent=o->now(o->context); retries=0; }
                locked=negotiated=1; port=from;
                block_size=proposed_block; window_size=proposed_window;
                if(o->stats) { o->stats->block_size=block_size; o->stats->window_size=window_size; }
                if(tftp_send(o,peer,port,file,0,0)<0) return fail(o,NB_SEND_FAILED);
            }
            if(op==3 && bytes>=4 && bytes<=block_size+4) {
                uint16_t block=be16(p+2);
                if(block!=next && locked) {
                    if(o->stats) {
                        if((uint16_t)(previous-block)<window_size) ++o->stats->duplicates;
                        else ++o->stats->out_of_order;
                    }
                    /* Go back to the last contiguous byte, discarding gaps.
                     * Counter resets align the next sender recovery window. */
                    if(tftp_send(o,peer,port,file,0,previous)<0) return fail(o,NB_SEND_FAILED);
                    in_window=0;
                } else if(block==next) {
                    unsigned data=bytes-4, offset=0;
                    if(!has_header) {
                        if(o->stats) { o->stats->stage=NB_HEADER; o->stats->failure=NB_BAD_HEADER; }
                        if(data>=36 && o->stats) {
                            o->stats->header_crc_expected=le32(p+36);
                            o->stats->header_crc_actual=nb_crc_update(0xffffffffU,p+4,32)^0xffffffffU;
                        }
                        if(data<36 || le32(p+4)!=0x31444c56U || le32(p+8)!=1 ||
                           le32(p+28)!=256 || le32(p+32)!=0 ||
                           le32(p+36)!=(nb_crc_update(0xffffffffU,p+4,32)^0xffffffffU))
                            goto bad;
                        uint32_t base=le32(p+12);
                        target=le32(p+16); size=le32(p+20); wanted=le32(p+24);
                        if(o->stats) {
                            o->stats->expected_length=size; o->stats->expected_crc=wanted;
                            o->stats->failure=NB_BAD_RANGE;
                        }
                        if(base!=o->base || !size || size>o->limit || (target&3) ||
                           target<base || (uint64_t)target>=(uint64_t)base+size) goto bad;
                        port=from; offset=36; has_header=locked=1;
                        if(o->stats) { o->stats->stage=NB_RX; o->stats->failure=NB_NONE; }
                    }
                    unsigned payload=data-offset;
                    if(payload>size-received) { fail(o,NB_LENGTH_MISMATCH); goto bad; }
                    uint64_t copy_start=o->stats?o->now(o->context):0;
                    int stored=payload?o->store(o->context,received,p+4+offset,payload):0;
                    if(o->stats) o->stats->copy_ticks+=o->now(o->context)-copy_start;
                    if(stored<0) { fail(o,NB_STORE_FAILED); goto bad; }
                    running=stream_crc(o,running,p+4+offset,payload); received+=payload;
                    if(o->stats) { o->stats->received=received; o->stats->stream_crc=running^0xffffffffU; }
                    if(data<block_size) {
                        stage(o,NB_STREAM_CRC);
                        if(received!=size) { fail(o,NB_LENGTH_MISMATCH); goto bad; }
                        if((running^0xffffffffU)!=wanted) { fail(o,NB_STREAM_MISMATCH); goto bad; }
                    }
                    previous=next++; /* Defined 16-bit rollover; bytes determine completeness. */
                    if(++in_window==window_size || data<block_size) {
                        if(tftp_send(o,peer,port,file,0,previous)<0) return fail(o,NB_SEND_FAILED);
                        in_window=0;
                    }
                    sent=o->now(o->context); retries=0;
                    if(data<block_size) {
                        if(!final_ack(o,peer,port,file,previous,data)) return 0;
                        if(o->prepare_verify) {
                            stage(o,NB_RAM_PREPARE);
                            int prepared=o->prepare_verify(o->context);
                            if(prepared<0)return fail(o,prepared==-2?NB_RX_ABORTED:NB_RAM_PREPARE_FAILED);
                        }
                        stage(o,NB_RAM_CRC);
                        uint64_t verify_start=o->stats?o->now(o->context):0;
                        int verified=o->verify(o->context,size,wanted);
                        if(o->stats) o->stats->verify_ticks+=o->now(o->context)-verify_start;
                        if(verified==-2) return fail(o,NB_RX_ABORTED);
                        if(verified<0) { fail(o,NB_RAM_MISMATCH); goto bad; }
                        *entry=target; *length=size; return 1;
                    }
                }
            }
        }
        if(o->now(o->context)-sent>=o->hz) {
            if(++retries==5) return fail(o,NB_RETRY_LIMIT);
            if(o->stats) ++o->stats->retries;
            if(tftp_send(o,peer,port,file,!locked,previous)<0) return fail(o,NB_SEND_FAILED);
            sent=o->now(o->context); in_window=0;
        }
        continue;
bad:
        tftp_error(o,peer,locked?port:from,0);
        return 0;
    }
}
