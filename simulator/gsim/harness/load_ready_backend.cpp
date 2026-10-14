#include "LoadReadyBackendGsim.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

// Only the public request, memory,
// reset, inspection and commit ports. There is deliberately no external recovery.
namespace {
constexpr uint64_t ram = UINT64_C(0x80010000);
constexpr uint64_t never = std::numeric_limits<uint64_t>::max();
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &) const = default;
    bool operator<(const Token &b) const { return std::tie(index, tag) < std::tie(b.index, b.tag); }
};
std::string tokenText(Token t) { return std::to_string(t.index) + ":" + std::to_string(t.tag); }
struct Request {
    bool valid = false, writes = true, word = false, usePc = false, useImmediate = true;
    bool memory = false, store = false, unsign = false, mulDiv = false;
    bool fetchFault = false, fetchPageFault = false, responseError = false, responsePage = false;
    unsigned rs1 = 0, rs2 = 0, rd = 1, op = 0, mOp = 0, branch = 0, size = 3;
    uint64_t immediate = 0, pc = 0, fetchTval = 0;
    uint32_t instruction = 0x13;
    std::string role;
};
struct Input {
    std::array<Request, 2> requests{};
    bool commit = true, response = false, error = false, page = false;
    uint64_t data = 0;
    unsigned inspect = 0;
    bool gateOnStart = false; Token gateToken{};
};
struct Completion { bool valid = false, exception = false; Token token{}; uint64_t data = 0, cause = 0, tval = 0; };
struct Commit { bool valid = false, writes = false; Token token{}; unsigned rd = 0; uint64_t data = 0, pc = 0; uint32_t instruction = 0; };
struct Lane {
    bool occupied = false, cancel = false, enqValid = false, enqReady = false, deqValid = false, deqReady = false;
    Token held{}, incoming{}, actual{}, storeToken{};
    unsigned destination = 0, source1 = 0, source2 = 0, promiseDestination = 0, heldMask = 0;
    uint64_t left = 0, right = 0, result = 0, incomingLeft = 0, incomingRight = 0;
    bool forwardable = false, destinationReady = false, promise = false;
    bool usePc = false, useImmediate = false, incomingMemory = false, prepared = false;
    uint64_t storeBase = 0, storeImmediate = 0, storeData = 0;
    bool storeDataReady = false, actualValid = false, accepted = false, actualException = false;
    bool write = false; unsigned writeDestination = 0; uint64_t writeData = 0;
    bool capture() const { return enqValid && enqReady; }
};
struct Start { bool fire = false, store = false; Token token{}; uint64_t a = 0, b = 0; };
struct Slot {
    Token owner{}, resultToken{}; unsigned phase=0, destination=0, heldDestination=0, publishDestination=0;
    bool start=false, startForward=false, request=false, response=false, valid=false, ready=false, cancelled=false, cancel=false;
    bool savedValid=false, held=false, publish=false, exception=false; uint64_t data=0, cause=0, tval=0, heldData=0;
};
struct Row { Token token{}; unsigned source1=0, source2=0; bool memory=false, store=false, mulDiv=false, system=false, usePc=false, useImmediate=false; };
struct ReadyEvent { bool valid=false; unsigned destination=0; };
struct Output {
    std::array<Slot,4> slot{}; std::array<Row,16> row{};
    std::array<ReadyEvent,3> wake{}; std::array<ReadyEvent,2> reserve{};
    unsigned rowReady1=0,rowReady2=0,memoryLive=0,selectedSlot=0;
    bool requestOwnerValid=false,serviceGate=false; Token requestOwner{};
    std::array<bool, 2> allocated{};
    std::array<Token, 2> token{};
    std::array<unsigned, 2> destination{}, source1{}, source2{};
    std::array<Completion, 2> complete{};
    std::array<Commit, 2> commit{};
    std::array<Lane, 2> lane{};
    Start memory{}, multiplier{}, divider{};
    bool request = false, requestWrite = false, responseReady = false, memoryBusy = false;
    uint64_t address = 0, requestData = 0; unsigned mask = 0, size = 0;
    bool redirect = false, recoveryAccepted = false, recovering = false;
    Token redirectToken{}, faultToken{}; uint64_t target = 0, inspected = 0;
    bool fault = false; uint64_t faultCause = 0, faultTval = 0;
    bool rawLsu = false, rawDivider = false, rawMultiplier = false;
    uint64_t readyMask = 0; unsigned pendingMask = 0, killedMask = 0, preparedMask = 0, issueCount = 0;
    std::array<unsigned, 2> loadForward{};
};
void drive(SLoadReadyBackendGsim &d, const Input &in) {
    d.set_io$$memory$$request$$ready(1);
    d.set_responseOnStart$$valid(in.gateOnStart);
    d.set_responseOnStart$$bits$$index(in.gateToken.index);
    d.set_responseOnStart$$bits$$tag(in.gateToken.tag);
    d.set_io$$memory$$response$$valid(in.response);
    d.set_io$$memory$$response$$bits$$data(in.data);
    d.set_io$$memory$$response$$bits$$error(in.error);
    d.set_io$$memory$$response$$bits$$pageFault(in.page);
#define DRIVE(N) \
    d.set_io$$allocate##N##$$valid(in.requests[N].valid); \
    d.set_io$$allocate##N##$$bits$$rename$$writesRd(in.requests[N].writes); \
    d.set_io$$allocate##N##$$bits$$rename$$rs1(in.requests[N].rs1); \
    d.set_io$$allocate##N##$$bits$$rename$$rs2(in.requests[N].rs2); \
    d.set_io$$allocate##N##$$bits$$rename$$rd(in.requests[N].rd); \
    d.set_io$$allocate##N##$$bits$$rename$$pc(in.requests[N].pc); \
    d.set_io$$allocate##N##$$bits$$rename$$instruction(in.requests[N].instruction); \
    d.set_io$$allocate##N##$$bits$$operation(in.requests[N].op); \
    d.set_io$$allocate##N##$$bits$$word(in.requests[N].word); \
    d.set_io$$allocate##N##$$bits$$usePc(in.requests[N].usePc); \
    d.set_io$$allocate##N##$$bits$$useImmediate(in.requests[N].useImmediate); \
    d.set_io$$allocate##N##$$bits$$immediate(in.requests[N].immediate); \
    d.set_io$$allocate##N##$$bits$$memory(in.requests[N].memory); \
    d.set_io$$allocate##N##$$bits$$store(in.requests[N].store); \
    d.set_io$$allocate##N##$$bits$$memorySize(in.requests[N].size); \
    d.set_io$$allocate##N##$$bits$$memoryUnsigned(in.requests[N].unsign); \
    d.set_io$$allocate##N##$$bits$$mulDiv(in.requests[N].mulDiv); \
    d.set_io$$allocate##N##$$bits$$mulDivOp(in.requests[N].mOp); \
    d.set_io$$allocate##N##$$bits$$controlFlow(in.requests[N].branch); \
    d.set_io$$allocate##N##$$bits$$fetchFault(in.requests[N].fetchFault); \
    d.set_io$$allocate##N##$$bits$$fetchPageFault(in.requests[N].fetchPageFault); \
    d.set_io$$allocate##N##$$bits$$fetchTval(in.requests[N].fetchTval); \
    d.set_io$$allocate##N##$$bits$$predictedNextPc$$valid(0); \
    d.set_io$$allocate##N##$$bits$$predictedNextPc$$bits(0); \
    d.set_io$$allocate##N##$$bits$$expandedInstruction(0); \
    d.set_io$$allocate##N##$$bits$$atomic(0); \
    d.set_io$$allocate##N##$$bits$$atomicOp(0); \
    d.set_io$$allocate##N##$$bits$$system(0);
    DRIVE(0) DRIVE(1)
#undef DRIVE
    d.set_io$$commitEnable(in.commit);
    d.set_io$$recover$$valid(0);
    d.set_io$$recover$$bits$$inclusive(0);
    d.set_io$$recover$$bits$$token$$index(0);
    d.set_io$$recover$$bits$$token$$tag(0);
    d.set_io$$inspectRegister(in.inspect);
}
Output sample(SLoadReadyBackendGsim &d) {
    Output o;
#define SAMPLE(N) \
    o.allocated[N] = d.get_io$$renamed##N##$$valid(); \
    o.token[N] = {unsigned(d.get_io$$renamed##N##$$bits$$token$$index()), uint64_t(d.get_io$$renamed##N##$$bits$$token$$tag())}; \
    o.destination[N] = d.get_io$$renamed##N##$$bits$$destination(); \
    o.source1[N] = d.get_io$$renamed##N##$$bits$$source1(); \
    o.source2[N] = d.get_io$$renamed##N##$$bits$$source2(); \
    o.complete[N] = {bool(d.get_io$$issued##N##$$valid()), bool(d.get_io$$issued##N##$$bits$$exception()), \
        {unsigned(d.get_io$$issued##N##$$bits$$token$$index()), uint64_t(d.get_io$$issued##N##$$bits$$token$$tag())}, \
        uint64_t(d.get_io$$issued##N##$$bits$$data()), uint64_t(d.get_io$$issued##N##$$bits$$cause()), uint64_t(d.get_io$$issued##N##$$bits$$tval())}; \
    o.commit[N] = {bool(d.get_io$$commit##N##$$valid()), bool(d.get_io$$commit##N##$$bits$$writesRd()), \
        {unsigned(d.get_io$$commit##N##$$bits$$token$$index()), uint64_t(d.get_io$$commit##N##$$bits$$token$$tag())}, \
        unsigned(d.get_io$$commit##N##$$bits$$rd()), uint64_t(d.get_io$$commit##N##$$bits$$data()), \
        uint64_t(d.get_io$$commit##N##$$bits$$pc()), uint32_t(d.get_io$$commit##N##$$bits$$instruction())}; \
    o.lane[N].occupied = d.get_observation##N##$$occupied(); \
    o.lane[N].cancel = d.get_observation##N##$$cancel(); \
    o.lane[N].enqValid = d.get_observation##N##$$enqValid(); \
    o.lane[N].enqReady = d.get_observation##N##$$enqReady(); \
    o.lane[N].deqValid = d.get_observation##N##$$deqValid(); \
    o.lane[N].deqReady = d.get_observation##N##$$deqReady(); \
    o.lane[N].held = {unsigned(d.get_observation##N##$$heldToken$$index()), uint64_t(d.get_observation##N##$$heldToken$$tag())}; \
    o.lane[N].destination = d.get_observation##N##$$heldDestination(); \
    o.lane[N].forwardable = d.get_observation##N##$$heldForwardable(); \
    o.lane[N].left = d.get_observation##N##$$heldLeft(); \
    o.lane[N].right = d.get_observation##N##$$heldRight(); \
    o.lane[N].result = d.get_observation##N##$$heldResult(); \
    o.lane[N].destinationReady = d.get_observation##N##$$heldDestinationReady(); \
    o.lane[N].promise = d.get_observation##N##$$promiseValid(); \
    o.lane[N].promiseDestination = d.get_observation##N##$$promiseDestination(); \
    o.lane[N].incoming = {unsigned(d.get_observation##N##$$incomingToken$$index()), uint64_t(d.get_observation##N##$$incomingToken$$tag())}; \
    o.lane[N].source1 = d.get_observation##N##$$incomingSource1(); \
    o.lane[N].source2 = d.get_observation##N##$$incomingSource2(); \
    o.lane[N].usePc = d.get_observation##N##$$incomingUsePc(); \
    o.lane[N].useImmediate = d.get_observation##N##$$incomingUseImmediate(); \
    o.lane[N].incomingLeft = d.get_observation##N##$$incomingLeft(); \
    o.lane[N].incomingRight = d.get_observation##N##$$incomingRight(); \
    o.lane[N].incomingMemory = d.get_observation##N##$$incomingMemory(); \
    o.lane[N].prepared = d.get_observation##N##$$prepared(); \
    o.lane[N].storeToken = {unsigned(d.get_observation##N##$$storePrepareToken$$index()), uint64_t(d.get_observation##N##$$storePrepareToken$$tag())}; \
    o.lane[N].storeBase = d.get_observation##N##$$storePrepareBase(); \
    o.lane[N].storeImmediate = d.get_observation##N##$$storePrepareImmediate(); \
    o.lane[N].storeData = d.get_observation##N##$$storePrepareData(); \
    o.lane[N].storeDataReady = d.get_observation##N##$$storePrepareDataReady(); \
    o.lane[N].heldMask = d.get_observation##N##$$capturedHeld0Mask(); \
    o.lane[N].actualValid = d.get_observation##N##$$actualCompletionValid(); \
    o.lane[N].accepted = d.get_observation##N##$$actualCompletionAccepted(); \
    o.lane[N].actual = {unsigned(d.get_observation##N##$$actualCompletionToken$$index()), uint64_t(d.get_observation##N##$$actualCompletionToken$$tag())}; \
    o.lane[N].actualException = d.get_observation##N##$$actualCompletionException(); \
    o.lane[N].write = d.get_observation##N##$$prfWriteValid(); \
    o.lane[N].writeDestination = d.get_observation##N##$$prfWriteDestination(); \
    o.lane[N].writeData = d.get_observation##N##$$prfWriteData();
    SAMPLE(0) SAMPLE(1)
#undef SAMPLE
#define START(NAME, MEMBER, A, B) \
    o.MEMBER.fire = d.get_##NAME##$$fire(); \
    o.MEMBER.token = {unsigned(d.get_##NAME##$$token$$index()), uint64_t(d.get_##NAME##$$token$$tag())}; \
    o.MEMBER.a = d.get_##NAME##$$##A(); o.MEMBER.b = d.get_##NAME##$$##B();
    START(memoryStart, memory, address, data)
    START(multiplierStart, multiplier, left, right)
    START(dividerStart, divider, left, right)
#undef START
    o.memory.store = d.get_memoryStart$$store();
    o.request = d.get_io$$memory$$request$$valid(); o.requestWrite = d.get_io$$memory$$request$$bits$$write();
    o.address = d.get_io$$memory$$request$$bits$$address(); o.requestData = d.get_io$$memory$$request$$bits$$data();
    o.mask = d.get_io$$memory$$request$$bits$$mask(); o.size = d.get_io$$memory$$request$$bits$$size();
    o.responseReady = d.get_io$$memory$$response$$ready(); o.memoryBusy = d.get_io$$memoryBusy();
    o.redirect = d.get_io$$redirect$$valid();
    o.redirectToken = {unsigned(d.get_io$$redirect$$bits$$token$$index()), uint64_t(d.get_io$$redirect$$bits$$token$$tag())};
    o.target = d.get_io$$redirect$$bits$$target(); o.recoveryAccepted = d.get_io$$recoveryAccepted();
    o.recovering = d.get_io$$recovering(); o.inspected = d.get_io$$committedValue();
    o.fault = d.get_io$$headException$$valid();
    o.faultToken = {unsigned(d.get_io$$headException$$bits$$token$$index()), uint64_t(d.get_io$$headException$$bits$$token$$tag())};
    o.faultCause = d.get_io$$headException$$bits$$cause(); o.faultTval = d.get_io$$headException$$bits$$tval();
    o.rawLsu = d.get_rawLsuCompletion(); o.rawDivider = d.get_rawDividerCompletion(); o.rawMultiplier = d.get_rawMultiplierCompletion();
    o.readyMask = d.get_physicalReadyMask(); o.pendingMask = d.get_pendingMask(); o.killedMask = d.get_killedMask();
    o.preparedMask = d.get_storePreparedMask(); o.issueCount = d.get_io$$issueCount();
    o.loadForward = {unsigned(d.get_io$$forwarded0()), unsigned(d.get_io$$forwarded1())};
    o.rowReady1=d.get_rowReady1(); o.rowReady2=d.get_rowReady2();
    o.memoryLive=d.get_memoryLiveMask(); o.selectedSlot=d.get_selectedSlot();
    o.serviceGate=d.get_responseServiceGate();
    o.requestOwnerValid=d.get_requestOwner$$valid();
    o.requestOwner={unsigned(d.get_requestOwner$$bits$$index()),uint64_t(d.get_requestOwner$$bits$$tag())};
    o.slot[0].phase=d.get_slot0$$phase();
    o.slot[0].start=d.get_slot0$$start();
    o.slot[0].startForward=d.get_slot0$$startForward();
    o.slot[0].request=d.get_slot0$$request();
    o.slot[0].response=d.get_slot0$$response();
    o.slot[0].valid=d.get_slot0$$completeValid();
    o.slot[0].ready=d.get_slot0$$completeReady();
    o.slot[0].cancelled=d.get_slot0$$cancelled();
    o.slot[0].cancel=d.get_slot0$$cancel();
    o.slot[0].savedValid=d.get_slot0$$savedDestination$$valid();
    o.slot[0].destination=d.get_slot0$$savedDestination$$bits();
    o.slot[0].held=d.get_slot0$$held$$valid();
    o.slot[0].heldDestination=d.get_slot0$$held$$bits$$destination();
    o.slot[0].heldData=d.get_slot0$$held$$bits$$data();
    o.slot[0].publish=d.get_slot0$$publish$$valid();
    o.slot[0].publishDestination=d.get_slot0$$publish$$bits();
    o.slot[0].exception=d.get_slot0$$result$$exception();
    o.slot[0].data=d.get_slot0$$result$$data();
    o.slot[0].cause=d.get_slot0$$result$$cause();
    o.slot[0].tval=d.get_slot0$$result$$tval();
    o.slot[0].owner={unsigned(d.get_slot0$$owner$$index()),uint64_t(d.get_slot0$$owner$$tag())};
    o.slot[0].resultToken={unsigned(d.get_slot0$$result$$token$$index()),uint64_t(d.get_slot0$$result$$token$$tag())};
    o.slot[1].phase=d.get_slot1$$phase();
    o.slot[1].start=d.get_slot1$$start();
    o.slot[1].startForward=d.get_slot1$$startForward();
    o.slot[1].request=d.get_slot1$$request();
    o.slot[1].response=d.get_slot1$$response();
    o.slot[1].valid=d.get_slot1$$completeValid();
    o.slot[1].ready=d.get_slot1$$completeReady();
    o.slot[1].cancelled=d.get_slot1$$cancelled();
    o.slot[1].cancel=d.get_slot1$$cancel();
    o.slot[1].savedValid=d.get_slot1$$savedDestination$$valid();
    o.slot[1].destination=d.get_slot1$$savedDestination$$bits();
    o.slot[1].held=d.get_slot1$$held$$valid();
    o.slot[1].heldDestination=d.get_slot1$$held$$bits$$destination();
    o.slot[1].heldData=d.get_slot1$$held$$bits$$data();
    o.slot[1].publish=d.get_slot1$$publish$$valid();
    o.slot[1].publishDestination=d.get_slot1$$publish$$bits();
    o.slot[1].exception=d.get_slot1$$result$$exception();
    o.slot[1].data=d.get_slot1$$result$$data();
    o.slot[1].cause=d.get_slot1$$result$$cause();
    o.slot[1].tval=d.get_slot1$$result$$tval();
    o.slot[1].owner={unsigned(d.get_slot1$$owner$$index()),uint64_t(d.get_slot1$$owner$$tag())};
    o.slot[1].resultToken={unsigned(d.get_slot1$$result$$token$$index()),uint64_t(d.get_slot1$$result$$token$$tag())};
    o.slot[2].phase=d.get_slot2$$phase();
    o.slot[2].start=d.get_slot2$$start();
    o.slot[2].startForward=d.get_slot2$$startForward();
    o.slot[2].request=d.get_slot2$$request();
    o.slot[2].response=d.get_slot2$$response();
    o.slot[2].valid=d.get_slot2$$completeValid();
    o.slot[2].ready=d.get_slot2$$completeReady();
    o.slot[2].cancelled=d.get_slot2$$cancelled();
    o.slot[2].cancel=d.get_slot2$$cancel();
    o.slot[2].savedValid=d.get_slot2$$savedDestination$$valid();
    o.slot[2].destination=d.get_slot2$$savedDestination$$bits();
    o.slot[2].held=d.get_slot2$$held$$valid();
    o.slot[2].heldDestination=d.get_slot2$$held$$bits$$destination();
    o.slot[2].heldData=d.get_slot2$$held$$bits$$data();
    o.slot[2].publish=d.get_slot2$$publish$$valid();
    o.slot[2].publishDestination=d.get_slot2$$publish$$bits();
    o.slot[2].exception=d.get_slot2$$result$$exception();
    o.slot[2].data=d.get_slot2$$result$$data();
    o.slot[2].cause=d.get_slot2$$result$$cause();
    o.slot[2].tval=d.get_slot2$$result$$tval();
    o.slot[2].owner={unsigned(d.get_slot2$$owner$$index()),uint64_t(d.get_slot2$$owner$$tag())};
    o.slot[2].resultToken={unsigned(d.get_slot2$$result$$token$$index()),uint64_t(d.get_slot2$$result$$token$$tag())};
    o.slot[3].phase=d.get_slot3$$phase();
    o.slot[3].start=d.get_slot3$$start();
    o.slot[3].startForward=d.get_slot3$$startForward();
    o.slot[3].request=d.get_slot3$$request();
    o.slot[3].response=d.get_slot3$$response();
    o.slot[3].valid=d.get_slot3$$completeValid();
    o.slot[3].ready=d.get_slot3$$completeReady();
    o.slot[3].cancelled=d.get_slot3$$cancelled();
    o.slot[3].cancel=d.get_slot3$$cancel();
    o.slot[3].savedValid=d.get_slot3$$savedDestination$$valid();
    o.slot[3].destination=d.get_slot3$$savedDestination$$bits();
    o.slot[3].held=d.get_slot3$$held$$valid();
    o.slot[3].heldDestination=d.get_slot3$$held$$bits$$destination();
    o.slot[3].heldData=d.get_slot3$$held$$bits$$data();
    o.slot[3].publish=d.get_slot3$$publish$$valid();
    o.slot[3].publishDestination=d.get_slot3$$publish$$bits();
    o.slot[3].exception=d.get_slot3$$result$$exception();
    o.slot[3].data=d.get_slot3$$result$$data();
    o.slot[3].cause=d.get_slot3$$result$$cause();
    o.slot[3].tval=d.get_slot3$$result$$tval();
    o.slot[3].owner={unsigned(d.get_slot3$$owner$$index()),uint64_t(d.get_slot3$$owner$$tag())};
    o.slot[3].resultToken={unsigned(d.get_slot3$$result$$token$$index()),uint64_t(d.get_slot3$$result$$token$$tag())};
    o.row[0].token={unsigned(d.get_row0$$token$$index()),uint64_t(d.get_row0$$token$$tag())};
    o.row[0].source1=d.get_row0$$source1();
    o.row[0].source2=d.get_row0$$source2();
    o.row[0].memory=d.get_row0$$memory();
    o.row[0].store=d.get_row0$$store();
    o.row[0].mulDiv=d.get_row0$$mulDiv();
    o.row[0].system=d.get_row0$$system();
    o.row[0].usePc=d.get_row0$$usePc();
    o.row[0].useImmediate=d.get_row0$$useImmediate();
    o.row[1].token={unsigned(d.get_row1$$token$$index()),uint64_t(d.get_row1$$token$$tag())};
    o.row[1].source1=d.get_row1$$source1();
    o.row[1].source2=d.get_row1$$source2();
    o.row[1].memory=d.get_row1$$memory();
    o.row[1].store=d.get_row1$$store();
    o.row[1].mulDiv=d.get_row1$$mulDiv();
    o.row[1].system=d.get_row1$$system();
    o.row[1].usePc=d.get_row1$$usePc();
    o.row[1].useImmediate=d.get_row1$$useImmediate();
    o.row[2].token={unsigned(d.get_row2$$token$$index()),uint64_t(d.get_row2$$token$$tag())};
    o.row[2].source1=d.get_row2$$source1();
    o.row[2].source2=d.get_row2$$source2();
    o.row[2].memory=d.get_row2$$memory();
    o.row[2].store=d.get_row2$$store();
    o.row[2].mulDiv=d.get_row2$$mulDiv();
    o.row[2].system=d.get_row2$$system();
    o.row[2].usePc=d.get_row2$$usePc();
    o.row[2].useImmediate=d.get_row2$$useImmediate();
    o.row[3].token={unsigned(d.get_row3$$token$$index()),uint64_t(d.get_row3$$token$$tag())};
    o.row[3].source1=d.get_row3$$source1();
    o.row[3].source2=d.get_row3$$source2();
    o.row[3].memory=d.get_row3$$memory();
    o.row[3].store=d.get_row3$$store();
    o.row[3].mulDiv=d.get_row3$$mulDiv();
    o.row[3].system=d.get_row3$$system();
    o.row[3].usePc=d.get_row3$$usePc();
    o.row[3].useImmediate=d.get_row3$$useImmediate();
    o.row[4].token={unsigned(d.get_row4$$token$$index()),uint64_t(d.get_row4$$token$$tag())};
    o.row[4].source1=d.get_row4$$source1();
    o.row[4].source2=d.get_row4$$source2();
    o.row[4].memory=d.get_row4$$memory();
    o.row[4].store=d.get_row4$$store();
    o.row[4].mulDiv=d.get_row4$$mulDiv();
    o.row[4].system=d.get_row4$$system();
    o.row[4].usePc=d.get_row4$$usePc();
    o.row[4].useImmediate=d.get_row4$$useImmediate();
    o.row[5].token={unsigned(d.get_row5$$token$$index()),uint64_t(d.get_row5$$token$$tag())};
    o.row[5].source1=d.get_row5$$source1();
    o.row[5].source2=d.get_row5$$source2();
    o.row[5].memory=d.get_row5$$memory();
    o.row[5].store=d.get_row5$$store();
    o.row[5].mulDiv=d.get_row5$$mulDiv();
    o.row[5].system=d.get_row5$$system();
    o.row[5].usePc=d.get_row5$$usePc();
    o.row[5].useImmediate=d.get_row5$$useImmediate();
    o.row[6].token={unsigned(d.get_row6$$token$$index()),uint64_t(d.get_row6$$token$$tag())};
    o.row[6].source1=d.get_row6$$source1();
    o.row[6].source2=d.get_row6$$source2();
    o.row[6].memory=d.get_row6$$memory();
    o.row[6].store=d.get_row6$$store();
    o.row[6].mulDiv=d.get_row6$$mulDiv();
    o.row[6].system=d.get_row6$$system();
    o.row[6].usePc=d.get_row6$$usePc();
    o.row[6].useImmediate=d.get_row6$$useImmediate();
    o.row[7].token={unsigned(d.get_row7$$token$$index()),uint64_t(d.get_row7$$token$$tag())};
    o.row[7].source1=d.get_row7$$source1();
    o.row[7].source2=d.get_row7$$source2();
    o.row[7].memory=d.get_row7$$memory();
    o.row[7].store=d.get_row7$$store();
    o.row[7].mulDiv=d.get_row7$$mulDiv();
    o.row[7].system=d.get_row7$$system();
    o.row[7].usePc=d.get_row7$$usePc();
    o.row[7].useImmediate=d.get_row7$$useImmediate();
    o.row[8].token={unsigned(d.get_row8$$token$$index()),uint64_t(d.get_row8$$token$$tag())};
    o.row[8].source1=d.get_row8$$source1();
    o.row[8].source2=d.get_row8$$source2();
    o.row[8].memory=d.get_row8$$memory();
    o.row[8].store=d.get_row8$$store();
    o.row[8].mulDiv=d.get_row8$$mulDiv();
    o.row[8].system=d.get_row8$$system();
    o.row[8].usePc=d.get_row8$$usePc();
    o.row[8].useImmediate=d.get_row8$$useImmediate();
    o.row[9].token={unsigned(d.get_row9$$token$$index()),uint64_t(d.get_row9$$token$$tag())};
    o.row[9].source1=d.get_row9$$source1();
    o.row[9].source2=d.get_row9$$source2();
    o.row[9].memory=d.get_row9$$memory();
    o.row[9].store=d.get_row9$$store();
    o.row[9].mulDiv=d.get_row9$$mulDiv();
    o.row[9].system=d.get_row9$$system();
    o.row[9].usePc=d.get_row9$$usePc();
    o.row[9].useImmediate=d.get_row9$$useImmediate();
    o.row[10].token={unsigned(d.get_row10$$token$$index()),uint64_t(d.get_row10$$token$$tag())};
    o.row[10].source1=d.get_row10$$source1();
    o.row[10].source2=d.get_row10$$source2();
    o.row[10].memory=d.get_row10$$memory();
    o.row[10].store=d.get_row10$$store();
    o.row[10].mulDiv=d.get_row10$$mulDiv();
    o.row[10].system=d.get_row10$$system();
    o.row[10].usePc=d.get_row10$$usePc();
    o.row[10].useImmediate=d.get_row10$$useImmediate();
    o.row[11].token={unsigned(d.get_row11$$token$$index()),uint64_t(d.get_row11$$token$$tag())};
    o.row[11].source1=d.get_row11$$source1();
    o.row[11].source2=d.get_row11$$source2();
    o.row[11].memory=d.get_row11$$memory();
    o.row[11].store=d.get_row11$$store();
    o.row[11].mulDiv=d.get_row11$$mulDiv();
    o.row[11].system=d.get_row11$$system();
    o.row[11].usePc=d.get_row11$$usePc();
    o.row[11].useImmediate=d.get_row11$$useImmediate();
    o.row[12].token={unsigned(d.get_row12$$token$$index()),uint64_t(d.get_row12$$token$$tag())};
    o.row[12].source1=d.get_row12$$source1();
    o.row[12].source2=d.get_row12$$source2();
    o.row[12].memory=d.get_row12$$memory();
    o.row[12].store=d.get_row12$$store();
    o.row[12].mulDiv=d.get_row12$$mulDiv();
    o.row[12].system=d.get_row12$$system();
    o.row[12].usePc=d.get_row12$$usePc();
    o.row[12].useImmediate=d.get_row12$$useImmediate();
    o.row[13].token={unsigned(d.get_row13$$token$$index()),uint64_t(d.get_row13$$token$$tag())};
    o.row[13].source1=d.get_row13$$source1();
    o.row[13].source2=d.get_row13$$source2();
    o.row[13].memory=d.get_row13$$memory();
    o.row[13].store=d.get_row13$$store();
    o.row[13].mulDiv=d.get_row13$$mulDiv();
    o.row[13].system=d.get_row13$$system();
    o.row[13].usePc=d.get_row13$$usePc();
    o.row[13].useImmediate=d.get_row13$$useImmediate();
    o.row[14].token={unsigned(d.get_row14$$token$$index()),uint64_t(d.get_row14$$token$$tag())};
    o.row[14].source1=d.get_row14$$source1();
    o.row[14].source2=d.get_row14$$source2();
    o.row[14].memory=d.get_row14$$memory();
    o.row[14].store=d.get_row14$$store();
    o.row[14].mulDiv=d.get_row14$$mulDiv();
    o.row[14].system=d.get_row14$$system();
    o.row[14].usePc=d.get_row14$$usePc();
    o.row[14].useImmediate=d.get_row14$$useImmediate();
    o.row[15].token={unsigned(d.get_row15$$token$$index()),uint64_t(d.get_row15$$token$$tag())};
    o.row[15].source1=d.get_row15$$source1();
    o.row[15].source2=d.get_row15$$source2();
    o.row[15].memory=d.get_row15$$memory();
    o.row[15].store=d.get_row15$$store();
    o.row[15].mulDiv=d.get_row15$$mulDiv();
    o.row[15].system=d.get_row15$$system();
    o.row[15].usePc=d.get_row15$$usePc();
    o.row[15].useImmediate=d.get_row15$$useImmediate();
    o.wake[0]={bool(d.get_wake0$$valid()),unsigned(d.get_wake0$$bits())};
    o.wake[1]={bool(d.get_wake1$$valid()),unsigned(d.get_wake1$$bits())};
    o.wake[2]={bool(d.get_wake2$$valid()),unsigned(d.get_wake2$$bits())};
    o.reserve[0]={bool(d.get_reserve0$$valid()),unsigned(d.get_reserve0$$bits())};
    o.reserve[1]={bool(d.get_reserve1$$valid()),unsigned(d.get_reserve1$$bits())};
    return o;
}

// Independent RV64 arithmetic. Numeric op values are the fixture's decoded-port
// API; arithmetic and architectural state are never obtained from DUT results.
uint64_t sext32(uint64_t v) { return (v & UINT64_C(0x80000000)) ? (v | UINT64_C(0xffffffff00000000)) : (v & UINT64_C(0xffffffff)); }
uint64_t arithmetic(const Request &r, uint64_t left, uint64_t right) {
    if (r.branch || r.store) return 0;
    if (r.mulDiv) {
        if (r.mOp == 0) return r.word ? sext32(left * right) : left * right;
        if (r.mOp == 5) {
            uint64_t a = r.word ? uint32_t(left) : left, b = r.word ? uint32_t(right) : right;
            uint64_t q = b ? a / b : (r.word ? UINT64_C(0xffffffff) : UINT64_MAX);
            return r.word ? sext32(q) : q;
        }
        throw std::runtime_error("host request uses unsupported M operation");
    }
    uint64_t a = r.usePc ? r.pc : left, b = r.useImmediate ? r.immediate : right, v = 0;
    unsigned sh = unsigned(b & (r.word ? 31 : 63));
    switch (r.op) {
    case 0: v = a + b; break;
    case 1: v = a - b; break;
    case 2: v = a ^ b; break;
    case 3: v = a | b; break;
    case 4: v = a & b; break;
    case 5: v = a << sh; break;
    case 6: v = r.word ? uint32_t(a) >> sh : a >> sh; break;
    case 7: {
        const unsigned width = r.word ? 32 : 64;
        const uint64_t x = r.word ? uint32_t(a) : a;
        v = x >> sh;
        if (sh && ((x >> (width - 1)) & 1)) v |= UINT64_MAX << (width - sh);
        break;
    }
    case 8: v = (a ^ (UINT64_C(1) << 63)) < (b ^ (UINT64_C(1) << 63)); break;
    case 9: v = a < b; break;
    case 63: return 0; // Directed reserved opcode; exception data is immaterial.
    default: throw std::runtime_error("host request uses unsupported ALU operation");
    }
    return r.word ? sext32(v) : v;
}
uint64_t initialBeat(uint64_t a) { return UINT64_C(0x80f1e2d3c4b5a697) ^ ((a & ~UINT64_C(7)) * UINT64_C(0x0102040810204081)); }
struct Bytes {
    std::map<uint64_t, uint8_t> changed;
    uint8_t byte(uint64_t a) const { auto i = changed.find(a); return i == changed.end() ? uint8_t(initialBeat(a) >> ((a & 7) * 8)) : i->second; }
    uint64_t read(uint64_t a, unsigned size, bool unsign = true) const {
        uint64_t v = 0; unsigned n = 1u << size;
        for (unsigned i = 0; i < n; ++i) v |= uint64_t(byte(a + i)) << (8 * i);
        if (!unsign && n < 8 && (v & (UINT64_C(1) << (8 * n - 1)))) v |= UINT64_MAX << (8 * n);
        return v;
    }
    void write(uint64_t a, unsigned size, uint64_t v) { for (unsigned i = 0; i < (1u << size); ++i) changed[a + i] = uint8_t(v >> (8 * i)); }
};
struct Entry {
    Token token{}; Request r{}; unsigned destination = 0, source1 = 0, source2 = 0;
    uint64_t left = 0, right = 0, expected = 0, address = 0, allocate = 0;
    std::optional<Token> leftOwner, rightOwner, heldProducer;
    uint64_t internalRequest = never, slotResponse = never, forwarded = never, capture = never, complete = never, start = never, prepare = never, request = never, response = never, retire = never, kill = never;
    unsigned captureLane = 2, memorySlot = 4, prepares = 0;
    bool exceptional = false, requested = false, responded = false, killed = false;
    uint64_t cause = 0, tval = 0;
};
struct Reply { Token token; uint64_t due = never, data = 0; bool error = false, page = false; };
struct Config { bool enabled = false, specified = false, trace = false; std::string mutation; unsigned applied = 0; } config;
struct Totals {
    uint64_t cases = 0, cycles = 0, retired = 0, heldCaptures = 0, heldAccepted = 0, acceptedWhileHeld = 0;
    uint64_t left = 0, right = 0, both = 0, stalled = 0, lsuStalls = 0, dividerStalls = 0, multiplierStalls = 0;
    uint64_t loadChains = 0, mChains = 0, storeChains = 0, killedChains = 0, completeChains = 0;
    uint64_t redirects = 0, killed = 0, prfReuse = 0, robReuse = 0, delayedKilledResponses = 0, replacements = 0;
    uint64_t requests = 0, responses = 0, storeWrites = 0, invalidStorePayload = 0, faults = 0;
    uint64_t stageCancels = 0, cancelledP0 = 0, cancelledHeldConsumer = 0, pairedHeldKill = 0;
    uint64_t loadWhileHeld = 0, mWhileHeld = 0, storeWhileHeld = 0, crossLaneReplacements = 0, mixedCaptures = 0;
    uint64_t mixedHeld0 = 0, exactReuseCases = 0, exactPrfBeforeReply = 0, exactRobBeforeReply = 0;
    uint64_t archHash = UINT64_C(1469598103934665603), serialSpan = 0, dualSpan = 0, serialRun = 0, dualRun = 0;
} total;
void hashValue(uint64_t &h, uint64_t v) { for (unsigned i = 0; i < 8; ++i) { h ^= uint8_t(v >> (8 * i)); h *= UINT64_C(1099511628211); } }

class Bench {
    SLoadReadyBackendGsim dut;
    std::array<uint64_t, 32> architectural{};
    std::array<std::optional<Token>, 32> committedOwner{};
    std::array<Lane, 2> previous{};
    bool havePrevious = false;
    Bytes architecturalMemory, actualMemory;
    std::deque<Reply> replies;
    std::deque<Token> internalRequests;
public:
    std::string name;
    uint64_t cycle = 0, nextPc = 0x1000, burstRelease = never;
    bool commitEnable = true, delayDependentReply = false;
    std::map<Token, Entry> entries;
    std::vector<Token> live;
    std::map<std::string, Token> roles;
    Output last{};
    uint64_t expectedPhysical=UINT64_C(0xffffffff), heldLoadCaptures=0, unselectedCaptures=0, twoHolderCaptures=0;
    uint64_t actualHandoffs=0, incomingHandoffs=0, soleCaptureHandoffs=0, holderCycles=0, twoHolderCycles=0;
    uint64_t drainReplacements=0, replacementCaptures=0;
    uint64_t firstUnselected=0, reserveChecks=0, nonordinaryChecks=0, ignoredSourceChecks=0, highPhysicalChecks=0;
    std::array<Slot,4> previousSlots{};
    uint64_t requests = 0, responses = 0, redirects = 0, heldCaptures = 0, acceptedWhileHeld = 0;
    uint64_t heldAccepted = 0, loadChains = 0, mChains = 0, storeChains = 0, completeChains = 0, killedChains = 0;
    uint64_t prfReuse = 0, robReuse = 0, killedResponses = 0, retired = 0, archHash = UINT64_C(1469598103934665603);
    uint64_t loadWhileHeld = 0, mWhileHeld = 0, storeWhileHeld = 0;
    std::set<Token> reusedPrf, reusedRob;
    std::set<Token> exactPrfBeforeReply, exactRobBeforeReply;
    std::map<uint64_t, unsigned> roiCaptures, roiCompletions;

    explicit Bench(std::string n) : name(std::move(n)) {
        drive(dut, {}); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    }
    void check(bool ok, const std::string &why) const {
        if (!ok) throw std::runtime_error("case=" + name + " cycle=" + std::to_string(cycle) + " " + why);
    }
    Entry &owner(Token t) { auto i = entries.find(t); check(i != entries.end(), "unknown full token " + tokenText(t)); return i->second; }
    bool isLive(Token t) const { return std::find(live.begin(), live.end(), t) != live.end(); }
    bool oldReady(const std::optional<Token> &t) const {
        return !t || (!entries.at(*t).exceptional && entries.at(*t).complete < cycle);
    }
    bool dependentOn(const Entry &e, Token t) const { return e.leftOwner == t || e.rightOwner == t; }
    bool mutation(const std::string &m) {
        if (config.mutation != m || config.applied) return false;
        ++config.applied;
        std::cerr << "LOAD_READY_MUTATION_APPLIED mutation=" << m << " case=" << name << " cycle=" << cycle << '\n';
        return true;
    }
    void trace(const std::string &event, const Entry &e) const {
        if (config.trace) std::cout << "LOAD_READY_EVENT case=" << name << " cycle=" << cycle << " event=" << event
            << " owner=" << tokenText(e.token) << " pc=" << e.r.pc << " role=" << e.r.role << " expected=" << e.expected << '\n';
    }
    void markChain(Entry &e, unsigned kind, const Output &o) {
        for (const auto &dep : {e.leftOwner, e.rightOwner}) if (dep) {
            auto &c = owner(*dep);
            if (c.heldProducer) {
                check(c.complete < cycle, "transitive consumer used C1 before its accepted PRF/ready edge");
                if (kind == 0) { ++loadChains; ++total.loadChains; }
                if (kind == 1) { ++mChains; ++total.mChains; }
                if (kind == 2) { ++storeChains; ++total.storeChains; }
                const auto &p = owner(*c.heldProducer);
                bool stillHeld = p.complete == never && o.lane[0].occupied && o.lane[0].held == p.token && !o.lane[0].deqReady;
                if (stillHeld && kind == 0) { ++loadWhileHeld; ++total.loadWhileHeld; }
                if (stillHeld && kind == 1) { ++mWhileHeld; ++total.mWhileHeld; }
                if (stillHeld && kind == 2) { ++storeWhileHeld; ++total.storeWhileHeld; }
                trace(kind == 0 ? "held_chain_load_start" : kind == 1 ? "held_chain_m_start" : "held_chain_store_prepare", e);
                break;
            }
        }
    }
    void applyMutations(Output &o) {
        if (config.applied) return;
        if (config.mutation == "value") for (unsigned n = 0; n < 2; ++n) if (o.complete[n].valid && entries.count(o.complete[n].token)) {
            const auto &e = entries.at(o.complete[n].token);
            if (e.heldProducer && !e.exceptional && mutation("value")) { o.complete[n].data ^= 1; return; }
        }
        for (unsigned n = 0; n < 2; ++n) if (o.lane[n].capture()) {
            auto &c = o.lane[n];
            if (config.mutation == "priority" && o.loadForward[n]) {
                for (const auto &p : o.lane) if (p.promise &&
                    (((o.loadForward[n] & 1) && !c.useImmediate && c.source2 == p.destination) ||
                     ((o.loadForward[n] & 2) && !c.usePc && c.source1 == p.destination)) && mutation("priority")) {
                    if (o.loadForward[n] & 1) c.incomingLeft = p.result; else c.incomingRight = p.result;
                    return;
                }
            }
            if (config.mutation == "replacement") for (unsigned p = 0; p < 2; ++p) {
                const auto &old = o.lane[p];
                if (!old.promise || !old.deqReady || !old.capture() || !entries.count(old.incoming)) continue;
                const auto &replacement = entries.at(old.incoming);
                if (replacement.expected == old.result) continue;
                if (!c.usePc && c.source1 == old.destination && mutation("replacement")) { c.incomingLeft = replacement.expected; return; }
                if (!c.useImmediate && c.source2 == old.destination && mutation("replacement")) { c.incomingRight = replacement.expected; return; }
            }
        }
    }
    void observeLoadReady(Output &o, const Input &in) {
        // Expected physical history uses prior independently authorized writes and reservations.
        check(o.readyMask==expectedPhysical,"independent physical-ready history mismatch");
        for(unsigned n=0;n<2;++n) {
            check(o.wake[n].valid==o.lane[n].write,"actual PRF wake/write qualification mismatch");
            if(o.wake[n].valid) check(o.wake[n].destination==o.lane[n].writeDestination,"actual wake address mismatch");
            bool reserve=o.allocated[n] && in.requests[n].writes && in.requests[n].rd;
            check(o.reserve[n].valid==reserve,"independent accepted allocation reserve mismatch");
            if(reserve) { check(o.reserve[n].destination==o.destination[n],"reserve destination mismatch"); ++reserveChecks; }
        }
        check(!o.wake[2].valid,"prohibited fast-load ready write appeared");
        if(in.gateOnStart) {
            check(!replies.empty() && replies.front().token==roles.at("L0"),"armed response lacks exact L0 debt");
            auto &l0=owner(replies.front().token);
            check(l0.requested && !l0.responded && in.data==replies.front().data && in.error==replies.front().error && in.page==replies.front().page,
                "armed response changed accepted debt/payload");
            bool event=o.memory.fire && o.memory.token==in.gateToken;
            check(o.serviceGate==event,"event gate differs from actual accepted F start");
            if(event) check(o.responseReady && owner(in.gateToken).r.role=="F" && !o.memory.store,"armed one-edge reply not consumed by exact F event");
        }
        unsigned successful=0, unselected=0;
        for(unsigned n=0;n<4;++n) {
            auto &h=o.slot[n];
            if(h.phase || h.valid || h.held) {
                auto &e=owner(h.owner);
                check(e.start<cycle,"raw slot lacks a previously accepted actual LSU start");
                bool localFault=e.exceptional && !e.r.responseError && !e.r.responsePage;
                bool done=(e.slotResponse<cycle || (localFault && e.start<cycle) || e.forwarded<cycle) && e.complete==never;
                bool expectedRaw=done && !(e.kill<cycle);
                check(h.valid==expectedRaw,"raw result-valid disagrees with independent operation/response lifecycle");
                if(h.valid) {
                    check(h.resultToken==e.token,"raw holder full-token mismatch");
                    check(h.exception==e.exceptional,"raw holder exception mismatch");
                    if(e.exceptional) check(h.cause==e.cause && h.tval==e.tval,"raw fault cause/tval mismatch");
                    else check(h.data==e.expected,"raw holder independent byte/arithmetic value mismatch");
                }
                check(h.savedValid==(e.r.writes && e.r.rd && !e.r.store),"saved load-destination permission mismatch");
                if(h.savedValid) check(h.destination==e.destination,"saved destination lost its full-token owner");
                bool expectedHeld=expectedRaw && !e.exceptional && e.r.writes && e.r.rd && !e.r.store;
                check(h.held==expectedHeld,"successful raw holder availability mismatch");
            }
            if(h.held) {
                auto &e=owner(h.owner);
                if(config.mutation=="wrong-fulltoken" && mutation("wrong-fulltoken")) h.owner.tag^=UINT64_C(1)<<63;
                check(h.owner==e.token && h.heldDestination==e.destination && h.heldData==e.expected,
                    "independent successful holder token/destination/data mismatch");
                check((o.memoryLive>>e.token.index)&1,"holder producer lost memoryLive (pending is not liveness)");
                check(!(expectedPhysical&(UINT64_C(1)<<e.destination)),"unaccepted live holder unexpectedly physical-ready");
                for(unsigned other=0;other<n;++other) if(o.slot[other].held)
                    check(o.slot[other].heldDestination!=h.heldDestination,"live holders alias physical destination");
                for(const auto &alu:o.lane) if(alu.promise)
                    check(alu.promiseDestination!=h.heldDestination,"load holder aliases ALU promise");
                ++successful; unselected+=!h.ready;
                if(config.mutation=="wrong-captured-data" || config.mutation=="unselected-mispair") {
                    for(auto &lane:o.lane) if(lane.capture()) {
                        bool targeted=config.mutation=="wrong-captured-data" || !h.ready;
                        if(targeted && !lane.usePc && lane.source1==h.heldDestination && mutation(config.mutation)) lane.incomingLeft^=1;
                        else if(targeted && !lane.useImmediate && lane.source2==h.heldDestination && mutation(config.mutation)) lane.incomingRight^=1;
                    }
                }
                bool oldNeed=false,incomingNeed=false,captureNeed=false;
                for(unsigned r=0;r<16;++r) if((o.pendingMask>>r)&1) {
                    const auto &q=o.row[r]; bool overwritten=false,captured=false,completed=false;
                    for(unsigned lane=0;lane<2;++lane) {
                        overwritten|=o.allocated[lane] && o.token[lane].index==r;
                        captured|=o.lane[lane].capture() && o.lane[lane].incoming==q.token;
                        completed|=o.complete[lane].valid && o.complete[lane].token==q.token;
                    }
                    if(!q.memory&&!q.mulDiv&&!q.system&&!((o.killedMask>>r)&1)&&!overwritten&&!captured&&!completed)
                        oldNeed|=q.source1==e.destination || q.source2==e.destination;
                }
                for(unsigned lane=0;lane<2;++lane) {
                    const auto &r=in.requests[lane];
                    if(o.allocated[lane]&&!r.memory&&!r.mulDiv)
                        incomingNeed|=o.source1[lane]==e.destination || o.source2[lane]==e.destination;
                    const auto &q=o.lane[lane];
                    if(q.capture()) captureNeed|=(!q.usePc&&q.source1==e.destination)||(!q.useImmediate&&q.source2==e.destination);
                }
                if(h.valid&&h.ready&&h.start) { ++drainReplacements; replacementCaptures+=captureNeed; }
                if(h.valid&&h.ready&&(oldNeed||incomingNeed||captureNeed)) {
                    if(config.mutation=="missing-prf-handoff" && mutation("missing-prf-handoff")) o.lane[0].write=false;
                    const auto &actual=o.lane[0];
                    bool reserved=false;for(const auto &r:o.reserve) reserved|=r.valid&&r.destination==e.destination;
                    check(actual.actualValid&&actual.accepted&&!actual.actualException&&actual.actual==e.token&&
                        actual.write&&actual.writeDestination==e.destination&&actual.writeData==e.expected&&
                        o.wake[0].valid&&o.wake[0].destination==e.destination&&!reserved,
                        "actual draining-load accepted ROB/PRF/data/wake/no-reserve handoff missing");
                    ++actualHandoffs;incomingHandoffs+=incomingNeed;soleCaptureHandoffs+=captureNeed&&!oldNeed&&!incomingNeed;
                }
            }
            bool expectedPublish=false;unsigned publishDestination=0;
            if(h.response && !h.start) {
                auto &e=owner(h.owner);
                expectedPublish=!e.r.store&&e.r.writes&&e.r.rd&&!in.error&&!in.page&&!h.cancelled&&!h.cancel;
                publishDestination=e.destination;
            }
            if(h.valid&&h.ready) expectedPublish=false;
            if(h.start) {
                auto &e=owner(o.memory.token);
                bool localFault=e.exceptional&&!e.r.responseError&&!e.r.responsePage;
                bool completed=localFault||h.startForward||h.response;
                bool fault=h.response ? (in.error||in.page) : localFault;
                expectedPublish=completed&&!fault&&!e.r.store&&e.r.writes&&e.r.rd;
                publishDestination=e.destination;
            }
            if(config.enabled) {
                if(config.mutation=="killed-owner-revival" && h.response && !h.start && entries.count(h.owner) && owner(h.owner).killed && mutation("killed-owner-revival")) {
                    h.publish=true;h.publishDestination=owner(h.owner).destination;
                }
                check(h.publish==expectedPublish,"independent result-writer publication mismatch");
                if(expectedPublish) check(h.publishDestination==publishDestination,"publication destination lineage mismatch");
            } else check(!h.publish,"OFF acquired optional publication interface behavior");
            if(havePrevious) {
                const auto &p=previousSlots[n];
                if(p.held&&!p.ready&&!p.cancel) check(h.held&&h.owner==p.owner&&h.destination==p.destination&&h.data==p.data,
                    "unselected held token/destination/value changed before real drain/cancel");
            }
        }
        holderCycles+=successful!=0;twoHolderCycles+=successful>=2;
        if(successful&&unselected&&roles.count("F")&&o.slot[2].valid&&o.slot[2].owner==roles.at("F")) {
            ++firstUnselected;check(o.selectedSlot==2&&o.slot[2].ready,"primed real RR did not prefer fault slot2");
        }
        for(unsigned r=0;r<16;++r) if((o.pendingMask>>r)&1) {
            const auto &row=o.row[r];auto &e=owner(row.token);
            check(row.token.index==r&&row.source1==e.source1&&row.source2==e.source2&&row.memory==e.r.memory&&row.store==e.r.store&&row.mulDiv==e.r.mulDiv&&!row.system&&row.usePc==e.r.usePc&&row.useImmediate==e.r.useImmediate,
                "pending row full-token/source/class differs from accepted owner");
            check(row.source1<48&&row.source2<48,"pending source escaped compact48 range");
            bool ordinary=!row.memory&&!row.mulDiv&&!row.system;
            auto held=[&](unsigned id){bool hit=false;for(const auto &h:o.slot)hit|=h.held&&h.heldDestination==id;return hit;};
            bool h1=held(row.source1),h2=held(row.source2);
            bool expected1=bool((expectedPhysical>>row.source1)&1)||(config.enabled&&ordinary&&h1);
            bool expected2=bool((expectedPhysical>>row.source2)&1)||(config.enabled&&ordinary&&h2);
            if(config.mutation=="false-nonordinary"&&!ordinary&&(h1||h2)&&mutation("false-nonordinary")) {
                if(h1)o.rowReady1|=1u<<r;else o.rowReady2|=1u<<r;
            }
            bool reservedDependency=false;
            for(unsigned lane=0;lane<2;++lane) if(last.allocated[lane])
                reservedDependency|=last.destination[lane]!=0&&(row.source1==last.destination[lane]||row.source2==last.destination[lane]);
            if(config.mutation=="reserve-priority"&&reservedDependency&&(!expected1||!expected2)&&mutation("reserve-priority")) {
                if(!expected1)o.rowReady1|=1u<<r;else o.rowReady2|=1u<<r;
            }
            check(bool((o.rowReady1>>r)&1)==expected1&&bool((o.rowReady2>>r)&1)==expected2,
                "both-source class-qualified physical-or-holder ready equality mismatch");
            nonordinaryChecks+=!ordinary&&(h1||h2);ignoredSourceChecks+=row.usePc||row.useImmediate;
            highPhysicalChecks+=row.source1>=32||row.source2>=32;
        }
    }
    void observeCapture(Lane &s, unsigned lane, const Output &o) {
        if (!s.capture()) return;
        auto &e = owner(s.incoming);
        check(isLive(e.token) && !e.killed, "capture of killed/nonlive consumer");
        check(e.capture == never && e.complete == never, "duplicate ALU enqueue");
        check(!e.r.memory && !e.r.mulDiv && !s.incomingMemory, "non-ALU work entered execution slot");
        check(s.source1 == e.source1 && s.source2 == e.source2 && s.usePc == e.r.usePc && s.useImmediate == e.r.useImmediate,
            "captured operand selector differs from accepted owner");
        if (!e.r.usePc) check(s.incomingLeft == e.left, "independent captured left value mismatch");
        if (!e.r.useImmediate) check(s.incomingRight == e.right, "independent captured right value mismatch");
        unsigned usedHolders=0, usedUnselected=0;
        for (unsigned h=0; h<4; ++h) if (o.slot[h].held) {
            const auto &q=o.slot[h]; auto &producer=owner(q.owner);
            unsigned mask=(!s.usePc && s.source1==q.heldDestination ? 1u:0u) |
                (!s.useImmediate && s.source2==q.heldDestination ? 2u:0u);
            if (!mask) continue;
            check(!q.cancel && !producer.killed && isLive(producer.token), "captured killed held load");
            if(mask&1) check(e.leftOwner==q.owner && s.incomingLeft==producer.expected,"held-load left full-token/value mismatch");
            if(mask&2) check(e.rightOwner==q.owner && s.incomingRight==producer.expected,"held-load right full-token/value mismatch");
            check(config.enabled || (q.valid && q.ready),"OFF captured genuinely unselected load");
            ++usedHolders; usedUnselected+=!q.ready;
        }
        if(usedHolders) ++heldLoadCaptures;
        if(usedUnselected) ++unselectedCaptures;
        if(usedHolders>=2) ++twoHolderCaptures;
        const auto &p = o.lane[0];
        unsigned heldMask = 0;
        if (p.occupied && !p.deqReady && p.promise) {
            if (!s.usePc && s.source1 == p.destination) heldMask |= 1;
            if (!s.useImmediate && s.source2 == p.destination) heldMask |= 2;
        }
        check(s.heldMask == heldMask, "passive held-capture mask disagrees with real handshake");
        if (heldMask) {
            check(lane == 1 && !p.cancel, "held producer granted illegal lane/cancel capture");
            auto &producer = owner(p.held);
            auto pPosition = std::find(live.begin(), live.end(), producer.token);
            auto cPosition = std::find(live.begin(), live.end(), e.token);
            check(producer.complete == never && !producer.killed && pPosition < cPosition,
                "held capture lacks older uncompleted full-token producer");
            if (heldMask & 1) check(e.leftOwner == p.held && e.left == producer.expected, "held left owner/value mismatch");
            if (heldMask & 2) check(e.rightOwner == p.held && e.right == producer.expected, "held right owner/value mismatch");
            check(!p.destinationReady && !((o.readyMask >> producer.destination) & 1), "held promise prematurely set producer ready");
            e.heldProducer = p.held; ++heldCaptures;
            ++total.heldCaptures; total.left += heldMask == 1; total.right += heldMask == 2; total.both += heldMask == 3;
            std::cout << "LOAD_READY_CAPTURE case=" << name << " cycle=" << cycle << " producer=" << tokenText(p.held)
                << " consumer=" << tokenText(e.token) << " mask=" << heldMask << " value=" << producer.expected << '\n';
        }
        auto available = [&](std::optional<Token> dep, unsigned physical) {
            if (oldReady(dep)) return true;
            for (const auto &q : o.lane) if (q.promise && !q.cancel && q.promiseDestination == physical && dep == q.held) return true;
            if (config.enabled && dep) for (const auto &h:o.slot)
                if (h.held && h.owner==*dep && h.heldDestination==physical && !h.cancel) return true;
            return dep && o.complete[0].valid && !o.complete[0].exception && o.complete[0].token == *dep && owner(*dep).r.memory;
        };
        if (!e.r.usePc) check(available(e.leftOwner, e.source1), "left capture has no ready/accepted-load/held-ALU authority");
        if (!e.r.useImmediate) check(available(e.rightOwner, e.source2), "right capture has no ready/accepted-load/held-ALU authority");
        for (unsigned pLane = 0; pLane < 2; ++pLane) {
            const auto &q = o.lane[pLane];
            bool consumes = (!s.usePc && s.source1 == q.destination) || (!s.useImmediate && s.source2 == q.destination);
            if (q.promise && q.deqReady && q.capture() && consumes && q.held != q.incoming) {
                ++total.replacements;
                if (pLane == 0 && lane == 1) ++total.crossLaneReplacements;
                if (config.trace) std::cout << "LOAD_READY_REPLACEMENT case=" << name << " producer_lane=" << pLane
                    << " consumer_lane=" << lane << " old=" << tokenText(q.held) << " next=" << tokenText(q.incoming)
                    << " consumer=" << tokenText(e.token) << '\n';
            }
        }
        for (unsigned pLane = 0; pLane < 2; ++pLane) {
            const auto &q = o.lane[pLane];
            if (q.promise &&
            (((o.loadForward[lane] & 1) && !s.useImmediate && s.source2 == q.destination) ||
             ((o.loadForward[lane] & 2) && !s.usePc && s.source1 == q.destination))) {
                ++total.mixedCaptures;
                if (pLane == 0 && !q.deqReady) ++total.mixedHeld0;
            }
        }
        e.capture = cycle; e.captureLane = lane;
        if (e.r.role == "roi") ++roiCaptures[cycle];
        trace("capture", e);
    }
    void observeStage(unsigned n, const Output &o) {
        const auto &s = o.lane[n];
        check(s.enqReady == (!s.occupied || s.deqReady), "execution credit equation changed");
        check(s.deqValid == (s.occupied && !s.cancel), "cancel did not suppress dequeue valid");
        if (havePrevious) {
            const auto &p = previous[n];
            if (p.occupied && !p.deqReady && !p.cancel) check(s.occupied && s.held == p.held && s.destination == p.destination &&
                s.left == p.left && s.right == p.right && s.result == p.result && s.forwardable == p.forwardable,
                "stalled owner/payload/result changed across edge");
            if (p.capture()) check(s.occupied && s.held == p.incoming, "captured owner not retained after capture edge");
            if (p.occupied && p.cancel && !p.capture()) check(!s.occupied, "cancelled owner did not clear after edge");
        }
        if (!s.occupied) { check(!s.promise, "empty slot manufactured promise"); return; }
        auto &e = owner(s.held);
        check(e.capture < cycle && e.captureLane == n && e.retire == never, "held slot lacks its prior real capture");
        check(s.destination == e.destination, "held destination differs from accepted owner");
        check(s.cancel == e.killed, "held cancellation disagrees with independent branch suffix");
        if (s.cancel) {
            ++total.stageCancels; total.cancelledP0 += e.r.role == "P0";
            total.cancelledHeldConsumer += bool(e.heldProducer);
            check(!s.capture(), "recovery captured a new execution owner on cancelled stage edge");
            check(!(s.accepted && s.actual == e.token), "killed held owner accepted completion");
            if (e.r.writes && e.r.rd) check(!(s.write && s.writeDestination == e.destination), "killed held owner wrote PRF");
            trace("occupied_cancel", e);
        }
        bool legalForward = e.r.writes && e.r.rd != 0 && !e.r.branch && !e.r.fetchFault && !e.r.fetchPageFault && e.r.op != 63;
        check(s.forwardable == legalForward, "held promise legality/old-owner metadata mismatch");
        if (!e.r.usePc) check(s.left == e.left, "held left arithmetic operand mismatch");
        if (!e.r.useImmediate) check(s.right == e.right, "held right arithmetic operand mismatch");
        if (legalForward) check(s.result == e.expected, "independent held ALU arithmetic mismatch");
        bool promise = legalForward && ((n == 0) || s.deqReady);
        check(s.promise == promise, "OFF/ON promise topology differs from selected variant");
        if (promise) check(s.promiseDestination == e.destination && e.destination != 0, "promise destination ownership");
        if (!s.deqReady) {
            ++total.stalled; total.lsuStalls += o.rawLsu; total.dividerStalls += o.rawDivider; total.multiplierStalls += o.rawMultiplier;
            check(n == 0, "unexpected blocked lane 1");
            check(!s.capture(), "held producer borrowed same-lane replacement credit");
            check(e.complete == never && !s.destinationReady, "stalled producer already completed/ready");
        }
        if (s.deqValid && s.deqReady) check(o.complete[n].valid && o.complete[n].token == e.token,
            "live ALU drain lacks actual accepted full-token completion");
    }
    void observeStart(const Start &s, unsigned kind, const Output &o) {
        if (!s.fire) return;
        auto &e = owner(s.token);
        check(isLive(s.token) && !e.killed && e.start == never, "start lacks unique live full-token owner");
        check(oldReady(e.leftOwner), "non-ALU start borrowed an unaccepted ALU promise");
        if (kind || e.r.store) check(oldReady(e.rightOwner), "non-ALU right operand preceded registered ready edge");
        if (kind == 0) {
            check(e.r.memory && e.r.store == s.store && s.a == e.address, "actual LSU start identity/address mismatch");
            if (e.r.store) check(s.b == e.right, "actual LSU store start data mismatch");
            else markChain(e, 0, o);
        } else {
            check(e.r.mulDiv && (e.r.mOp >= 4) == (kind == 2) && s.a == e.left && s.b == e.right,
                "actual M start differs from independent operands/class");
            markChain(e, 1, o);
        }
        if(kind==0) for(unsigned i=0;i<4;++i) if(o.slot[i].start) {
            e.memorySlot=i;if(o.slot[i].startForward)e.forwarded=cycle;
        }
        e.start = cycle; trace(kind == 0 ? "lsu_start" : "m_start", e);
    }
    void observeStore(const Lane &s, const Output &o) {
        if (!s.prepared) {
            if (s.incomingMemory) ++total.invalidStorePayload;
            return;
        }
        auto &e = owner(s.storeToken);
        check(isLive(e.token) && !e.killed && e.r.memory && e.r.store, "store preparation grant lacks live store owner");
        check(oldReady(e.leftOwner), "store base preparation used unaccepted promise");
        check(s.storeBase == e.left && s.storeImmediate == e.r.immediate, "raw store base/immediate mismatch");
        check(s.storeDataReady == oldReady(e.rightOwner), "store data-ready disagrees with accepted-edge history");
        if (s.storeDataReady) {
            check(s.storeData == e.right, "raw PRF store data mismatch");
            if (e.prepare == never) { e.prepare = cycle; markChain(e, 2, o); }
        }
        check((o.pendingMask >> e.token.index) & 1, "real store preparation lost pending owner");
        ++e.prepares; trace("store_prepare", e);
    }
    Output tick(std::array<Request, 2> incoming = {}, unsigned inspect = 0) {
        Input in; in.requests = incoming; in.commit = commitEnable; in.inspect = inspect;
        if (!replies.empty()) {
            const auto &r = replies.front(); const auto &e = entries.at(r.token);
            uint64_t due = e.r.role == "pressure" ? burstRelease : r.due;
            in.response = due <= cycle;
            if(e.r.role=="L0") {
                in.response=roles.count("F")!=0;
                in.gateOnStart=in.response;
                if(in.gateOnStart) in.gateToken=roles.at("F");
            }
            if(e.r.role=="L1") in.response=roles.count("L0") && owner(roles.at("L0")).responded;
            if (in.response) { in.data = r.data; in.error = r.error; in.page = r.page; }
        }
        drive(dut, in); dut.step(); Output o = sample(dut);
        applyMutations(o);
        observeLoadReady(o, in);
        check(o.issueCount <= 2, "global two-issue budget exceeded");
        check(o.inspected == architectural[inspect], "committed architectural register mismatch");
        if (o.redirect) {
            auto &branch = owner(o.redirectToken);
            check(isLive(branch.token) && branch.r.branch == 1 && branch.left == branch.right, "redirect lacks actual taken BEQ owner");
            check(o.target == branch.r.pc + branch.r.immediate, "independent branch target mismatch");
            auto at = std::find(live.begin(), live.end(), branch.token);
            for (auto i = at + 1; i != live.end(); ++i) { auto &e = owner(*i); e.killed = true; e.kill = cycle; ++total.killed; trace("kill", e); }
            live.erase(at + 1, live.end()); ++redirects; ++total.redirects;
            if (config.mutation == "kill") for (auto &[t, e] : entries) if (e.kill == cycle && e.capture != never && e.complete == never && e.heldProducer && mutation("kill")) {
                // A fabricated accepted completion for a genuinely killed owner
                // must fail the independent live-suffix acceptance equation.
                o.lane[1].actualValid = true; o.lane[1].actual = t; o.lane[1].accepted = true;
                o.lane[1].actualException = false; o.complete[1] = {true, false, t, e.expected, 0, 0}; break;
            }
        }
        // recoveryAccepted reports the internal real redirect too. It never
        // authorizes a synthetic external recovery boundary in this host.
        if (o.recoveryAccepted) check(o.redirect, "recovery acceptance without exposed real branch redirect");
        for (unsigned n = 0; n < 2; ++n) observeStage(n, o);
        if (o.lane[0].occupied && o.lane[0].cancel && o.lane[1].occupied && o.lane[1].cancel &&
            owner(o.lane[1].held).heldProducer == o.lane[0].held) ++total.pairedHeldKill;
        check(!(o.lane[0].promise && o.lane[1].promise) || o.lane[0].promiseDestination != o.lane[1].promiseDestination,
            "two live ALU promises alias one physical destination");
        for (unsigned n = 0; n < 2; ++n) observeCapture(o.lane[n], n, o);
        observeStart(o.memory, 0, o); observeStart(o.multiplier, 1, o); observeStart(o.divider, 2, o);
        for(const auto &slot:o.slot) if(slot.request) {
            Token token=slot.start ? o.memory.token : slot.owner;
            auto &e=owner(token);
            check(o.requestOwnerValid&&o.requestOwner==token,"LSU internal enqueue full-token lineage mismatch");
            check(e.start<=cycle&&e.internalRequest==never,"duplicate/unstarted internal request");
            e.internalRequest=cycle;internalRequests.push_back(token);
        }
        for(const auto &slot:o.slot) if(slot.response) {
            Token token=slot.start ? o.memory.token : slot.owner;
            auto &e=owner(token);
            check(e.internalRequest<=cycle&&e.slotResponse==never,"slot response lacks unique internal accepted request");
            if(!e.r.store) check(in.response&&o.responseReady&&!replies.empty()&&replies.front().token==token,
                "direct load slot response lacks exact external ordered debt");
            e.slotResponse=cycle;
        }
        for (const auto &s : o.lane) observeStore(s, o);
        for (auto t : live) {
            const auto &e = owner(t);
            if (e.r.store && ((o.preparedMask >> t.index) & 1))
                check(e.prepare < cycle, "persistent store preparation without an earlier authorized raw-PRF capture");
        }
        // Mutate both views only after real stage/operand observations have
        // been checked. The independent allocation ledger must reject this
        // unknown full tag, rather than a redundant wire-agreement check.
        if (config.mutation == "owner" && !config.applied) for (unsigned n = 0; n < 2; ++n) {
            auto &r = o.complete[n];
            if (r.valid && entries.count(r.token) && entries.at(r.token).heldProducer && mutation("owner")) {
                r.token.tag ^= UINT64_C(1) << 63; o.lane[n].actual = r.token; break;
            }
        }
        std::set<Token> acceptedNow;
        for (unsigned n = 0; n < 2; ++n) {
            const auto &s = o.lane[n]; const auto &r = o.complete[n];
            auto it = entries.find(s.actual);
            bool expectedAccept = s.actualValid && it != entries.end() && isLive(s.actual) && !it->second.killed &&
                it->second.complete == never && !acceptedNow.count(s.actual);
            check(s.accepted == expectedAccept, "independent full-token completion acceptance mismatch");
            check(s.accepted == r.valid, "issued pulse differs from actual ROB acceptance");
            if (!r.valid) { check(!s.write, "PRF write without accepted completion"); continue; }
            check(r.token == s.actual && r.exception == s.actualException, "accepted completion token/exception pins disagree");
            auto &e = owner(r.token);
            check(isLive(r.token) && !e.killed && e.complete == never, "accepted killed/stale/duplicate completion");
            check(r.exception == e.exceptional, "independent exception result mismatch");
            if (e.exceptional) check(r.cause == e.cause && r.tval == e.tval, "independent exception cause/tval mismatch");
            else check(r.data == e.expected, "independent completion arithmetic mismatch");
            bool writes = e.r.writes && e.r.rd && !e.exceptional;
            check(s.write == writes, "accepted completion PRF write qualification");
            if (writes) check(s.writeDestination == e.destination && s.writeData == e.expected, "independent PRF write owner/value mismatch");
            if (e.heldProducer) {
                ++heldAccepted; ++total.heldAccepted;
                const auto &p = owner(*e.heldProducer);
                if (p.complete == never && o.lane[0].occupied && o.lane[0].held == p.token && !o.lane[0].deqReady) {
                    ++acceptedWhileHeld; ++total.acceptedWhileHeld;
                    trace("C1_accepted_while_P0_held", e);
                }
            }
            e.complete = cycle; acceptedNow.insert(e.token);
            if (e.r.role == "roi") ++roiCompletions[cycle];
            trace("complete", e);
        }
        if (in.response && o.responseReady) {
            check(!replies.empty(), "response handshake without accepted request obligation");
            Reply r = replies.front(); replies.pop_front(); auto &e = owner(r.token);
            check(e.requested && !e.responded, "duplicate/unowned response"); e.responded = true; e.response = cycle;
            if (e.killed) { ++killedResponses; ++total.delayedKilledResponses; }
            if (e.r.store && !r.error && !r.page) actualMemory.write(e.address, e.r.size, e.right);
            ++responses; ++total.responses; trace("response", e);
        }
        if (o.request) {
            check(!internalRequests.empty(),"external request lacks prior internal full-token enqueue");
            Token requestToken=internalRequests.front();internalRequests.pop_front();
            auto &e=owner(requestToken);
            check(e.internalRequest<cycle&&!e.requested&&e.r.memory&&e.address==o.address&&e.r.store==o.requestWrite&&e.r.size==o.size,
                "external accepted request differs from ordered internal full-token debt");
            check(!e.killed||e.internalRequest<e.kill,"new unowned request after killed suffix");
            check(e.r.role!="F","local misaligned F illegally issued external request");
            check(o.address >= ram && o.address + (UINT64_C(1) << o.size) <= ram + 65536, "physical address outside fixture RAM");
            unsigned mask = ((1u << (1u << o.size)) - 1u) << (o.address & 7);
            check(o.mask == mask, "physical byte mask mismatch");
            if (e.r.store) {
                check(o.requestData == (e.right << ((e.address & 7) * 8)), "independent store bus data mismatch");
                ++total.storeWrites;
            }
            e.requested = true; e.request = cycle;
            uint64_t due = cycle + ((delayDependentReply && e.r.role == "desc_load") || e.r.role == "cancelled_load" ? 240 : 2);
            replies.push_back({e.token, due, actualMemory.read(e.address & ~UINT64_C(7), 3), e.r.responseError, e.r.responsePage});
            ++requests; ++total.requests; trace("request", e);
        }
        if (!commitEnable) check(!o.commit[0].valid && !o.commit[1].valid, "retirement ignored commitEnable");
        for (const auto &c : o.commit) if (c.valid) {
            check(!live.empty() && live.front() == c.token, "retirement violated independent program order/full token");
            auto &e = owner(c.token);
            check(!e.killed && !e.exceptional && e.complete != never && e.retire == never, "killed/exceptional/uncompleted duplicate retirement");
            check(c.rd == e.r.rd && c.pc == e.r.pc && c.instruction == e.r.instruction && c.data == e.expected,
                "independent architectural retirement record mismatch");
            check(c.writes == (e.r.writes && e.r.rd != 0), "architectural write/x0 qualification mismatch");
            if (c.writes) { architectural[c.rd] = e.expected; committedOwner[c.rd] = e.token; }
            if (e.r.store) architecturalMemory.write(e.address, e.r.size, e.right);
            e.retire = cycle; live.erase(live.begin()); ++retired; ++total.retired;
            hashValue(archHash, c.pc); hashValue(archHash, c.rd); hashValue(archHash, c.data); hashValue(archHash, c.writes);
            trace("retire", e);
        }
        auto values = architectural; auto owners = committedOwner;
        for (auto t : live) { const auto &e = owner(t); if (e.r.writes && e.r.rd) { values[e.r.rd] = e.expected; owners[e.r.rd] = t; } }
        check(!o.allocated[1] || o.allocated[0], "rename accepted nonprefix packet");
        for (unsigned n = 0; n < 2; ++n) if (o.allocated[n]) {
            const auto &r = incoming[n]; check(r.valid, "allocation without offered request");
            check(!entries.count(o.token[n]), "full allocation token reused");
            Entry e; e.token = o.token[n]; e.r = r; e.allocate = cycle; e.destination = o.destination[n];
            e.source1 = o.source1[n]; e.source2 = o.source2[n];
            e.left = values[r.rs1]; e.right = values[r.rs2]; e.leftOwner = owners[r.rs1]; e.rightOwner = owners[r.rs2];
            if (r.rs1 == 0) { e.left = 0; e.leftOwner.reset(); check(!e.source1, "x0 source1 mapping"); }
            if (r.rs2 == 0) { e.right = 0; e.rightOwner.reset(); check(!e.source2, "x0 source2 mapping"); }
            if (e.leftOwner) check(e.source1 == owner(*e.leftOwner).destination, "rename source1 does not name independent prior writer");
            if (e.rightOwner) check(e.source2 == owner(*e.rightOwner).destination, "rename source2 does not name independent prior writer");
            e.address = e.left + r.immediate;
            e.expected = r.memory && !r.store ? architecturalMemory.read(e.address, r.size, r.unsign) : arithmetic(r, e.left, e.right);
            if (r.fetchPageFault || r.fetchFault) { e.exceptional = true; e.cause = r.fetchPageFault ? 12 : 1; e.tval = r.fetchTval; }
            else if (r.op == 63 && !r.memory && !r.mulDiv && !r.branch) { e.exceptional = true; e.cause = 2; e.tval = r.instruction; }
            else if (r.memory && (e.address & ((1u << r.size) - 1))) { e.exceptional = true; e.cause = r.store ? 6 : 4; e.tval = e.address; }
            else if (r.responseError || r.responsePage) { e.exceptional = true; e.cause = r.responsePage ? (r.store ? 15 : 13) : (r.store ? 7 : 5); e.tval = e.address; }
            for (const auto &[oldToken, old] : entries) if (old.killed) {
                if (e.token.index == oldToken.index && e.token.tag != oldToken.tag && reusedRob.insert(oldToken).second) { ++robReuse; ++total.robReuse; }
                if (r.writes && r.rd && old.r.writes && old.r.rd && e.destination == old.destination && reusedPrf.insert(oldToken).second) { ++prfReuse; ++total.prfReuse; }
                if(old.r.role=="cancelled_load"&&old.requested&&!old.responded) {
                    if(e.token.index==oldToken.index&&e.token.tag!=oldToken.tag)exactRobBeforeReply.insert(oldToken);
                    if(r.writes&&r.rd&&e.destination==old.destination)exactPrfBeforeReply.insert(oldToken);
                }
                if ((old.r.role == "P0" || old.r.role == "C1") && roles.count("desc_load")) {
                    const auto &load = owner(roles.at("desc_load"));
                    if (load.killed && load.requested && !load.responded) {
                        if (e.token.index == oldToken.index && e.token.tag != oldToken.tag) exactRobBeforeReply.insert(oldToken);
                        if (r.writes && r.rd && e.destination == old.destination) exactPrfBeforeReply.insert(oldToken);
                    }
                }
            }
            entries.emplace(e.token, e); live.push_back(e.token);
            if (!r.role.empty() && r.role != "pressure" && r.role != "roi" && r.role != "reuse") roles[r.role] = e.token;
            if (r.writes && r.rd) { values[r.rd] = e.expected; owners[r.rd] = e.token; }
            trace("allocate", e);
        }
        if (o.fault) {
            check(!live.empty() && live.front() == o.faultToken, "head exception lacks exact independent head");
            const auto &e = owner(o.faultToken);
            check(e.exceptional && e.complete < cycle && o.faultCause == e.cause && o.faultTval == e.tval,
                "precise head exception differs from independent request");
        }
        for(const auto &w:o.wake) if(w.valid) expectedPhysical|=UINT64_C(1)<<w.destination;
        for(const auto &r:o.reserve) if(r.valid) expectedPhysical&=~(UINT64_C(1)<<r.destination);
        expectedPhysical|=1;
        previousSlots=o.slot;
        previous = o.lane; havePrevious = true; last = o; ++cycle; ++total.cycles; return o;
    }
    std::vector<Token> submit(std::vector<Request> program) {
        for (auto &r : program) { r.valid = true; r.pc = nextPc; nextPc += 4; }
        std::vector<Token> result; size_t at = 0;
        for (unsigned bound = 0; at < program.size() && bound < 1000; ++bound) {
            std::array<Request, 2> in{}; in[0] = program[at]; if (at + 1 < program.size()) in[1] = program[at + 1];
            auto o = tick(in);
            for (unsigned n = 0; n < 2; ++n) if (o.allocated[n]) { result.push_back(o.token[n]); ++at; }
        }
        check(at == program.size(), "bounded allocation timeout"); return result;
    }
    void wait(unsigned n) { while (n--) tick(); }
    void drain() {
        commitEnable = true;
        for (unsigned n = 0; n < 1600 && (!live.empty() || !replies.empty() || last.memoryBusy); ++n) tick();
        check(live.empty() && replies.empty() && internalRequests.empty() && !last.memoryBusy, "bounded pipeline/accepted-response drain timeout");
        check(requests == responses, "accepted physical request/response conservation");
        for (unsigned r = 0; r < 32; ++r) tick({}, r);
        check(actualMemory.changed == architecturalMemory.changed, "final independent architectural/bus byte-memory mismatch");
    }
    void report(bool drained = true) {
        if (drained) for (auto t : live) check(owner(t).exceptional, "report has live nonexceptional owner");
        uint64_t digest = archHash;
        for (auto v : architectural) hashValue(digest, v);
        for (auto [a, v] : architecturalMemory.changed) { hashValue(digest, a); hashValue(digest, v); }
        hashValue(total.archHash, digest); ++total.cases;
        std::cout << "LOAD_READY_CASE {\"name\":\"" << name << "\",\"enabled\":" << config.enabled
            << ",\"cycles\":" << cycle << ",\"retired\":" << retired << ",\"architectural_digest\":\"" << digest
            << "\",\"held_captures\":" << heldCaptures << ",\"held_accepted\":" << heldAccepted
            << ",\"C1_accepted_while_P0_held\":" << acceptedWhileHeld << ",\"load_chains\":" << loadChains
            << ",\"m_chains\":" << mChains << ",\"store_chains\":" << storeChains
            << ",\"load_start_while_P0_held\":" << loadWhileHeld << ",\"m_start_while_P0_held\":" << mWhileHeld
            << ",\"store_prepare_while_P0_held\":" << storeWhileHeld
            << ",\"complete_chains\":" << completeChains << ",\"killed_chains\":" << killedChains
            << ",\"redirects\":" << redirects << ",\"prf_reuse\":" << prfReuse << ",\"rob_reuse\":" << robReuse
            << ",\"P0_C1_prf_reused_before_killed_reply\":" << exactPrfBeforeReply.size()
            << ",\"P0_C1_rob_reused_before_killed_reply\":" << exactRobBeforeReply.size()
            << ",\"killed_responses\":" << killedResponses
            << ",\"held_load_captures\":" << heldLoadCaptures << ",\"unselected_captures\":" << unselectedCaptures
            << ",\"two_holder_captures\":" << twoHolderCaptures << ",\"two_holder_cycles\":" << twoHolderCycles
            << ",\"actual_handoffs\":" << actualHandoffs << ",\"incoming_handoffs\":" << incomingHandoffs
            << ",\"sole_capture_handoffs\":" << soleCaptureHandoffs << ",\"nonordinary_checks\":" << nonordinaryChecks
            << ",\"reserve_checks\":" << reserveChecks << ",\"ignored_source_checks\":" << ignoredSourceChecks
            << ",\"high_physical_checks\":" << highPhysicalChecks << ",\"drain_replacements\":" << drainReplacements << ",\"replacement_captures\":" << replacementCaptures << "}\n";
    }
};

Request imm(unsigned rd, unsigned rs, uint64_t value, std::string role = {}) {
    Request r; r.valid = true; r.rd = rd; r.rs1 = rs; r.immediate = value; r.role = std::move(role); return r;
}
Request reg(unsigned rd, unsigned a, unsigned b, std::string role = {}) {
    Request r = imm(rd, a, 0, std::move(role)); r.rs2 = b; r.useImmediate = false; return r;
}
Request load(unsigned rd, unsigned a, uint64_t offset, std::string role = {}) {
    Request r = imm(rd, a, offset, std::move(role)); r.memory = true; return r;
}
Request store(unsigned a, unsigned b, uint64_t offset, std::string role = {}) {
    Request r = load(0, a, offset, std::move(role)); r.rs2 = b; r.store = true; r.writes = false; return r;
}
Request mul(unsigned rd, unsigned a, unsigned b, std::string role = {}) {
    Request r = reg(rd, a, b, std::move(role)); r.mulDiv = true; return r;
}
Request divu(unsigned rd, unsigned a, unsigned b, std::string role = {}) {
    Request r = mul(rd, a, b, std::move(role)); r.mOp = 5; return r;
}
Request branch(unsigned a) { Request r = reg(0, a, a, "branch"); r.writes = false; r.branch = 1; r.immediate = 0x100; r.instruction = 0x63; return r; }
void setup(Bench &b) {
    b.submit({imm(10, 0, ram), imm(25, 0, UINT64_C(0xfedcba9876543210)), imm(26, 0, 7)}); b.drain();
}
unsigned longest(const std::map<uint64_t, unsigned> &events, unsigned width) {
    unsigned best = 0, run = 0; uint64_t prev = never;
    for (auto [c, n] : events) { run = n == width ? ((prev != never && c == prev + 1) ? run + 1 : 1) : 0; best = std::max(best, run); prev = c; }
    return best;
}
void throughput(bool dual) {
    Bench b(dual ? "dual_independent" : "serial_II1");
    std::vector<Request> p;
    for (unsigned i = 0; i < 64; ++i) {
        p.push_back(imm(1, 1, 1, "roi"));
        if (dual) p.push_back(imm(2, 2, 3, "roi"));
    }
    b.submit(p); b.drain();
    unsigned width = dual ? 2 : 1;
    unsigned captureRun = longest(b.roiCaptures, width), completeRun = longest(b.roiCompletions, width);
    b.check(captureRun >= 24 && completeRun >= 24, "missing sustained ordinary ALU II=1/two-wide throughput");
    uint64_t span = b.roiCaptures.rbegin()->first - b.roiCaptures.begin()->first + 1;
    if (dual) { total.dualSpan = span; total.dualRun = captureRun; } else { total.serialSpan = span; total.serialRun = captureRun; }
    std::cout << "LOAD_READY_THROUGHPUT {\"name\":\"" << b.name << "\",\"instructions\":" << p.size()
        << ",\"capture_span\":" << span << ",\"longest_capture_run\":" << captureRun
        << ",\"longest_completion_run\":" << completeRun << ",\"width\":" << width << "}\n";
    b.report();
}

void transitive(unsigned phase, unsigned mask, bool kill) {
    Bench b(std::string(kill ? "kill" : "drain") + "_phase" + std::to_string(phase) + "_mask" + std::to_string(mask));
    setup(b); b.commitEnable = true; b.delayDependentReply = kill;
    if (kill) b.submit({divu(24, 25, 26, "older_divider"), branch(24)});
    // Four real accepted reads provide a contiguous ordered response burst.
    // Payloads/latencies are identical in OFF and ON; no internal pin is forced.
    b.submit({load(20, 10, 0x100, "pressure"), load(21, 10, 0x108, "pressure"),
              load(22, 10, 0x110, "pressure"), load(23, 10, 0x118, "pressure")});
    // submit can already accept bus requests, so count the four role owners.
    for (unsigned n = 0; n < 120; ++n) {
        unsigned got = 0; for (const auto &[t, e] : b.entries) got += e.r.role == "pressure" && e.requested;
        if (got == 4) break;
        b.tick();
    }
    unsigned got = 0; for (const auto &[t, e] : b.entries) got += e.r.role == "pressure" && e.requested;
    b.check(got == 4 && b.redirects == 0, "four real pressure reads must be accepted before branch resolves");
    b.burstRelease = b.cycle + phase;
    Request p = imm(5, 0, mask == 3 ? ram / 2 : ram, "P0");
    Request c = mask == 1 ? imm(6, 5, 0x180, "C1") : mask == 2 ? reg(6, 0, 5, "C1") : reg(6, 5, 5, "C1");
    // Oldest goes to lane 1, second-oldest to lane 0 in this real ranked backend.
    b.submit({imm(7, 0, 0x51, "older_dummy"), p});
    b.submit({c});
    b.submit({load(8, 6, mask == 1 ? 0 : 0x180, "desc_load"), mul(9, 6, 26, "desc_m"),
              store(6, 6, 0x300, "desc_store")});
    if (kill) {
        for (unsigned n = 0; n < 160 && !b.redirects; ++n) b.tick();
        b.check(b.redirects == 1, "real older DIVU-dependent branch did not redirect");
        for (const std::string role : {"P0", "C1", "desc_load", "desc_m", "desc_store"}) {
            b.check(b.roles.count(role), "directed suffix owner was not accepted before redirect");
            const auto &e = b.owner(b.roles.at(role));
            b.check(e.killed && e.retire == never, "older branch failed precise suffix kill");
        }
        const auto &cEntry = b.owner(b.roles.at("C1"));
        if (cEntry.heldProducer && cEntry.complete != never && b.loadChains && b.mChains && b.storeChains) {
            ++b.killedChains; ++total.killedChains;
        }
        b.commitEnable = true; b.wait(8);
        // A real new head DIVU keeps following accepted ALUs live long enough
        // to consume the free physical pool, including the exact killed P0/C1
        // destinations. commitEnable stays true throughout.
        std::vector<Request> reuse{divu(30, 25, 26, "reuse_blocker")};
        for (unsigned n = 0; n < 96; ++n) reuse.push_back(imm(1 + n % 12, 0, UINT64_C(0x200) + n, "reuse"));
        b.submit(reuse); b.drain();
        b.check(b.prfReuse && b.robReuse, "killed suffix never exercised physical destination/full-tag ROB-index reuse");
        const auto &dependentLoad = b.owner(b.roles.at("desc_load"));
        if (dependentLoad.requested) {
            b.check(dependentLoad.killed && dependentLoad.responded && b.exactPrfBeforeReply.size() == 2 &&
                b.exactRobBeforeReply.size() == 2,
                "P0/C1 exact physical and full-tag ROB reuse must precede killed descendant response drain: prf=" +
                std::to_string(b.exactPrfBeforeReply.size()) + " rob=" + std::to_string(b.exactRobBeforeReply.size()));
            ++total.exactReuseCases;
            total.exactPrfBeforeReply += b.exactPrfBeforeReply.size();
            total.exactRobBeforeReply += b.exactRobBeforeReply.size();
        }
    } else {
        b.wait(32); b.drain();
        const auto &cEntry = b.owner(b.roles.at("C1"));
        if (cEntry.heldProducer && cEntry.complete != never && b.loadChains && b.mChains && b.storeChains) {
            ++b.completeChains; ++total.completeChains;
        }
    }
    b.report();
}

void mixed(unsigned phase) {
    Bench b("mixed_load_alu_phase" + std::to_string(phase)); setup(b); b.commitEnable = true;
    b.submit({load(20, 10, 0x200, "pressure"), load(21, 10, 0x208, "pressure")});
    for (unsigned n = 0; b.requests < 2 && n < 100; ++n) b.tick();
    b.check(b.requests == 2, "mixed case lacks real accepted reads");
    b.burstRelease = b.cycle + phase;
    b.submit({imm(7, 0, 99, "older_dummy"), imm(5, 0, 31, "P0")});
    b.submit({reg(6, 20, 5, "mixed_consumer")});
    b.wait(20); b.drain(); b.report();
}

void crossLaneRefill() {
    Bench b("old_P0_cross_lane_consume_refill");
    b.submit({imm(7, 0, 55), imm(5, 0, 19, "P0")});
    b.submit({imm(6, 5, 3, "C1"), imm(8, 0, 91, "replacement")});
    b.drain(); b.report();
}

void occupiedKill() {
    Bench b("occupied_P0_C1_branch_kill"); setup(b);
    b.submit({divu(24, 25, 26, "older_divider"), branch(24)});
    b.submit({load(20, 10, 0x100, "pressure"), load(21, 10, 0x108, "pressure"),
              load(22, 10, 0x110, "pressure"), load(23, 10, 0x118, "pressure")});
    for (unsigned n = 0; b.requests < 4 && n < 120; ++n) b.tick();
    b.check(b.requests == 4 && !b.redirects, "occupied-kill pressure obligations absent");
    // Fixed, identical OFF/ON input delay. The real older branch supplies lane 1;
    // the four accepted replies hold P0 in lane 0 while C1 captures in lane 1.
    b.wait(60); b.burstRelease = b.cycle;
    b.submit({imm(5, 0, 19, "P0")});
    b.submit({imm(6, 5, 3, "C1")});
    for (unsigned n = 0; !b.redirects && n < 80; ++n) b.tick();
    b.check(b.redirects == 1, "occupied-kill real branch redirect absent");
    for (const std::string role : {"P0", "C1"}) {
        b.check(b.roles.count(role), "occupied-kill suffix was not actually accepted");
        const auto &e = b.owner(b.roles.at(role));
        b.check(e.killed && e.retire == never, "occupied-kill suffix escaped recovery");
    }
    b.drain(); b.report();
}

void faults() {
    for (unsigned kind = 0; kind < 6; ++kind) {
        Bench b("fault_" + std::to_string(kind)); setup(b); b.commitEnable = true;
        Request p;
        if (kind < 3) { p = load(5, 10, kind == 2 ? 1 : 0x400, "faulting"); p.responseError = kind == 0; p.responsePage = kind == 1; }
        else { p = imm(5, 0, 19, "faulting"); p.fetchFault = kind == 3; p.fetchPageFault = kind == 4; p.fetchTval = 0x90000004; if (kind == 5) { p.op = 63; p.instruction = 0xffffffff; } }
        b.submit({p, reg(6, 5, 5, "fault_dependent")});
        bool seen = false;
        for (unsigned n = 0; n < 100; ++n) { b.tick(); seen |= b.last.fault; }
        b.check(seen, "expected precise head exception never appeared");
        auto &dep = b.owner(b.roles.at("fault_dependent"));
        b.check(dep.capture == never && dep.complete == never && dep.retire == never, "faulting producer made dependent available");
        ++total.faults; b.report(false);
    }
    // A later fault remains behind a real long divider. The bare fixture can
    // expose precise head exception, but cannot perform integrated trap recovery.
    Bench b("late_fault_behind_older_divider"); setup(b); b.commitEnable = true;
    auto bad = load(5, 10, 0x480, "faulting"); bad.responseError = true;
    b.submit({divu(24, 25, 26, "older_divider"), bad, imm(7, 0, 17), imm(8, 7, 3)});
    b.wait(110); b.commitEnable = true;
    bool seen = false; for (unsigned n = 0; n < 60; ++n) { b.tick(); seen |= b.last.fault; }
    b.check(seen && b.owner(b.roles.at("faulting")).retire == never, "late fault lost precise ordered head behavior");
    ++total.faults; b.report(false);
}

void arithmeticCases() {
    Bench b("arithmetic_x0_word");
    std::vector<Request> p{imm(1, 0, UINT64_C(0x8000000080000001)), imm(2, 0, 7), imm(0, 0, 99)};
    for (unsigned op = 0; op <= 9; ++op) { auto r = reg(3 + op, 1, 2); r.op = op; p.push_back(r); }
    for (unsigned op : {0u, 1u, 5u, 6u, 7u}) { auto r = reg(15 + op, 1, 2); r.op = op; r.word = true; p.push_back(r); }
    auto pc = imm(23, 0, 8); pc.usePc = true; p.push_back(pc);
    p.push_back(imm(24, 0, 11)); p.push_back(mul(25, 1, 2)); p.push_back(divu(26, 1, 2));
    b.submit(p); b.drain(); b.report();
}
void contention() {
    Bench b("L0_L1_C_F");setup(b);
    b.submit({load(4,10,0x20,"prime")});b.drain();
    const auto &prime=b.owner(b.roles.at("prime"));
    b.check(prime.complete!=never&&prime.memorySlot==0,"RR prime lacks actual accepted load completion");
    b.submit({load(5,10,0x40,"L0"),load(6,10,0x80,"L1")});
    for(unsigned n=0;n<120 && !(b.owner(b.roles.at("L0")).requested&&b.owner(b.roles.at("L1")).requested);++n)b.tick();
    b.check(b.owner(b.roles.at("L0")).requested&&b.owner(b.roles.at("L1")).requested,"both legal L0/L1 requests were not accepted");
    b.check(!b.owner(b.roles.at("L0")).responded&&!b.owner(b.roles.at("L1")).responded,"contention replies escaped event law");
    b.submit({reg(7,5,6,"C"),load(8,10,0xc1,"F")});
    bool seen=false;
    for(unsigned n=0;n<150&&!seen;++n){b.tick();seen=b.last.fault;}
    auto &l0=b.owner(b.roles.at("L0"));auto &l1=b.owner(b.roles.at("L1"));
    auto &c=b.owner(b.roles.at("C"));auto &f=b.owner(b.roles.at("F"));
    b.check(seen&&f.complete!=never&&c.retire!=never&&c.retire<b.cycle,"C did not retire before precise F head exception");
    b.check(l0.memorySlot==0&&l1.memorySlot==1&&f.memorySlot==2,"L0/L1/F did not occupy required actual slots0/1/2");
    b.check(l0.response==f.start&&l1.response==f.complete,"exact event-bound L0/F and L1/fault-drain coincidences were not reached");
    b.check(!f.requested&&l0.responded&&l1.responded,"F generated debt or L0/L1 reply conservation failed");
    b.check(b.firstUnselected&&b.twoHolderCycles,"real RR contention did not reach first unselected/two-successful-holder states");
    if(config.enabled)b.check(b.unselectedCaptures&&b.twoHolderCaptures&&b.actualHandoffs,"ON lacks real two-holder capture plus accepted PRF handoff");
    else b.check(!b.unselectedCaptures&&!b.twoHolderCaptures,"OFF unexpectedly captured an unselected source");
    std::cout<<"LOAD_READY_CONTENTION {\"enabled\":"<<config.enabled<<",\"L0_response\":"<<l0.response
        <<",\"F_start\":"<<f.start<<",\"F_complete\":"<<f.complete<<",\"L1_response\":"<<l1.response
        <<",\"C_capture\":"<<c.capture<<",\"C_retire\":"<<c.retire<<",\"L0_complete\":"<<l0.complete
        <<",\"L1_complete\":"<<l1.complete<<",\"first_unselected\":"<<b.firstUnselected<<"}\n";
    b.report(false);
}
void selectedAndIncoming() {
    {
        Bench b("selected_earliest_both_ignored_x0");setup(b);
        auto ignored=imm(8,5,19,"ignored_right");ignored.rs2=5;
        auto pc=reg(9,5,5,"ignored_left");pc.usePc=true;
        b.submit({load(5,10,0x500,"selected"),reg(6,5,5,"both"),ignored,pc,imm(0,5,1,"x0write")});b.drain();
        auto &l=b.owner(b.roles.at("selected"));auto &c=b.owner(b.roles.at("both"));
        b.check(c.capture==l.complete,"selected-load consumer lost original earliest accepted handoff edge");
        b.check(b.actualHandoffs&&b.heldLoadCaptures,"selected-load capture/handoff witness absent");b.report();
    }
    {
        Bench b("incoming_on_actual_load_drain");setup(b);
        b.submit({load(5,10,0x540,"incoming_producer")});
        for(unsigned n=0;n<120&&!b.owner(b.roles.at("incoming_producer")).responded;++n)b.tick();
        b.check(b.owner(b.roles.at("incoming_producer")).responded,"incoming case response was not owed/accepted");
        b.submit({reg(6,5,5,"incoming_consumer"),imm(7,6,1,"packet_raw")});b.drain();
        auto &l=b.owner(b.roles.at("incoming_producer"));auto &c=b.owner(b.roles.at("incoming_consumer"));
        b.check(c.allocate==l.complete&&b.incomingHandoffs,"accepted incoming row did not share actual producer drain edge");b.report();
    }
}
void isolationAndReplacement() {
    Bench b("raw_memory_M_store_and_slot_replacement");setup(b);
    b.submit({store(10,10,0x580,"seed_address")});b.drain();
    b.submit({load(5,10,0x580,"class_producer"),mul(6,5,26,"class_m"),
              store(10,5,0x600,"class_store"),load(7,5,0x5c0,"class_load"),
              reg(8,5,5,"ordinary"),load(11,10,0x640),load(12,10,0x680),load(13,10,0x6c0)});
    b.drain();b.check(b.nonordinaryChecks,"actual nonordinary pending source never overlapped successful holder");b.report();
}
void cancelledLoadReuse() {
    Bench b("cancelled_load_exact_reuse_before_reply");setup(b);
    b.submit({divu(24,25,26,"older_divider"),branch(24),load(5,10,0x700,"cancelled_load"),reg(6,5,5,"cancelled_dependent")});
    for(unsigned n=0;n<140&&!b.redirects;++n)b.tick();
    b.check(b.redirects==1,"older real branch recovery not reached");
    auto &old=b.owner(b.roles.at("cancelled_load"));
    b.check(old.requested&&old.killed&&!old.responded,"cancelled load lacks still-owed accepted read");
    std::vector<Request> reuse{divu(30,25,26,"reuse_blocker")};
    for(unsigned n=0;n<96;++n)reuse.push_back(imm(1+n%12,0,0x900+n,"reuse"));
    b.submit(reuse);b.drain();
    b.check(b.exactPrfBeforeReply.count(old.token)&&b.exactRobBeforeReply.count(old.token),"exact cancelled-load physical and full-tag ROB-index reuse before response not reached");
    b.check(old.responded&&old.complete==never&&old.retire==never,"old killed load revived after delayed reply");b.report();
}
} // namespace

int main(int argc,char **argv) {
    try {
        std::cout.setf(std::ios::unitbuf);
        std::string selected="all";
        for(int n=1;n<argc;++n) {
            std::string a=argv[n];
            if(a=="--enabled=0"||a=="--enabled=1"){config.enabled=a.back()=='1';config.specified=true;}
            else if(a=="--trace")config.trace=true;
            else if(a.rfind("--mutate=",0)==0)config.mutation=a.substr(9);
            else if(a.rfind("--case=",0)==0)selected=a.substr(7);
            else throw std::runtime_error("unknown argument "+a);
        }
        if(!config.specified)throw std::runtime_error("required emitted --enabled binding");
        const std::set<std::string> modes{"","wrong-fulltoken","wrong-captured-data","false-nonordinary","missing-prf-handoff","reserve-priority","killed-owner-revival","unselected-mispair"};
        if(!modes.count(config.mutation))throw std::runtime_error("unknown mutation");
        const std::set<std::string> cases{"all","contention","selected","isolation","recovery","mixed","throughput","faults"};
        if(!cases.count(selected))throw std::runtime_error("unknown fixed case");
        auto run=[&](const std::string &n){return selected=="all"||selected==n;};
        if(run("contention"))contention();
        if(run("selected"))selectedAndIncoming();
        if(run("isolation"))isolationAndReplacement();
        if(run("recovery"))cancelledLoadReuse();
        if(run("mixed")){mixed(1);crossLaneRefill();}
        if(run("throughput")){throughput(false);throughput(true);}
        if(run("faults"))faults();
        if(!config.mutation.empty()) {
            std::cerr<<"LOAD_READY_MUTATION_NOT_REACHED mutation="<<config.mutation<<" applied="<<config.applied<<'\n';return 3;
        }
        if(run("mixed")&&!total.mixedHeld0)throw std::runtime_error("fixed mixed case did not reach held-B1 plus load operands");
        std::cout<<"LOAD_READY_BACKEND_PASS {\"enabled\":"<<config.enabled<<",\"cases\":"<<total.cases
            <<",\"cycles\":"<<total.cycles<<",\"retired\":"<<total.retired<<",\"architectural_digest\":\""<<total.archHash
            <<"\",\"serial_capture_span\":"<<total.serialSpan<<",\"dual_capture_span\":"<<total.dualSpan
            <<",\"serial_II1_run\":"<<total.serialRun<<",\"dual_II1_run\":"<<total.dualRun<<"}\n";
        return 0;
    }catch(const std::exception &e){
        std::cerr<<"LOAD_READY_ORACLE_FAIL mutation="<<(config.mutation.empty()?"none":config.mutation)
            <<" applied="<<config.applied<<" "<<e.what()<<'\n';return 1;
    }
}
