extern "C" {
#include "netboot.h"
}
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
static void check(bool v,const char* m) { if(!v) throw std::runtime_error(m); }
static uint32_t crc(const uint8_t *p,size_t n) {
    uint32_t v=~0U;
    while(n--) { v^=*p++; for(unsigned b=0;b<8;++b) v=(v>>1)^(0xedb88320U&uint32_t(-int(v&1))); }
    return ~v;
}
static unsigned r16(const uint8_t *p) { return unsigned(p[0])*256+p[1]; }
static void w16(uint8_t *p,unsigned n) { p[0]=n>>8; p[1]=n; }
static void w32(uint8_t *p,uint32_t n) { p[0]=n>>24; p[1]=n>>16; p[2]=n>>8; p[3]=n; }
static void le32(uint8_t *p,uint32_t n) { for(unsigned b=0;b<4;++b) p[b]=n>>(8*b); }
static uint16_t checksum(const uint8_t *p,unsigned n,uint32_t sum=0) {
    for(unsigned b=0;b<n;b+=2) sum+=unsigned(p[b])*256+(b+1<n?p[b+1]:0);
    while(sum>>16) sum=(sum&65535)+(sum>>16);
    return uint16_t(~sum);
}
struct Server {
    nb_ops ops{};
    nb_stats stats{};
    std::vector<nb_stage> phases;
    std::array<uint8_t,2048> tx{},rx{};
    std::array<uint8_t,6> mac{2,0xaa,0xbb,0xcc,0xdd,1};
    std::vector<uint8_t> file,ram;
    std::deque<std::vector<uint8_t>> packets;
    uint64_t ticks=0;
    unsigned serverBlock=1, stores=0, stored_bytes=0, errors=0, sends=0;
    int fault;
    bool injected=false, duplicate=false, stop=false;
    Server(unsigned length,int f=0):file(length+36),ram(length,0xa5),fault(f) {
        ops.context=this; ops.tx=tx.data(); ops.rx=rx.data(); ops.stats=&stats;
        ops.stage=[](void *p,nb_stage phase) { static_cast<Server*>(p)->phases.push_back(phase); };
        std::copy_n(std::array<uint8_t,6>{2,0x56,0x41,0x4c,0,1}.begin(),6,ops.mac);
        ops.ip=0xc0a8891e; ops.server_ip=0xc0a88901; ops.base=0x80200000;
        ops.limit=512*1024*1024-16384; ops.hz=1000;
        ops.now=[](void* p) { return static_cast<Server*>(p)->ticks; };
        ops.send=[](void* p,unsigned n) { return static_cast<Server*>(p)->send(n); };
        ops.recv=[](void* p,uint64_t budget) { return static_cast<Server*>(p)->recv(budget); };
        ops.store=[](void* p,uint32_t off,const uint8_t *data,unsigned n) {
            auto &s=*static_cast<Server*>(p);
            check(off<=s.ram.size() && n<=s.ram.size()-off,"store exceeded independently bounded RAM");
            check(off==s.stored_bytes,"DATA duplicated or committed out of order");
            check(std::equal(data,data+n,s.file.begin()+36+off),"wrong DATA committed to sequential stream");
            std::copy_n(data,n,s.ram.begin()+off); ++s.stores; s.stored_bytes+=n; return 0;
        };
        ops.verify=[](void* p,uint32_t n,uint32_t wanted) {
            auto &s=*static_cast<Server*>(p);
            if(s.fault==31) return -2;
            if(s.fault==30) s.ram.at(0)^=1;
            return n==s.ram.size() && crc(s.ram.data(),n)==wanted?0:-1;
        };
        for(unsigned n=0;n<length;++n)
            file[36+n]=uint8_t(n*17+(n>>8)*13+(n>>16)*7+(n>>24)*19+3);
        le32(file.data(),0x31444c56); le32(file.data()+4,1);
        le32(file.data()+8,ops.base); le32(file.data()+12,ops.base);
        le32(file.data()+16,length); le32(file.data()+20,crc(file.data()+36,length));
        le32(file.data()+24,256); le32(file.data()+28,0);
        if(fault==20) le32(file.data(),0);
        if(fault==21) le32(file.data()+8,ops.base+8);
        if(fault==22) le32(file.data()+12,ops.base+1);
        if(fault==23) le32(file.data()+16,ops.limit+1);
        if(fault==24) le32(file.data()+16,0);
        if(fault==25) file[20]^=1;
        if(fault==26) le32(file.data()+16,length+1);
        if(fault==27) le32(file.data()+16,length-1);
        if(fault==29) le32(file.data()+24,512);
        le32(file.data()+32,crc(file.data(),32));
        if(fault==28) file[32]^=1;
    }
    std::vector<uint8_t> arp() {
        std::vector<uint8_t> v(60);
        std::copy_n(ops.mac,6,v.begin()); std::copy(mac.begin(),mac.end(),v.begin()+6);
        w16(v.data()+12,0x806); auto a=v.data()+14;
        w16(a,1); w16(a+2,0x800); a[4]=6; a[5]=4; w16(a+6,2);
        std::copy(mac.begin(),mac.end(),a+8); w32(a+14,ops.server_ip);
        std::copy_n(ops.mac,6,a+18); w32(a+24,ops.ip); return v;
    }
    std::vector<uint8_t> udp(const std::vector<uint8_t>& payload,unsigned port=43000) {
        auto v=data(1,port);
        v.resize(42+payload.size());
        std::copy(payload.begin(),payload.end(),v.begin()+42);
        auto ip=v.data()+14,u=ip+20;
        w16(ip+2,28+payload.size()); w16(ip+10,0); w16(u+4,8+payload.size()); w16(u+6,0);
        uint32_t pseudo=17+8+payload.size();
        for(unsigned i=12;i<20;i+=2) pseudo+=r16(ip+i);
        auto sum=checksum(u,8+payload.size(),pseudo); w16(u+6,sum?sum:65535);
        w16(ip+10,checksum(ip,20)); return v;
    }
    std::vector<uint8_t> data(unsigned block,unsigned port=43000,unsigned block_size=512) {
        size_t off=(size_t(block)-1)*block_size;
        check(off<=file.size(),"server ACK advanced beyond file");
        unsigned bytes=std::min<size_t>(block_size,file.size()-off);
        std::vector<uint8_t> v(46+bytes);
        std::copy_n(ops.mac,6,v.begin()); std::copy(mac.begin(),mac.end(),v.begin()+6);
        w16(v.data()+12,0x800);
        auto ip=v.data()+14,u=ip+20;
        ip[0]=0x45; w16(ip+2,32+bytes); w16(ip+6,0x4000); ip[8]=64; ip[9]=17;
        w32(ip+12,ops.server_ip); w32(ip+16,ops.ip);
        w16(u,port); w16(u+2,49152); w16(u+4,12+bytes);
        w16(u+8,3); w16(u+10,block);
        std::copy_n(file.begin()+off,bytes,v.begin()+46);
        uint32_t pseudo=17+12+bytes;
        for(unsigned i=12;i<20;i+=2) pseudo+=r16(ip+i);
        auto sum=checksum(u,12+bytes,pseudo); w16(u+6,sum?sum:65535);
        w16(ip+10,checksum(ip,20)); return v;
    }
    void queue_data() {
        auto v=data(serverBlock);
        if(fault==1 && !injected) { injected=true; return; } // lost first DATA
        if(fault>=4 && fault<=11 && !injected && serverBlock==2) {
            injected=true; auto bad=v;
            if(fault==4) bad.resize(18);
            if(fault==5) bad[14+10]^=1;
            if(fault==6) bad[14+20+6]^=1;
            if(fault==7) { w16(bad.data()+14+6,0x2000); w16(bad.data()+14+10,0);
                           w16(bad.data()+14+10,checksum(bad.data()+14,20)); }
            if(fault==8) bad=data(serverBlock,43001);
            if(fault==9) bad[0]^=1;
            if(fault==10) w16(bad.data()+14+2,2040);
            if(fault==11) bad.resize(41);
            packets.push_back(std::move(bad));
        }
        packets.push_back(std::move(v));
    }
    int send(unsigned n) {
        check(n>=60 && n<=2048,"TX frame bounds/padding"); ++sends;
        if(r16(tx.data()+12)==0x806) {
            if(r16(tx.data()+20)==1 && fault!=2) packets.push_back(arp());
            return 0;
        }
        check(r16(tx.data()+12)==0x800 && !checksum(tx.data()+14,20),"TX IP checksum");
        auto u=tx.data()+34; unsigned len=r16(u+4);
        uint32_t sum=17+len;
        for(unsigned i=26;i<34;i+=2) sum+=r16(tx.data()+i);
        check(!checksum(u,len,sum),"TX UDP checksum");
        unsigned op=r16(u+8);
        if(op==1) {
            serverBlock=1; queue_data();
        } else if(op==4) {
            unsigned b=r16(u+10);
            if(b==(serverBlock&65535)) {
                if(fault==3 && !duplicate && serverBlock==2) {
                    duplicate=true; packets.push_back(data(serverBlock)); return 0;
                }
                if((size_t(serverBlock)-1)*512+512<=file.size()) {
                    ++serverBlock; queue_data();
                }
            }
        } else if(op==5) ++errors;
        else check(false,"unexpected TFTP transmit opcode");
        return 0;
    }
    bool borrowed_mode=false;
    std::vector<uint8_t> borrowed_frame;
    void enable_borrowed() {
        borrowed_mode=true;
        ops.received_frame=[](void *p) { return static_cast<Server*>(p)->borrowed_frame.data(); };
    }
    int recv(uint64_t budget) {
        if(borrowed_mode) std::fill(borrowed_frame.begin(),borrowed_frame.end(),0xa5);
        if(stop) return -1;
        if(packets.empty()) { ticks+=budget; return 0; }
        auto p=std::move(packets.front()); packets.pop_front();
        unsigned n=p.size();
        if(borrowed_mode) borrowed_frame=std::move(p);
        else std::copy(p.begin(),p.end(),rx.begin());
        ++ticks; return n;
    }
    void run(bool success) {
        uint32_t entry=0xdeadbeef,length=0xfeedbeef;
        int good=nb_tftp(&ops,"valence.vld",&entry,&length);
        check(bool(good)==success,"unexpected TFTP result");
        if(success) {
            check(entry==ops.base && length==ram.size(),"entry/length mismatch");
            check(std::equal(ram.begin(),ram.end(),file.begin()+36),"actual RAM differs from image");
            check(stats.failure==NB_NONE && stats.received==ram.size() &&
                  stats.expected_length==ram.size() && stats.stream_crc==crc(ram.data(),ram.size()),
                  "aggregate stats changed payload/completion");
            auto expected_phases=std::vector<nb_stage>{NB_ARP,NB_RX,NB_STREAM_CRC};
            if(ops.prepare_verify)expected_phases.push_back(NB_RAM_PREPARE);
            expected_phases.push_back(NB_RAM_CRC);check(phases==expected_phases,"phase ordering");
        } else check(entry==0xdeadbeef && length==0xfeedbeef,"failed image published an entry");
        check(stats.tx_frames==sends,"TX counter");
        if(fault==1) check(stats.retries==1 && stats.rx_timeouts>0,"retry counter");
        if(fault==2) check(stats.retries==4 && stats.failure==NB_RETRY_LIMIT,"bounded retry counter");
        if(fault==3) check(stats.duplicates==1,"duplicate counter");
        if(fault==25) check(stats.failure==NB_STREAM_MISMATCH,"stream mismatch diagnosis");
        if(fault==28) check(stats.header_crc_expected!=stats.header_crc_actual,"header CRC evidence");
        if(fault==30) check(stats.failure==NB_RAM_MISMATCH,"RAM mismatch diagnosis");
        if(fault==31) check(stats.failure==NB_RX_ABORTED && errors==0,"RAM verify cancel diagnosis");
        if((fault>=20 && fault<=24) || fault==28 || fault==29) check(stores==0,"invalid header wrote RAM");
    }
};
/* Independent bounded sender model: packet numbers are absolute internally,
 * wire numbers wrap modulo 65536. ACKs are checked against the offered range. */
struct WindowServer:Server {
    unsigned block_size, window_size, network_fault, acked=0, sent_end=0;
    unsigned options_sent=0, final_acks=0, last_wire_ack=0, gaps=0;
    bool ready=false, network_injected=false, gap_restarted=false;
    bool flood_final=false, stop_at_final=false;
    std::vector<uint8_t> override_oack;
    std::vector<unsigned> wire_acks;
    WindowServer(unsigned length,unsigned block=1024,unsigned window=4,unsigned f=0,int image_fault=0)
        :Server(length,image_fault),block_size(block),window_size(window),network_fault(f) {
        ops.request_blksize=1024; ops.request_windowsize=std::max(4U,window);
        ops.send=[](void *p,unsigned n) { return static_cast<WindowServer*>(p)->window_send(n); };
    }
    std::vector<uint8_t> oack() {
        if(!override_oack.empty()) return udp(override_oack);
        std::string options("\0\6",2);
        if(block_size!=512) options+=std::string("blksize\0",8)+std::to_string(block_size)+std::string(1,'\0');
        if(window_size!=1) options+=std::string("windowsize\0",11)+std::to_string(window_size)+std::string(1,'\0');
        // Explicit defaults remain valid options and need ACK0 too.
        if(options.size()==2) options+=std::string("windowsize\0001\0",13);
        return udp(std::vector<uint8_t>(options.begin(),options.end()));
    }
    unsigned last_block() const { return unsigned(file.size()/block_size)+1; }
    void burst(unsigned first) {
        sent_end=std::min(first+window_size-1,last_block());
        for(unsigned b=first;b<=sent_end;++b) {
            if(!network_injected && ((network_fault==1 && b==2) ||
                    (network_fault==2 && b==4) || (network_fault==3 && b==1))) {
                network_injected=true; continue; // Drop middle, tail or first DATA.
            }
            if(network_fault==4 && b==2 && !network_injected) {
                network_injected=true; packets.push_back(data(3,43000,block_size));
            }
            if(network_fault==5 && b==2 && !network_injected) {
                network_injected=true; packets.push_back(data(1,43000,block_size));
            }
            if(network_fault==6 && b==1 && !network_injected) {
                network_injected=true; packets.push_back(data(1,43001,block_size));
            }
            packets.push_back(data(b,43000,block_size));
        }
    }
    int window_send(unsigned n) {
        if(r16(tx.data()+12)==0x806) return Server::send(n);
        check(n>=60 && n<=512,"negotiated TX frame exceeds board buffer"); ++sends;
        check(!checksum(tx.data()+14,20),"windowed TX IP checksum");
        auto u=tx.data()+34; unsigned len=r16(u+4),sum=17+len;
        for(unsigned i=26;i<34;i+=2) sum+=r16(tx.data()+i);
        check(!checksum(u,len,sum),"windowed TX UDP checksum");
        unsigned op=r16(u+8);
        if(op==1) {
            std::string rrq(reinterpret_cast<char*>(u+10),len-10);
            check((!ops.request_blksize || rrq.find(std::string("blksize\0001024\0",13))!=std::string::npos) &&
                  (!ops.request_windowsize || rrq.find(std::string("windowsize\0",11)+std::to_string(ops.request_windowsize)+std::string(1,'\0'))!=std::string::npos),
                  "RRQ bounded options absent");
            if(network_fault==7 && !network_injected) { network_injected=true; return 0; }
            ++options_sent; packets.push_back(oack());
        } else if(op==4) {
            unsigned wire=r16(u+10); wire_acks.push_back(wire); last_wire_ack=wire;
            if(!ready) {
                check(wire==0,"OACK requires ACK0");
                if(network_fault==8 && !network_injected) {
                    network_injected=true; ++options_sent; packets.push_back(oack()); return 0;
                }
                ready=true;
                if(network_fault==9) {
                    std::string changed("\0\6windowsize\0002\0",15);
                    packets.push_back(udp(std::vector<uint8_t>(changed.begin(),changed.end())));
                }
                burst(1); return 0;
            }
            unsigned absolute=acked+uint16_t(wire-uint16_t(acked));
            if(absolute>sent_end) return 0; // Delayed older ACK, including across wrap.
            if(network_fault==10 && absolute==4 && !network_injected) {
                network_injected=true; burst(1); return 0; // Lost cumulative ACK.
            }
            if(absolute==last_block()) {
                ++final_acks;
                if(stop_at_final) stop=true;
                if((network_fault==11 && !network_injected) || flood_final) {
                    network_injected=true; packets.push_back(data(absolute,43000,block_size));
                }
                acked=absolute; return 0;
            }
            if(absolute>acked) {
                if(absolute<sent_end) ++gaps;
                acked=absolute; gap_restarted=false; burst(acked+1);
            } else if(!gap_restarted) {
                gap_restarted=true; ++gaps; burst(acked+1);
            }
        } else if(op==5) ++errors;
        else check(false,"unexpected negotiated opcode");
        return 0;
    }
    void checked_run(bool success=true) {
        run(success);
        if(success) {
            check(stats.block_size==block_size && stats.window_size==window_size,"negotiated dimensions");
            check(stored_bytes==ram.size(),"full exactly-once stream store");
            check(stats.final_ack_ticks==ops.hz*2,"final ACK grace deadline moved");
            check(final_acks>0,"EOF never cumulatively acknowledged");
            if(network_fault==11) check(final_acks==2,"lost EOF ACK was not recovered");
            if(network_fault==8) check(options_sent==2 && wire_acks[0]==0 && wire_acks[1]==0,"OACK retransmission ACK0");
        }
    }
};
static unsigned window_tests() {
    unsigned cases=0;
    for(unsigned fault:{0U,1U,4U,11U}) {
        WindowServer s(16348,1024,4,fault); s.enable_borrowed(); s.checked_run(); ++cases;
    }
    for(int fault:{25,30}) {
        WindowServer s(8000,1024,4,0,fault); s.enable_borrowed(); s.checked_run(false); ++cases;
    }
    { WindowServer s(76564168,1024,4); s.enable_borrowed(); s.checked_run();
      check(s.stats.received==76564168U && s.stored_bytes==76564168U,"current image semantic length mismatch"); ++cases;
      std::cout << "BOOTROM_CURRENT_IMAGE_PASS payload=76564168 wire=76564204 borrowed=1 stream_crc=1 ram_crc=1\n"; }

    for(unsigned block:{512U,1024U}) for(unsigned window:{1U,2U,3U,4U})
        for(unsigned length:{4U,988U,1020U,4060U,4096U}) {
            WindowServer s(length,block,window); s.checked_run(); ++cases;
        }
    for(unsigned fault=1;fault<=11;++fault) {
        WindowServer s(10000,1024,4,fault); s.checked_run(fault!=9);
        if(fault==9) check(s.stats.failure==NB_BAD_OPTIONS && s.stores==0,"changed OACK accepted");
        ++cases;
    }
    for(int fault=20;fault<=31;++fault) {
        WindowServer s(8000,1024,4,0,fault); s.checked_run(false); ++cases;
    }
    for(std::string options:{std::string(""),std::string("blksize\0001025\0",13),
            std::string("windowsize\0005\0",13),std::string("windowsize\0000\0",13),
            std::string("windowsize\000655360\0",18),std::string("blksize\000511\0",12),
            std::string("timeout\0001\0",10),std::string("windowsize\0004",12),
            std::string("windowsize\0\0",12),std::string("windowsize\000x\0",13),
            std::string("windowsize\0004\0WINDOWSIZE\0004\0",26)}) {
        WindowServer s(8000); std::string response=std::string("\0\6",2)+options;
        s.override_oack=std::vector<uint8_t>(response.begin(),response.end());
        s.checked_run(false); check(s.stats.failure==NB_BAD_OPTIONS && s.stores==0,"malformed OACK wrote RAM"); ++cases;
    }
    { WindowServer s(988); s.flood_final=true; s.checked_run();
      check(s.final_acks>=1000 && s.stats.final_ack_ticks==2000,"duplicates extended final ACK deadline"); ++cases; }
    { WindowServer s(988); s.stop_at_final=true; s.checked_run(false);
      check(s.stats.failure==NB_RX_ABORTED && s.phases.back()==NB_STREAM_CRC,"UART cancellation lost during EOF grace"); ++cases; }
    { Server s(2000); s.ops.request_blksize=1024; s.ops.request_windowsize=4; s.run(true);
      check(s.stats.block_size==512 && s.stats.window_size==1,"legacy server fallback"); ++cases; }
    { WindowServer s(988); s.ops.request_windowsize=0; s.checked_run(false);
      check(s.stats.failure==NB_BAD_OPTIONS,"unsolicited OACK option accepted"); ++cases; }
    { WindowServer s(10000); s.checked_run();
      check(s.wire_acks==std::vector<unsigned>{0,4,8,10},"ACK sent before negotiated window boundary"); ++cases; }
    for(unsigned bad:{511U,1025U}) {
        Server s(4); s.ops.request_blksize=bad; s.run(false);
        check(s.stats.failure==NB_BAD_OPTIONS && s.sends==0,"invalid local block bound advertised"); ++cases;
    }
    { Server s(4); s.ops.request_windowsize=17; s.run(false);
      check(s.stats.failure==NB_BAD_OPTIONS && s.sends==0,"invalid local window bound advertised"); ++cases; }
    for(unsigned window:{8U,16U}) for(unsigned fault:{0U,1U,4U,11U}) {
        WindowServer s(window*2048-36,1024,window,fault); s.checked_run();
        check(s.stats.window_size==window && s.stats.received==window*2048-36,
              "parameterized window lost bytes"); ++cases;
    }
    for(unsigned length:{65535U*1024-36,65537U*1024+13}) {
        WindowServer s(length); s.checked_run();
        check(std::count(s.wire_acks.begin(),s.wire_acks.end(),0)>=2,"wrapped ACK0 absent after initial handshake"); ++cases;
    }
    return cases;
}
static void prepare_tests() {
    Server s(16);
    s.ops.prepare_verify=[](void *p){auto &v=*static_cast<Server*>(p);
        check(v.stats.final_ack_ticks>=2*v.ops.hz,"maintenance before final ACK dally");
        v.ticks+=100000;return 0;};
    s.run(true);check(s.stats.verify_ticks<100000,"maintenance polluted CRC timing");
    Server bad(16);bad.ops.prepare_verify=[](void*){return -1;};bad.run(false);
    check(bad.stats.failure==NB_RAM_PREPARE_FAILED,"prepare failure mislabeled CRC/send");
    std::cout<<"BOOTROM_RAM_PREPARE_PROTOCOL_PASS cases=2 after_fixed_final_ack=1 crc_timing_separate=1\n";
}
int main() {
    prepare_tests(); try {
    unsigned cases=0;
    for(unsigned bytes:{4U,440U,476U,477U,988U,989U,4096U,65536U,33553920U,66348740U}) {
        Server s(bytes); s.run(true); ++cases;
    }
    for(int fault=1;fault<=11;++fault) {
        Server s(4096,fault); s.run(fault!=2); ++cases;
    }
    for(int fault=20;fault<=31;++fault) {
        Server s(4096,fault); s.run(false); ++cases;
    }
    Server stopped(4096); stopped.stop=true; stopped.run(false); ++cases;
    std::cout<<"BOOTROM_TFTP_HOST_PASS cases="<<cases
             <<" full_wire_length=66348776 block_rollover=1 stream_crc=1 actual_ram_crc=1 duplicate=1 timeouts=1 malformed=1\n";
    unsigned window_cases=window_tests();
    std::cout<<"BOOTROM_TFTP_WINDOW_PASS cases="<<window_cases
             <<" window4=1 block1024=1 oack=1 crc_exactly_once=1 final_ack_deadline=1 wrap=1 fallback=1\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<"BOOTROM_TFTP_HOST_FAIL "<<e.what()<<"\n"; return 1; } }
