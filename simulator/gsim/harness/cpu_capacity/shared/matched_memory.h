#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace matched {
inline void require(bool ok, const std::string &s) { if (!ok) throw std::runtime_error(s); }
constexpr uint64_t RamBase = 0x80200000ULL, RamBytes = 128 * 1024;
constexpr uint64_t RomBase = 0x80000000ULL, RomBytes = 128 * 1024;
constexpr unsigned FirstLatency = 3, MaxLive = 16, BeatBytes = 8;
class Memory {
public:
    std::vector<uint8_t> ram = std::vector<uint8_t>(RamBytes, 0);
    bool inRam(uint64_t a, uint64_t n) const { return n && n <= RamBytes && a >= RamBase && a - RamBase <= RamBytes - n; }
    bool mapped(uint64_t a, uint64_t n) const { return inRam(a,n) || (n && n <= RomBytes && a >= RomBase && a-RomBase <= RomBytes-n); }
    uint8_t byte(uint64_t a) const {
        require(mapped(a,1), "memory read outside declared ROM/RAM");
        if (a >= RamBase) return ram.at(a-RamBase);
        const uint64_t off=a-RomBase;
        // Same boot bytes on both cores, then defined NOPs for speculation.
        const uint32_t word = off < 4 ? 0x00200f97 : off < 8 ? 0x000f8067 : 0x00000013;
        return uint8_t(word >> (8*(off&3)));
    }
    uint64_t read(uint64_t a, unsigned n=8) const {
        require(n && n<=8 && mapped(a,n), "invalid memory read extent"); uint64_t v=0;
        for(unsigned i=0;i<n;++i) v |= uint64_t(byte(a+i)) << (8*i); return v;
    }
    void write(uint64_t a,uint64_t v,unsigned mask=255) {
        require(!(a&7) && inRam(a,8), "write outside aligned RAM beat");
        for(unsigned i=0;i<8;++i) if(mask&(1u<<i)) ram.at(a-RamBase+i)=uint8_t(v>>(8*i));
    }
};
struct ReadBeat { uint64_t tag,address,data; unsigned index,count; };
class ReadChannel {
    struct Entry { uint64_t tag,address,due; unsigned beat=0; std::vector<uint64_t> words; };
    std::deque<Entry> queue;
    uint64_t nextService=0;
public:
    uint64_t requests=0, bytes=0, responseBeats=0;
    bool ready() const { return queue.size()<MaxLive; }
    bool idle() const { return queue.empty(); }
    size_t size() const { return queue.size(); }
    void enqueue(const Memory &memory,uint64_t tag,uint64_t address,unsigned count,uint64_t cycle) {
        require(ready() && count && count<=8 && !(address&7) && memory.mapped(address,8*count), "invalid read enqueue");
        for(const auto&e:queue) require(e.tag!=tag,"read tag reused before response completion");
        Entry e{tag,address,std::max(cycle+FirstLatency,nextService),0,{}};
        for(unsigned i=0;i<count;++i)e.words.push_back(memory.read(address+8*i));
        // A stalled consumer shifts the next service dynamically in consume.
        nextService=e.due+count; queue.push_back(e); ++requests; bytes+=8*count;
    }
    bool valid(uint64_t cycle) const { return !queue.empty() && cycle>=queue.front().due; }
    ReadBeat offer(uint64_t cycle) const {
        require(valid(cycle),"read offer before due");const auto&e=queue.front();
        return {e.tag,e.address+8*e.beat,e.words.at(e.beat),e.beat,unsigned(e.words.size())};
    }
    void consume(uint64_t cycle) {
        require(valid(cycle),"read consume without valid");auto&e=queue.front();++responseBeats;
        if(++e.beat==e.words.size()){
            queue.pop_front();
            if(!queue.empty())queue.front().due=std::max(queue.front().due,cycle+1);
        }else e.due=cycle+1;
        nextService=std::max(nextService,cycle+1);
    }
};
struct WriteAck { uint64_t tag; };
class WriteChannel {
    struct Entry { uint64_t address; unsigned count; std::vector<uint64_t> words; std::vector<unsigned> masks; };
    std::map<uint64_t,Entry> collecting;
    struct Ack { uint64_t tag,due; };
    std::deque<Ack> acks;
    uint64_t lastBeat=UINT64_MAX;
public:
    uint64_t requests=0,bytes=0,responseAcks=0;
    bool idle() const {return collecting.empty()&&acks.empty();}
    bool ready() const {return collecting.size()+acks.size()<MaxLive;}
    bool conflicts(uint64_t address,unsigned bytes) const {
        for(const auto &[tag,e]:collecting) if(address < e.address+8*e.count && e.address<address+bytes)return true;
        return false;
    }
    void beat(Memory &memory,uint64_t tag,uint64_t address,unsigned count,unsigned index,uint64_t value,unsigned mask,uint64_t cycle) {
        require(cycle!=lastBeat,"write channel exceeded one beat per cycle");lastBeat=cycle;
        require(count && count<=8 && index<count && !(address&7) && memory.inRam(address,8*count),"invalid write extent");
        if(index==0){
            require(ready()&&!collecting.count(tag),"write tag/capacity violation");
            for(auto&a:acks)require(a.tag!=tag,"write tag reused before ack");
            collecting.emplace(tag,Entry{address,count,{},{}});++requests;
        }
        auto it=collecting.find(tag);require(it!=collecting.end(),"write continuation unowned");auto&e=it->second;
        require(e.address==address&&e.count==count&&e.words.size()==index,"write burst metadata/sequence changed");
        e.words.push_back(value);e.masks.push_back(mask);
        bytes+=__builtin_popcount(mask&255);
        if(index+1==count){
            for(unsigned i=0;i<count;++i)memory.write(address+8*i,e.words[i],e.masks[i]);
            collecting.erase(it);acks.push_back({tag,cycle+FirstLatency});
        }
    }
    void cleanRelease(uint64_t tag,uint64_t cycle) {
        require(ready()&&!collecting.count(tag),"clean release tag/capacity violation");
        for(auto&a:acks)require(a.tag!=tag,"clean release reused tag");
        acks.push_back({tag,cycle+FirstLatency});++requests;
    }
    bool valid(uint64_t cycle)const{return !acks.empty()&&cycle>=acks.front().due;}
    WriteAck offer(uint64_t cycle)const{require(valid(cycle),"write ack before due");return {acks.front().tag};}
    void consume(uint64_t cycle){require(valid(cycle),"write ack without valid");acks.pop_front();++responseAcks;}
};
}
