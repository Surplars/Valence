#pragma once
#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>
#ifndef CACHE_SETS
#define CACHE_SETS 16
#endif
#ifndef FETCH_WINDOW
#define FETCH_WINDOW 1
#endif
#ifndef FETCH_STAGED
#define FETCH_STAGED 1
#endif
namespace independent {
constexpr unsigned Sets = CACHE_SETS;
struct Packet { bool valid = false; uint64_t base = 0, data = 0; unsigned context = 0, errors = 0, pages = 0; };
struct Input {
    uint64_t pc = 0, frontier = 0, data = 0, pmpAddr = 0;
    bool enable = true, invalidate = false, pause = false, suppress = false;
    bool virtualized = false, ready = true, response = false;
    unsigned privilege = 3, errors = 0, pages = 0, pmpCfg = 0;
    unsigned context() const { return (unsigned(virtualized) << 2) | privilege; }
};
struct Lane { bool valid = false, error = false, page = false; uint32_t data = 0; uint64_t fault = 0; unsigned offset = 0; };
struct Output {
    bool request = false, responseReady = true, quiescent = true;
    uint64_t address = 0; unsigned mask = 0;
    std::array<Lane, 2> lanes{};
    std::array<Packet, 3> query{};
    bool newRequest = false, cancelPrepared = false;
};
struct Coverage {
    uint64_t cycles = 0, instructions = 0, requests = 0, responses = 0, stalls = 0;
    uint64_t staleResponses = 0, fillWithHit = 0, turnover = 0, prepareTurnover = 0, faults = 0, pageFaults = 0;
    uint64_t longInstructions = 0, shortInstructions = 0, straddles = 0, pmpDenied = 0;
    uint64_t contextChanges = 0, invalidations = 0, lockedStaleResponses = 0, wrappedQueries = 0;
    std::array<std::array<std::array<unsigned, 3>, 2>, Sets> hits{};
    std::array<std::array<unsigned, 2>, Sets> fills{};
};
// The oracle stores the original complete 64-bit byte address, never split tags or borrowed high bits.
// All packet relations use unsigned modulo-XLEN arithmetic and direct equality.
class Model {
public:
    std::array<std::array<Packet, 2>, Sets> rows{};
    std::array<bool, Sets> replace{};
    std::array<Packet, 3> snapshot{};
    Packet history{};
    bool pending = false, pendingStale = false, locked = false, lockedStale = false, maskCaptured = false;
    uint64_t pendingBase = 0, lockedBase = 0;
    unsigned pendingContext = 0, lockedContext = 0, lockedMask = 0;
    Coverage coverage{};
    unsigned previousContext = 3;
    static unsigned index(uint64_t base) { return unsigned((base / 8) % Sets); }
    static unsigned permission(const Input &i, uint64_t address, unsigned context) {
        if (context & 4) return 3;
        unsigned result = 0;
        for (unsigned word = 0; word < 2; ++word) {
            // Only entry zero is configured by this fixture; all other entries are OFF.
            using Wide = unsigned __int128;
            const Wide first = address + uint64_t(4 * word), last = first + 3;
            const unsigned mode = (i.pmpCfg >> 3) & 3;
            Wide lo = 0, hi = 0; bool active = mode != 0;
            if (mode == 1) { hi = Wide(i.pmpAddr) * 4; active = hi != 0; if (active) --hi; }
            if (mode == 2) { lo = Wide(i.pmpAddr) * 4; hi = lo + 3; }
            if (mode == 3) {
                unsigned ones = 0; while (ones < 54 && (i.pmpAddr & (UINT64_C(1) << ones))) ++ones;
                const Wide bytes = ones >= 53 ? Wide(1) << 56 : Wide(8) << ones;
                lo = (Wide(i.pmpAddr) * 4) & ~(bytes - 1); hi = lo + bytes - 1;
            }
            const bool overlap = active && first <= hi && last >= lo;
            const bool machine = (context & 3) == 3;
            const bool allow = overlap ? (first >= lo && last <= hi &&
                ((machine && !(i.pmpCfg & 128)) || (i.pmpCfg & 4))) : machine;
            result |= unsigned(allow) << word;
        }
        return result;
    }
    Output evaluate(const Input &i) {
        Output o;
        const uint64_t base = i.pc & ~UINT64_C(7);
        const unsigned context = i.context();
        const bool returning = i.response && pending && !pendingStale && pendingContext == context;
        for (unsigned offset = 0; offset < 3; ++offset) {
            auto &packet = o.query[offset]; packet.base = base + 8 * offset; packet.context = context;
            bool hit = false;
            for (unsigned way = 0; way < 2; ++way) {
                const auto &r = rows[index(packet.base)][way];
                if (!hit && r.valid && r.base == packet.base && r.context == context) {
                    packet = r; hit = true;
                    ++coverage.hits[index(packet.base)][way][offset];
                }
            }
            if (!hit && returning && pendingBase == packet.base)
                packet = {true, packet.base, i.data, context, i.errors, i.pages};
            if (offset && packet.base < base) ++coverage.wrappedQueries;
        }
        std::array<Packet, 3> supplied{};
        if (FETCH_WINDOW) {
            for (unsigned offset = 0; offset < 3; ++offset) {
                const uint64_t wanted = base + 8 * offset;
                for (const auto &old : snapshot) if (old.valid && old.base == wanted && old.context == context)
                    supplied[offset] = old;
                if (!supplied[offset].valid && offset == 0 && history.valid &&
                    history.base == wanted && history.context == context) supplied[offset] = history;
            }
        } else supplied = o.query;
        // Decode each lane from separately indexed halfwords. No copied prefix/alignment helper logic.
        uint64_t address = i.pc; bool prefix = true;
        for (auto &lane : o.lanes) {
            const unsigned byte = unsigned(address - base), firstRow = byte / 8, secondRow = (byte + 2) / 8;
            const unsigned halfIndex = (byte % 8) / 2, nextHalf = ((byte + 2) % 8) / 2;
            const auto &first = supplied[firstRow]; const auto &second = supplied[secondRow];
            const uint16_t low = first.data >> (16 * halfIndex), high = second.data >> (16 * nextHalf);
            const bool isLong = (low & 3) == 3;
            lane.valid = i.enable && !i.invalidate && prefix && first.valid && (!isLong || second.valid);
            lane.data = uint32_t(low) | (isLong ? uint32_t(high) << 16 : 0);
            const bool firstError = (first.errors >> ((byte % 8) / 4)) & 1;
            const bool firstPage = (first.pages >> ((byte % 8) / 4)) & 1;
            lane.error = firstError || (isLong && ((second.errors >> (((byte + 2) % 8) / 4)) & 1));
            lane.page = firstPage || (isLong && ((second.pages >> (((byte + 2) % 8) / 4)) & 1));
            lane.fault = address + (firstError || firstPage ? 0 : 2);
            lane.offset = unsigned(lane.fault - base) & 31;
            prefix = lane.valid;
            address += isLong ? 4 : 2;
        }
        const uint64_t wanted = o.query[0].valid ? base + 8 : base;
        const bool cached = o.query[0].valid && o.query[1].valid;
        const bool returningTarget = returning && !i.invalidate && pendingBase == wanted;
        const uint64_t frontier = i.frontier & ~UINT64_C(7);
        const bool frontierAllows = !FETCH_STAGED || (!i.suppress && (wanted == frontier || wanted == frontier + 8));
        o.newRequest = i.enable && !i.pause && !i.invalidate && (!pending || i.response) &&
            !cached && !returningTarget && frontierAllows;
        o.cancelPrepared = FETCH_STAGED && (!i.enable || i.pause || i.invalidate || i.suppress || lockedContext != context);
        o.request = FETCH_STAGED ? (locked && (maskCaptured || !o.cancelPrepared)) : (locked || o.newRequest);
        o.address = locked ? lockedBase : wanted;
        if (FETCH_STAGED) o.address = lockedBase;
        const uint64_t permissionBase = FETCH_STAGED ? lockedBase : wanted;
        const unsigned permissionContext = FETCH_STAGED ? lockedContext : context;
        o.mask = (FETCH_STAGED ? maskCaptured : locked) ? lockedMask : permission(i, permissionBase, permissionContext);
        o.quiescent = !pending && !locked;
        return o;
    }
    void advance(const Input &i, const Output &o) {
        ++coverage.cycles;
        coverage.prepareTurnover += FETCH_STAGED && i.response && !locked && o.newRequest;
        if (i.context() != previousContext) ++coverage.contextChanges;
        previousContext = i.context();
        if (i.invalidate) ++coverage.invalidations;
        for (const auto &lane : o.lanes) if (lane.valid) {
            ++coverage.instructions; coverage.faults += lane.error; coverage.pageFaults += lane.page;
            const bool longWord = (lane.data & 3) == 3;
            coverage.longInstructions += longWord; coverage.shortInstructions += !longWord;
        }
        uint64_t laneAddress = i.pc;
        for (const auto &lane : o.lanes) { if (lane.valid && (lane.data & 3) == 3 && (laneAddress & 7) == 6) ++coverage.straddles;
            laneAddress += (lane.data & 3) == 3 ? 4 : 2; }
        const bool oldPending = pending, oldStale = pendingStale, oldLocked = locked, oldLockedStale = lockedStale;
        const uint64_t oldPendingBase = pendingBase;
        const unsigned oldPendingContext = pendingContext, oldLockedContext = lockedContext;
        const auto oldRows = rows;
        if (FETCH_WINDOW) {
            history = snapshot[0]; history.valid &= !i.invalidate;
            snapshot = o.query; for (auto &p : snapshot) p.valid &= !i.invalidate;
        }
        if (FETCH_STAGED) {
            if (!locked && o.newRequest) {
                locked = true; lockedBase = o.query[0].valid ? (i.pc & ~UINT64_C(7)) + 8 : i.pc & ~UINT64_C(7);
                lockedContext = i.context(); lockedStale = false; maskCaptured = false;
            }
            if (oldLocked && !maskCaptured && o.cancelPrepared) { locked = false; lockedStale = false; }
            if (oldLocked && maskCaptured && o.cancelPrepared) lockedStale = true;
            if (o.request && !i.ready && !maskCaptured) { lockedMask = o.mask; maskCaptured = true; }
        } else if (o.request && !i.ready) {
            locked = true; lockedBase = o.address; lockedContext = i.context(); lockedMask = o.mask;
        }
        if (i.invalidate) {
            for (auto &set : rows) for (auto &r : set) r.valid = false;
            if (oldPending) pendingStale = true;
            if (oldLocked) lockedStale = true;
        }
        if (i.response) {
            if (!oldPending) throw std::runtime_error("oracle received response without owner");
            ++coverage.responses;
            pending = false; pendingStale = false;
            if (oldStale) { ++coverage.staleResponses; if (!i.invalidate) ++coverage.lockedStaleResponses; }
            const unsigned set = index(oldPendingBase);
            auto protect = [&](unsigned way) { const auto &r = oldRows[set][way]; return i.enable && r.valid &&
                r.base == (i.pc & ~UINT64_C(7)) && r.context == i.context(); };
            unsigned victim = protect(0) ? 1 : protect(1) ? 0 : !oldRows[set][0].valid ? 0 :
                !oldRows[set][1].valid ? 1 : unsigned(replace[set]);
            if (!oldStale) {
                const bool wasValid = rows[set][victim].valid;
                rows[set][victim] = {wasValid, oldPendingBase, i.data, oldPendingContext, i.errors, i.pages};
                if (!i.invalidate) {
                    rows[set][victim].valid = true; replace[set] = !victim; ++coverage.fills[set][victim];
                    for (const auto &r : o.query) if (r.valid && r.base != oldPendingBase) { ++coverage.fillWithHit; break; }
                }
            }
        }
        if (o.request && !i.ready) ++coverage.stalls;
        if (o.request && i.ready) {
            if (oldPending && !i.response) throw std::runtime_error("oracle exceeded single outstanding owner");
            ++coverage.requests; coverage.pmpDenied += o.mask != 3; coverage.turnover += i.response;
            pending = true; pendingBase = o.address; pendingContext = oldLocked ? oldLockedContext : i.context();
            pendingStale = i.invalidate || oldLockedStale || o.cancelPrepared;
            locked = false; lockedStale = false; maskCaptured = false;
        }
    }
};
}
