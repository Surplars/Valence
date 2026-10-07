extern "C" {
#include "netboot.h"
}
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
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
    std::array<uint8_t,2048> tx{},rx{};
    std::array<uint8_t,6> mac{2,0xaa,0xbb,0xcc,0xdd,1};
    std::vector<uint8_t> file,ram;
    std::deque<std::vector<uint8_t>> packets;
    uint64_t ticks=0;
    unsigned serverBlock=1, stores=0, errors=0, sends=0;
    int fault;
    bool injected=false, duplicate=false, stop=false;
    Server(unsigned length,int f=0):file(length+36),ram(length,0xa5),fault(f) {
        ops.context=this; ops.tx=tx.data(); ops.rx=rx.data();
        std::copy_n(std::array<uint8_t,6>{2,0x56,0x41,0x4c,0,1}.begin(),6,ops.mac);
        ops.ip=0xc0a8891e; ops.server_ip=0xc0a88901; ops.base=0x80200000;
        ops.limit=512*1024*1024-16384; ops.hz=1000;
        ops.now=[](void* p) { return static_cast<Server*>(p)->ticks; };
        ops.send=[](void* p,unsigned n) { return static_cast<Server*>(p)->send(n); };
        ops.recv=[](void* p,uint64_t budget) { return static_cast<Server*>(p)->recv(budget); };
        ops.store=[](void* p,uint32_t off,const uint8_t *data,unsigned n) {
            auto &s=*static_cast<Server*>(p);
            check(off<=s.ram.size() && n<=s.ram.size()-off,"store exceeded independently bounded RAM");
            std::copy_n(data,n,s.ram.begin()+off); ++s.stores; return 0;
        };
        ops.verify=[](void* p,uint32_t n,uint32_t wanted) {
            auto &s=*static_cast<Server*>(p);
            if(s.fault==30) s.ram.at(0)^=1;
            return n==s.ram.size() && crc(s.ram.data(),n)==wanted?0:-1;
        };
        for(unsigned n=0;n<length;++n) file[36+n]=uint8_t(n*17+3);
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
    std::vector<uint8_t> data(unsigned block,unsigned port=43000) {
        size_t off=(size_t(block)-1)*512;
        check(off<=file.size(),"server ACK advanced beyond file");
        unsigned bytes=std::min<size_t>(512,file.size()-off);
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
    int recv(uint64_t budget) {
        if(stop) return -1;
        if(packets.empty()) { ticks+=budget; return 0; }
        auto p=std::move(packets.front()); packets.pop_front();
        std::copy(p.begin(),p.end(),rx.begin()); ++ticks; return p.size();
    }
    void run(bool success) {
        uint32_t entry=0xdeadbeef,length=0xfeedbeef;
        int good=nb_tftp(&ops,"valence.vld",&entry,&length);
        check(bool(good)==success,"unexpected TFTP result");
        if(success) {
            check(entry==ops.base && length==ram.size(),"entry/length mismatch");
            check(std::equal(ram.begin(),ram.end(),file.begin()+36),"actual RAM differs from image");
        } else check(entry==0xdeadbeef && length==0xfeedbeef,"failed image published an entry");
        if((fault>=20 && fault<=24) || fault==28 || fault==29) check(stores==0,"invalid header wrote RAM");
    }
};
int main() { try {
    unsigned cases=0;
    for(unsigned bytes:{4U,440U,476U,477U,988U,989U,4096U,65536U,33553920U}) {
        Server s(bytes); s.run(true); ++cases;
    }
    for(int fault=1;fault<=11;++fault) {
        Server s(4096,fault); s.run(fault!=2); ++cases;
    }
    for(int fault=20;fault<=30;++fault) {
        Server s(4096,fault); s.run(false); ++cases;
    }
    Server stopped(4096); stopped.stop=true; stopped.run(false); ++cases;
    std::cout<<"BOOTROM_TFTP_HOST_PASS cases="<<cases
             <<" block_rollover=1 stream_crc=1 actual_ram_crc=1 duplicate=1 timeouts=1 malformed=1\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<"BOOTROM_TFTP_HOST_FAIL "<<e.what()<<"\n"; return 1; } }
