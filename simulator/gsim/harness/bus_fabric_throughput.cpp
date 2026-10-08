#include "BusFabricThroughputGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

// Independent protocol/byte oracle, not a CPU/cache/coherence performance model.
// The nested data inputs represent already authorized, disjoint backing traffic.
// In the board, coherent-home maintenance drains before direct DMA access. DMA
// is deliberately one transaction at a time here, retaining its ordered stream.
// Every run has exactly 128 requests per stream and unchanged 4/2 DDR capacity.
namespace {
constexpr unsigned Masters = 3, Requests = 128, Total = Masters * Requests;
constexpr unsigned ReadLatency = 12, WritePreparation = 12, Deadline = 100000;
constexpr uint64_t RomBase = 0x80000000ULL, DdrBase = 0x80200000ULL;
constexpr std::array<const char *, Masters> Names{"fetch", "home", "dma"};
bool mutateExpected = false;

void check(bool good, const std::string &message) {
    if (!good) throw std::runtime_error(message);
}
unsigned logSize(unsigned beats) {
    unsigned result = 3;
    for (; beats > 1; beats >>= 1) ++result;
    return result;
}
uint64_t initial(uint64_t address) {
    return 0x26ad9357b08f41ecULL ^ (address * 0x100100101ULL) ^ (address >> 7);
}
uint64_t payload(unsigned tx, unsigned beat) {
    return 0x8d246ac013579bfeULL ^ (uint64_t(tx + 1) * 0x10000010001ULL) ^
        (uint64_t(beat + 1) * 0x102040810204081ULL);
}
unsigned mask(unsigned tx, unsigned beat) {
    return tx % 3 == 0 ? 0xff : ((tx + beat) % 3 == 0 ? 0x55 : ((tx + beat) % 3 == 1 ? 0xaa : 0xff));
}
unsigned byteCount(unsigned mask) {
    unsigned n = 0;
    for (; mask; mask >>= 1) n += mask & 1;
    return n;
}
struct Transaction {
    unsigned n, master, sequence, source, beats;
    uint64_t address;
    bool write, rom, error;
    bool accepted = false, aDone = false, issued = false, responseDone = false, completed = false;
    unsigned firstCycle = 0, dBeat = 0, axiId = 0;
};
struct Read { unsigned tx, id, beat, due; };
struct Write { unsigned tx, id, beat, due; };
struct RomRead { unsigned tx, source, beat, due; };
using AddressBits = std::tuple<uint64_t, unsigned, unsigned, unsigned, unsigned, bool, unsigned, unsigned, unsigned>;
using WriteBits = std::tuple<uint64_t, unsigned, bool>;
using ReplyBits = std::tuple<uint64_t, unsigned, unsigned, unsigned, unsigned, unsigned, bool, bool>;
using RequestBits = std::tuple<uint64_t, uint64_t, unsigned, unsigned, unsigned, unsigned, unsigned, bool>;

#define SET_MASTER(field, value) do { \
    if (m == 0) dut.set_io$$fetch$$##field(value); \
    else if (m == 1) dut.set_io$$home$$##field(value); \
    else dut.set_io$$dma$$##field(value); \
} while (false)
#define GET_MASTER(field) (m == 0 ? dut.get_io$$fetch$$##field() : \
    (m == 1 ? dut.get_io$$home$$##field() : dut.get_io$$dma$$##field()))

void reset(SBusFabricThroughputGsim &dut) {
    for (unsigned m = 0; m < Masters; ++m) {
        SET_MASTER(a$$valid, 0); SET_MASTER(b$$ready, 0);
        SET_MASTER(c$$valid, 0); SET_MASTER(e$$valid, 0); SET_MASTER(d$$ready, 0);
    }
    dut.set_io$$rom$$a$$ready(0); dut.set_io$$rom$$d$$valid(0);
    dut.set_io$$rom$$b$$valid(0); dut.set_io$$rom$$c$$ready(0); dut.set_io$$rom$$e$$ready(0);
    dut.set_io$$axi$$ar$$ready(0); dut.set_io$$axi$$aw$$ready(0); dut.set_io$$axi$$w$$ready(0);
    dut.set_io$$axi$$r$$valid(0); dut.set_io$$axi$$b$$valid(0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
}

void run(SBusFabricThroughputGsim &dut, bool pressure) {
    reset(dut);
    std::vector<Transaction> tx;
    std::map<uint64_t, unsigned> addresses;
    std::map<uint64_t, uint64_t> expectedMemory, deviceMemory;
    auto updateMemory = [](auto &memory, uint64_t address, uint64_t data, unsigned strobes) {
        const auto found = memory.find(address);
        uint64_t word = found == memory.end() ? initial(address) : found->second;
        for (unsigned byte = 0; byte < 8; ++byte) if (strobes & (1U << byte)) {
            const uint64_t bits = 0xffULL << (8 * byte);
            word = (word & ~bits) | (data & bits);
        }
        memory[address] = word;
    };
    unsigned wantAr = 0, wantAw = 0, wantR = 0, wantW = 0, wantD = 0, wantRom = 0;
    uint64_t wantReadBytes = 0, wantWriteBytes = 0;
    for (unsigned m = 0; m < Masters; ++m) for (unsigned i = 0; i < Requests; ++i) {
        const unsigned n = m * Requests + i;
        const bool rom = m == 0 && i % 4 == 0;
        const bool wr = m == 1 ? i % 3 != 2 : m == 2 && i % 4 != 3;
        // Fetch is read-only; home includes complete line-sized traffic and a
        // 16-beat fabric-limit case. Direct DMA uses naturally aligned words.
        const unsigned beats = m == 0 ? (rom ? 2 : 8) : m == 1 ? (i % 8 == 7 ? 16 : 8) : 1;
        const uint64_t address = (rom ? RomBase : DdrBase + uint64_t(m) * 0x100000) + uint64_t(i) * 256;
        const unsigned source = i % (m == 0 ? 16 : 8);
        const bool error = pressure && !rom && (wr ? i % 29 == 11 : i % 31 == 17);
        tx.push_back({n, m, i, source, beats, address, wr, rom, error});
        check(addresses.emplace(address, n).second, "test contains overlapping transaction addresses");
        wantD += wr ? 1 : beats;
        if (rom) ++wantRom;
        else if (wr) { ++wantAw; wantW += beats; }
        else { ++wantAr; wantR += beats; }
        if (!wr && !error) wantReadBytes += uint64_t(beats) * 8;
        if (wr) for (unsigned beat = 0; beat < beats; ++beat) {
            updateMemory(expectedMemory, address + beat * 8, payload(n, beat), mask(n, beat));
            if (!error) wantWriteBytes += byteCount(mask(n, beat));
        }
    }

    std::array<unsigned, Masters> next{}, aBeat{}, completed{}, inFlight{}, firstDone{}, lastDone{};
    std::array<unsigned, Masters> maxLatency{}, maxAcceptGap{}, lastAccept{}, aStalls{}, dStalls{}, dBeats{};
    std::array<std::array<int, 16>, Masters> sourceOwner{};
    for (auto &row : sourceOwner) row.fill(-1);
    std::array<int, 16> axiOwner{}; axiOwner.fill(-1);
    std::array<std::optional<unsigned>, Masters> dBurst{};
    std::array<std::optional<ReplyBits>, Masters> heldD{};
    std::optional<AddressBits> heldAr, heldAw;
    std::optional<WriteBits> heldW;
    std::optional<RequestBits> heldRomA;
    std::vector<Read> reads;
    std::deque<Write> writes, responses;
    std::deque<RomRead> romReads;
    std::optional<Read> offeredR;
    std::optional<Write> offeredB;
    std::optional<RomRead> offeredRom;
    unsigned readTurn = 0, cycle = 0, done = 0, arCount = 0, awCount = 0, rCount = 0, wCount = 0;
    unsigned bCount = 0, romCount = 0, romBeats = 0, dCount = 0, errorCount = 0;
    unsigned idsPeak = 0, readsPeak = 0, writesPeak = 0, mastersPeak = 0, axiMastersPeak = 0;
    unsigned readWriteOverlap = 0, simultaneousRW = 0, simultaneousD = 0, awLeadCount = 0, awLeadPeak = 0;
    unsigned arStalls = 0, awStalls = 0, wStalls = 0, rStalls = 0, bStalls = 0;
    unsigned reorderedD = 0, rInterleaves = 0, accepted = 0, maxLive = 0;
    unsigned usefulRBeats = 0, usefulWBeats = 0, usefulDBeats = 0;
    std::optional<unsigned> previousR;
    uint64_t usefulReadBytes = 0, usefulWriteBytes = 0, writeWireBytes = 0;

    auto findOwner = [&](uint64_t address, bool write, bool rom) -> Transaction & {
        const auto it = addresses.find(address);
        check(it != addresses.end(), "address has no independent transaction owner");
        auto &t = tx[it->second];
        check(t.accepted && t.aDone && !t.issued && !t.completed && t.write == write && t.rom == rom,
            "AXI/ROM address has wrong, incomplete or duplicate TL owner");
        return t;
    };
    auto claimId = [&](unsigned id, Transaction &t) {
        check(id < 4 && axiOwner[id] == -1, "AXI ID reused while a response remains live");
        axiOwner[id] = int(t.n); t.axiId = id; t.issued = true;
    };

    for (; cycle < Deadline && done < Total; ++cycle) {
        const bool arReady = !pressure || cycle % 11 < 8;
        const bool awReady = !pressure || cycle % 13 < 9;
        const bool wReady = !writes.empty() && cycle >= writes.front().due && (!pressure || cycle % 7 < 5);
        const bool romReady = !pressure || cycle % 5 != 1;
        std::array<bool, Masters> valid{}, ready{};
        for (unsigned m = 0; m < Masters; ++m) {
            ready[m] = !pressure || ((cycle + m * 3) % (11 + 2 * m) < 8 + m &&
                (cycle + m * 11) % 97 < 83);
            const unsigned n = m * Requests + std::min(next[m], Requests - 1);
            const auto &t = tx[n];
            // Never reuse a source until the master's complete D message. DMA
            // permits only one complete transaction outstanding, so it cannot
            // gain throughput by illegally bypassing its ordering boundary.
            valid[m] = next[m] < Requests && (aBeat[m] ||
                (sourceOwner[m][t.source] == -1 && (m != 2 || !inFlight[m])));
            SET_MASTER(a$$valid, valid[m]); SET_MASTER(a$$bits$$opcode, t.write ? (n % 3 == 0 ? 0 : 1) : 4);
            SET_MASTER(a$$bits$$param, 0); SET_MASTER(a$$bits$$size, logSize(t.beats));
            SET_MASTER(a$$bits$$source, t.source); SET_MASTER(a$$bits$$address, t.address);
            SET_MASTER(a$$bits$$mask, t.write ? mask(n, aBeat[m]) : 0xff);
            SET_MASTER(a$$bits$$data, t.write ? payload(n, aBeat[m]) : 0);
            SET_MASTER(a$$bits$$corrupt, 0); SET_MASTER(d$$ready, ready[m]);
        }
        if (!offeredR && (!pressure || cycle % 6 != 0)) {
            for (unsigned delta = 0; delta < 4 && !offeredR; ++delta) {
                const unsigned id = (readTurn + delta) % 4;
                const auto it = std::find_if(reads.begin(), reads.end(), [&](const Read &r) {
                    return r.id == id && cycle >= r.due;
                });
                if (it != reads.end()) offeredR = *it;
            }
        }
        if (!offeredB && (!pressure || cycle % 5 != 0)) {
            for (auto it = responses.rbegin(); it != responses.rend(); ++it) if (cycle >= it->due) {
                offeredB = *it; break;
            }
        }
        if (!offeredRom && !romReads.empty() && cycle >= romReads.front().due) {
            offeredRom = romReads.front(); romReads.pop_front();
        }
        dut.set_io$$axi$$ar$$ready(arReady); dut.set_io$$axi$$aw$$ready(awReady);
        dut.set_io$$axi$$w$$ready(wReady); dut.set_io$$axi$$r$$valid(bool(offeredR));
        dut.set_io$$axi$$r$$bits$$id(offeredR ? offeredR->id : 0);
        dut.set_io$$axi$$r$$bits$$data(offeredR ? initial(tx[offeredR->tx].address + offeredR->beat * 8) : 0);
        dut.set_io$$axi$$r$$bits$$last(offeredR && offeredR->beat + 1 == tx[offeredR->tx].beats);
        dut.set_io$$axi$$r$$bits$$resp(offeredR && tx[offeredR->tx].error &&
            offeredR->beat + 1 == tx[offeredR->tx].beats ? 2 : 0);
        dut.set_io$$axi$$b$$valid(bool(offeredB));
        dut.set_io$$axi$$b$$bits$$id(offeredB ? offeredB->id : 0);
        dut.set_io$$axi$$b$$bits$$resp(offeredB && tx[offeredB->tx].error ? 2 : 0);
        dut.set_io$$rom$$a$$ready(romReady); dut.set_io$$rom$$d$$valid(bool(offeredRom));
        dut.set_io$$rom$$d$$bits$$opcode(1); dut.set_io$$rom$$d$$bits$$param(0);
        dut.set_io$$rom$$d$$bits$$size(offeredRom ? logSize(tx[offeredRom->tx].beats) : 3);
        dut.set_io$$rom$$d$$bits$$source(offeredRom ? offeredRom->source : 0);
        dut.set_io$$rom$$d$$bits$$sink(0); dut.set_io$$rom$$d$$bits$$denied(0);
        dut.set_io$$rom$$d$$bits$$corrupt(0);
        dut.set_io$$rom$$d$$bits$$data(offeredRom ? initial(tx[offeredRom->tx].address + offeredRom->beat * 8) : 0);
        dut.step();

        for (unsigned m = 0; m < Masters; ++m) {
            check(!GET_MASTER(b$$valid), "TL-UL input unexpectedly received a coherence probe");
            if (valid[m] && GET_MASTER(a$$ready)) {
                auto &t = tx[m * Requests + next[m]];
                if (!aBeat[m]) {
                    check(!t.accepted && sourceOwner[m][t.source] == -1, "TL source reused or request duplicated");
                    sourceOwner[m][t.source] = int(t.n); t.accepted = true; t.firstCycle = cycle;
                    ++inFlight[m]; ++accepted;
                    maxAcceptGap[m] = std::max(maxAcceptGap[m], cycle - lastAccept[m]); lastAccept[m] = cycle;
                }
                ++aBeat[m];
                if (!t.write || aBeat[m] == t.beats) { t.aDone = true; ++next[m]; aBeat[m] = 0; }
            } else if (valid[m]) ++aStalls[m];
        }

#define AXI_ADDRESS(channel) std::make_tuple(uint64_t(dut.get_io$$axi$$##channel##$$bits$$addr()), \
    unsigned(dut.get_io$$axi$$##channel##$$bits$$id()), unsigned(dut.get_io$$axi$$##channel##$$bits$$len()), \
    unsigned(dut.get_io$$axi$$##channel##$$bits$$size()), unsigned(dut.get_io$$axi$$##channel##$$bits$$burst()), \
    bool(dut.get_io$$axi$$##channel##$$bits$$lock()), unsigned(dut.get_io$$axi$$##channel##$$bits$$cache()), \
    unsigned(dut.get_io$$axi$$##channel##$$bits$$prot()), unsigned(dut.get_io$$axi$$##channel##$$bits$$qos()))
        const AddressBits ar = AXI_ADDRESS(ar), aw = AXI_ADDRESS(aw);
#undef AXI_ADDRESS
        const WriteBits wb{uint64_t(dut.get_io$$axi$$w$$bits$$data()),
            unsigned(dut.get_io$$axi$$w$$bits$$strb()), bool(dut.get_io$$axi$$w$$bits$$last())};
        const bool arv = dut.get_io$$axi$$ar$$valid(), awv = dut.get_io$$axi$$aw$$valid();
        const bool wv = dut.get_io$$axi$$w$$valid();
        if (heldAr) check(arv && ar == *heldAr, "AR payload changed under backpressure");
        if (heldAw) check(awv && aw == *heldAw, "AW payload changed under backpressure");
        if (heldW) check(wv && wb == *heldW, "W payload changed under backpressure");
        heldAr = arv && !arReady ? std::optional{ar} : std::nullopt;
        heldAw = awv && !awReady ? std::optional{aw} : std::nullopt;
        heldW = wv && !wReady ? std::optional{wb} : std::nullopt;
        arStalls += arv && !arReady; awStalls += awv && !awReady; wStalls += wv && !wReady;
        auto checkAddress = [&](const AddressBits &bits, const Transaction &t) {
            check(std::get<2>(bits) + 1 == t.beats && std::get<3>(bits) == 3 &&
                std::get<4>(bits) == 1 && !std::get<5>(bits) && !std::get<6>(bits) &&
                !std::get<7>(bits) && !std::get<8>(bits), "AXI burst attributes differ from independent request");
            check((std::get<0>(bits) & 4095) + t.beats * 8 <= 4096, "AXI burst crossed 4-KiB boundary");
        };
        if (arv && arReady) {
            auto &t = findOwner(DdrBase + std::get<0>(ar), false, false); checkAddress(ar, t);
            claimId(std::get<1>(ar), t); reads.push_back({t.n, t.axiId, 0, cycle + ReadLatency}); ++arCount;
        }
        if (awv && awReady) {
            auto &t = findOwner(DdrBase + std::get<0>(aw), true, false); checkAddress(aw, t);
            claimId(std::get<1>(aw), t);
            // Preparation belongs to each accepted AW, not to the currently
            // selected W owner. Accepting a later AW early hides this latency.
            awLeadCount += !writes.empty();
            writes.push_back({t.n, t.axiId, 0, cycle + WritePreparation}); ++awCount;
            awLeadPeak = std::max(awLeadPeak, unsigned(writes.size()));
        }
        const bool rFire = offeredR && dut.get_io$$axi$$r$$ready();
        const bool wFire = wv && wReady;
        simultaneousRW += rFire && wFire;
        if (wFire) {
            check(!writes.empty(), "ID-less W has no AW owner"); auto &w = writes.front(); const auto &t = tx[w.tx];
            check(cycle >= w.due && std::get<0>(wb) == payload(t.n, w.beat) &&
                std::get<1>(wb) == mask(t.n, w.beat) && std::get<2>(wb) == (w.beat + 1 == t.beats),
                "ID-less W data, strobes, last or FIFO burst ownership mismatch");
            updateMemory(deviceMemory, t.address + w.beat * 8, std::get<0>(wb), std::get<1>(wb));
            writeWireBytes += byteCount(std::get<1>(wb));
            if (!t.error) { usefulWriteBytes += byteCount(std::get<1>(wb)); ++usefulWBeats; }
            ++wCount;
            if (++w.beat == t.beats) { w.due = cycle + 4; responses.push_back(w); writes.pop_front(); }
        }
        if (rFire) {
            const Read delivered = *offeredR;
            const auto it = std::find_if(reads.begin(), reads.end(), [&](const Read &r) { return r.id == delivered.id; });
            check(it != reads.end() && it->tx == delivered.tx && it->beat == delivered.beat &&
                axiOwner[delivered.id] == int(delivered.tx), "R response ID/burst ownership mismatch");
            rInterleaves += previousR && *previousR != delivered.id; previousR = delivered.id;
            readTurn = (delivered.id + 1) % 4; ++rCount;
            usefulRBeats += !tx[delivered.tx].error;
            if (++it->beat == tx[it->tx].beats) {
                tx[it->tx].responseDone = true; axiOwner[it->id] = -1; reads.erase(it);
            }
            offeredR.reset();
        } else if (offeredR) ++rStalls;
        if (offeredB && dut.get_io$$axi$$b$$ready()) {
            const auto it = std::find_if(responses.begin(), responses.end(), [&](const Write &w) {
                return w.id == offeredB->id && w.tx == offeredB->tx;
            });
            check(it != responses.end() && axiOwner[it->id] == int(it->tx) && it->beat == tx[it->tx].beats,
                "B response preceded W completion or lost its owner");
            tx[it->tx].responseDone = true; axiOwner[it->id] = -1;
            responses.erase(it); offeredB.reset(); ++bCount;
        } else if (offeredB) ++bStalls;

        const bool romValid = dut.get_io$$rom$$a$$valid();
        const RequestBits romBits{uint64_t(dut.get_io$$rom$$a$$bits$$address()),
            uint64_t(dut.get_io$$rom$$a$$bits$$data()), unsigned(dut.get_io$$rom$$a$$bits$$source()),
            unsigned(dut.get_io$$rom$$a$$bits$$size()), unsigned(dut.get_io$$rom$$a$$bits$$opcode()),
            unsigned(dut.get_io$$rom$$a$$bits$$param()), unsigned(dut.get_io$$rom$$a$$bits$$mask()),
            bool(dut.get_io$$rom$$a$$bits$$corrupt())};
        if (heldRomA) check(romValid && romBits == *heldRomA, "ROM A changed under backpressure");
        heldRomA = romValid && !romReady ? std::optional{romBits} : std::nullopt;
        if (romValid && romReady) {
            auto &t = findOwner(std::get<0>(romBits), false, true);
            check(t.master == 0 && std::get<2>(romBits) == (16 | t.source) &&
                std::get<3>(romBits) == logSize(t.beats) && std::get<4>(romBits) == 4 &&
                !std::get<5>(romBits) && std::get<6>(romBits) == 255 && !std::get<7>(romBits),
                "ROM routed source, burst or request metadata mismatch");
            t.issued = true; romReads.push_back({t.n, unsigned(std::get<2>(romBits)), 0, cycle + 4}); ++romCount;
        }
        if (offeredRom && dut.get_io$$rom$$d$$ready()) {
            ++romBeats;
            if (++offeredRom->beat == tx[offeredRom->tx].beats) {
                tx[offeredRom->tx].responseDone = true; offeredRom.reset();
            }
        }

        unsigned dfires = 0;
        for (unsigned m = 0; m < Masters; ++m) {
            const bool dv = GET_MASTER(d$$valid);
            const ReplyBits db{uint64_t(GET_MASTER(d$$bits$$data)), unsigned(GET_MASTER(d$$bits$$source)),
                unsigned(GET_MASTER(d$$bits$$size)), unsigned(GET_MASTER(d$$bits$$opcode)),
                unsigned(GET_MASTER(d$$bits$$param)), unsigned(GET_MASTER(d$$bits$$sink)),
                bool(GET_MASTER(d$$bits$$denied)), bool(GET_MASTER(d$$bits$$corrupt))};
            if (heldD[m]) check(dv && db == *heldD[m], std::string(Names[m]) + " D changed under backpressure");
            heldD[m] = dv && !ready[m] ? std::optional{db} : std::nullopt;
            if (dv && !ready[m]) ++dStalls[m];
            if (!dv || !ready[m]) continue;
            const unsigned source = std::get<1>(db);
            check(source < sourceOwner[m].size() && sourceOwner[m][source] >= 0, "D has no live master/source owner");
            auto &t = tx[unsigned(sourceOwner[m][source])];
            check(t.aDone && t.issued && t.responseDone && !t.completed, "D duplicated or escaped before complete AXI burst");
            if (dBurst[m]) check(*dBurst[m] == t.n, "TL D interleaved two source bursts");
            else {
                dBurst[m] = t.n;
                for (unsigned older = m * Requests; older < t.n; ++older) if (tx[older].accepted && !tx[older].completed) {
                    ++reorderedD; break;
                }
            }
            check(std::get<2>(db) == logSize(t.beats) && std::get<3>(db) == (t.write ? 0U : 1U) &&
                !std::get<4>(db) && !std::get<5>(db) && std::get<6>(db) == t.error &&
                std::get<7>(db) == (!t.write && t.error), "D source/size/opcode/error metadata mismatch");
            const uint64_t expected = t.write || t.error ? 0 : initial(t.address + t.dBeat * 8);
            check(std::get<0>(db) == (expected ^ (mutateExpected ? 1ULL : 0ULL)), "independent expected-data mutation/oracle mismatch");
            if (!t.write && !t.error) usefulReadBytes += 8;
            ++dCount; ++dBeats[m]; ++dfires; usefulDBeats += !t.error;
            if (++t.dBeat == (t.write ? 1 : t.beats)) {
                t.completed = true; sourceOwner[m][source] = -1; dBurst[m].reset();
                --inFlight[m]; ++done; ++completed[m]; errorCount += t.error;
                if (completed[m] == 1) firstDone[m] = cycle; lastDone[m] = cycle;
                maxLatency[m] = std::max(maxLatency[m], cycle - t.firstCycle + 1);
            }
        }
        simultaneousD += dfires > 1;
        unsigned activeMasters = 0, live = 0, activeIds = 0;
        std::array<bool, Masters> axiMasters{};
        for (unsigned m = 0; m < Masters; ++m) { activeMasters += inFlight[m] != 0; live += inFlight[m]; }
        for (int owner : axiOwner) if (owner >= 0) { ++activeIds; axiMasters[tx[unsigned(owner)].master] = true; }
        mastersPeak = std::max(mastersPeak, activeMasters); maxLive = std::max(maxLive, live);
        idsPeak = std::max(idsPeak, activeIds);
        axiMastersPeak = std::max(axiMastersPeak, unsigned(std::count(axiMasters.begin(), axiMasters.end(), true)));
        readsPeak = std::max(readsPeak, unsigned(reads.size()));
        writesPeak = std::max(writesPeak, unsigned(writes.size() + responses.size()));
        readWriteOverlap += !reads.empty() && (!writes.empty() || !responses.empty());
    }

    check(accepted == Total && done == Total && reads.empty() && writes.empty() && responses.empty() && romReads.empty() &&
        !offeredR && !offeredB && !offeredRom, "lost transaction or forward-progress deadline");
    check(arCount == wantAr && awCount == wantAw && rCount == wantR && wCount == wantW &&
        bCount == wantAw && dCount == wantD && romCount == wantRom, "lost or duplicate AXI/ROM/TL transaction or beat");
    check(usefulReadBytes == wantReadBytes && usefulWriteBytes == wantWriteBytes && deviceMemory == expectedMemory,
        "independent byte accounting or masked memory contents mismatch");
    for (unsigned m = 0; m < Masters; ++m) {
        check(completed[m] == Requests && next[m] == Requests && inFlight[m] == 0 &&
            maxLatency[m] < 20000 && maxAcceptGap[m] < 20000, "master starvation, incomplete request or latency bound");
        check(std::all_of(sourceOwner[m].begin(), sourceOwner[m].end(), [](int n) { return n == -1; }), "live source leak");
    }
    check(std::all_of(tx.begin(), tx.end(), [](const Transaction &t) { return t.completed; }), "uncompleted transaction ledger entry");
    check(std::all_of(axiOwner.begin(), axiOwner.end(), [](int n) { return n == -1; }), "AXI ID leak");
    check(mastersPeak == 3 && axiMastersPeak >= 2 && idsPeak >= 3 && writesPeak == 2 &&
        readWriteOverlap && simultaneousRW && simultaneousD, "multi-master/read-write/channel concurrency coverage missing");
    if (pressure) check(errorCount && arStalls && awStalls && wStalls &&
        dStalls[0] && dStalls[1] && dStalls[2], "error or independently stalled-channel coverage missing");

    // Keep the ports live after the measured final response. A delayed duplicate
    // or leaked request must fail rather than disappear at the timing boundary.
    for (unsigned idle = 0; idle < 16; ++idle) {
        for (unsigned m = 0; m < Masters; ++m) { SET_MASTER(a$$valid, 0); SET_MASTER(d$$ready, 1); }
        dut.set_io$$axi$$ar$$ready(1); dut.set_io$$axi$$aw$$ready(1); dut.set_io$$axi$$w$$ready(1);
        dut.set_io$$axi$$r$$valid(0); dut.set_io$$axi$$b$$valid(0);
        dut.set_io$$rom$$a$$ready(1); dut.set_io$$rom$$d$$valid(0); dut.step();
        check(!dut.get_io$$axi$$ar$$valid() && !dut.get_io$$axi$$aw$$valid() &&
            !dut.get_io$$axi$$w$$valid() && !dut.get_io$$rom$$a$$valid(), "request leaked after all completions");
        for (unsigned m = 0; m < Masters; ++m) check(!GET_MASTER(d$$valid), "duplicate D after final completion");
    }

    std::cout << "BUS_FABRIC_PASS mode=" << (pressure ? "pressure" : "steady") << " cycles=" << cycle
        << " requests=" << done << " per_master=" << Requests << " ar=" << arCount << " aw=" << awCount
        << " rbeats=" << rCount << " wbeats=" << wCount << " b=" << bCount << " dbeats=" << dCount
        << " rom_requests=" << romCount << " rom_dbeats=" << romBeats << " errors=" << errorCount
        << " useful_read_bytes=" << usefulReadBytes << " useful_write_bytes=" << usefulWriteBytes
        << " write_wire_bytes=" << writeWireBytes << " masters_peak=" << mastersPeak
        << " axi_masters_peak=" << axiMastersPeak << " ids_peak=" << idsPeak
        << " reads_peak=" << readsPeak << " writes_peak=" << writesPeak << " live_tl_peak=" << maxLive
        << " aw_lead_count=" << awLeadCount << " aw_pending_w_peak=" << awLeadPeak
        << " read_write_overlap_cycles=" << readWriteOverlap << " simultaneous_rw_cycles=" << simultaneousRW
        << " simultaneous_d_cycles=" << simultaneousD << " reordered_d=" << reorderedD
        << " r_id_switches=" << rInterleaves << std::fixed << std::setprecision(6)
        << " r_beats_per_cycle=" << double(rCount) / cycle << " w_beats_per_cycle=" << double(wCount) / cycle
        << " d_beats_per_cycle=" << double(dCount) / cycle
        << " useful_r_beats_per_cycle=" << double(usefulRBeats) / cycle
        << " useful_w_beats_per_cycle=" << double(usefulWBeats) / cycle
        << " useful_d_beats_per_cycle=" << double(usefulDBeats) / cycle
        << " useful_bytes_per_cycle=" << double(usefulReadBytes + usefulWriteBytes) / cycle << '\n';
    for (unsigned m = 0; m < Masters; ++m) std::cout << "BUS_FABRIC_MASTER mode=" << (pressure ? "pressure" : "steady")
        << " master=" << Names[m] << " completed=" << completed[m] << " dbeats=" << dBeats[m]
        << " first_done=" << firstDone[m] << " last_done=" << lastDone[m]
        << " max_latency=" << maxLatency[m] << " max_accept_gap=" << maxAcceptGap[m]
        << " a_stalls=" << aStalls[m] << " d_stalls=" << dStalls[m] << '\n';
    std::cout << "BUS_FABRIC_STALLS mode=" << (pressure ? "pressure" : "steady")
        << " ar=" << arStalls << " aw=" << awStalls << " w=" << wStalls
        << " r=" << rStalls << " b=" << bStalls << '\n';
}
} // namespace

int main(int argc, char **argv) {
    try {
        check(argc <= 2, "usage: bus_fabric_throughput [--inject-data|--steady-only|--pressure-only]");
        const std::string option = argc == 2 ? argv[1] : "";
        check(option.empty() || option == "--inject-data" || option == "--steady-only" || option == "--pressure-only",
            "unknown argument");
        mutateExpected = option == "--inject-data";
        SBusFabricThroughputGsim dut;
        if (option != "--pressure-only") run(dut, false);
        if (option != "--steady-only" && !mutateExpected) run(dut, true);
        check(!mutateExpected, "expected-data negative control was not detected");
        std::cout << "BUS_FABRIC_ALL_PASS topology=nested-arbiter+registered-boundaries+2x2-crossbar+ddr"
            << " ddr_slots=4 write_slots=2 max_burst=16 unordered=1 read_latency=" << ReadLatency
            << " aw_to_w_preparation=" << WritePreparation
            << " scope=disjoint-backing-fabric-not-full-board-coherence\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "BUS_FABRIC_FAIL " << error.what() << '\n';
        return 1;
    }
}
