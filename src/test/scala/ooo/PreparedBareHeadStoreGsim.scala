package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import soc.core.ooo._

/** Production numerical row + Bare issue-source policy + unchanged generic PMP.
  * The final mock admission gate is a fixture-only contract witness, not an LSU,
  * ROB, backend or permission-to-memory integration test. Scalar ports retain the
  * pinned GSIM host ABI; full owner and head identities are independent inputs.
  */
class PreparedBareHeadStoreGsim extends Module {
    private val p = OooParams(robEntries = 16, physicalRegs = 48, tagBits = 64,
        speculativeRamBase = BigInt("80200000", 16), speculativeRamBytes = BigInt(1) << 31)
    val io = IO(new Bundle {
        val candidateValid = Input(Bool())
        val candidateIndex = Input(UInt(4.W)); val candidateTag = Input(UInt(64.W))
        val candidateAddress = Input(UInt(64.W)); val candidateData = Input(UInt(64.W))
        val candidateSize = Input(UInt(2.W))
        val currentValid = Input(Bool())
        val currentIndex = Input(UInt(4.W)); val currentTag = Input(UInt(64.W))
        val headValid = Input(Bool()); val headDone = Input(Bool())
        val headIndex = Input(UInt(4.W)); val headTag = Input(UInt(64.W))
        val memory = Input(Bool()); val store = Input(Bool()); val atomic = Input(Bool())
        val system = Input(Bool()); val mulDiv = Input(Bool())
        val fetchFault = Input(Bool()); val fetchPageFault = Input(Bool())
        val controlFlow = Input(Bool()); val integerAdd = Input(Bool())
        val virtualized = Input(Bool())
        val normalAddress = Input(UInt(64.W)); val normalSize = Input(UInt(2.W))
        val normalAccess = Input(UInt(2.W)); val privilege = Input(UInt(2.W))
        val flush = Input(Bool()); val kill = Input(Bool())
        val consumeValid = Input(Bool())
        val consumeIndex = Input(UInt(4.W)); val consumeTag = Input(UInt(64.W))
        val sourceReady1 = Input(Bool()); val sourceReady2 = Input(Bool())
        val strictSerialCredit = Input(Bool()); val commitEnable = Input(Bool())
        val barrier = Input(Bool()); val pendingException = Input(Bool())
        val cfg0 = Input(UInt(8.W)); val addr0 = Input(UInt(54.W))
        val cfg1 = Input(UInt(8.W)); val addr1 = Input(UInt(54.W))
        val cfg2 = Input(UInt(8.W)); val addr2 = Input(UInt(54.W))
        val cfg3 = Input(UInt(8.W)); val addr3 = Input(UInt(54.W))
        val cfg4 = Input(UInt(8.W)); val addr4 = Input(UInt(54.W))
        val cfg5 = Input(UInt(8.W)); val addr5 = Input(UInt(54.W))
        val cfg6 = Input(UInt(8.W)); val addr6 = Input(UInt(54.W))
        val cfg7 = Input(UInt(8.W)); val addr7 = Input(UInt(54.W))
        val cfg8 = Input(UInt(8.W)); val addr8 = Input(UInt(54.W))
        val cfg9 = Input(UInt(8.W)); val addr9 = Input(UInt(54.W))
        val cfg10 = Input(UInt(8.W)); val addr10 = Input(UInt(54.W))
        val cfg11 = Input(UInt(8.W)); val addr11 = Input(UInt(54.W))
        val cfg12 = Input(UInt(8.W)); val addr12 = Input(UInt(54.W))
        val cfg13 = Input(UInt(8.W)); val addr13 = Input(UInt(54.W))
        val cfg14 = Input(UInt(8.W)); val addr14 = Input(UInt(54.W))
        val cfg15 = Input(UInt(8.W)); val addr15 = Input(UInt(54.W))
        val rowValid = Output(Bool())
        val rowIndex = Output(UInt(4.W)); val rowTag = Output(UInt(64.W))
        val rowAddress = Output(UInt(64.W)); val rowData = Output(UInt(64.W))
        val rowSize = Output(UInt(2.W))
        val ownerLive = Output(Bool()); val atHead = Output(Bool())
        val choice = Output(Bool())
        val queryAddress = Output(UInt(64.W)); val querySize = Output(UInt(2.W))
        val queryAccess = Output(UInt(2.W)); val denied = Output(Bool())
        val fixtureAdmission = Output(Bool())
    })
    val row = Module(new PreparedHeadStoreOperands(p))
    row.io.candidate.valid := io.candidateValid
    row.io.candidate.bits.token.index := io.candidateIndex
    row.io.candidate.bits.token.tag := io.candidateTag
    row.io.candidate.bits.address := io.candidateAddress
    row.io.candidate.bits.data := io.candidateData
    row.io.candidate.bits.size := io.candidateSize
    val held = row.io.prepared
    val ownerLive = held.valid && io.currentValid &&
        held.bits.token.index === io.currentIndex && held.bits.token.tag === io.currentTag
    val atHead = io.headValid && held.bits.token.index === io.headIndex && held.bits.token.tag === io.headTag
    row.io.ownerLive := ownerLive
    row.io.atHead := atHead
    row.io.flush := io.flush || io.kill
    row.io.consume.valid := io.consumeValid
    row.io.consume.bits.index := io.consumeIndex
    row.io.consume.bits.tag := io.consumeTag
    val ordinary = io.memory && io.store && !io.atomic && !io.system && !io.mulDiv &&
        !io.fetchFault && !io.fetchPageFault && !io.controlFlow && io.integerAdd
    val choice = PreparedBareHeadStorePolicy.eligible(p, held.valid, ownerLive, atHead,
        io.headDone, ordinary, io.virtualized, held.bits.address, held.bits.size)
    val (address, size, access) = PreparedBareHeadStorePolicy.pmpQuery(choice,
        held.bits.address, held.bits.size, io.normalAddress, io.normalSize, io.normalAccess)
    val state = WireDefault(0.U.asTypeOf(new PmpState))
    state.cfg(0) := io.cfg0; state.addr(0) := io.addr0
    state.cfg(1) := io.cfg1; state.addr(1) := io.addr1
    state.cfg(2) := io.cfg2; state.addr(2) := io.addr2
    state.cfg(3) := io.cfg3; state.addr(3) := io.addr3
    state.cfg(4) := io.cfg4; state.addr(4) := io.addr4
    state.cfg(5) := io.cfg5; state.addr(5) := io.addr5
    state.cfg(6) := io.cfg6; state.addr(6) := io.addr6
    state.cfg(7) := io.cfg7; state.addr(7) := io.addr7
    state.cfg(8) := io.cfg8; state.addr(8) := io.addr8
    state.cfg(9) := io.cfg9; state.addr(9) := io.addr9
    state.cfg(10) := io.cfg10; state.addr(10) := io.addr10
    state.cfg(11) := io.cfg11; state.addr(11) := io.addr11
    state.cfg(12) := io.cfg12; state.addr(12) := io.addr12
    state.cfg(13) := io.cfg13; state.addr(13) := io.addr13
    state.cfg(14) := io.cfg14; state.addr(14) := io.addr14
    state.cfg(15) := io.cfg15; state.addr(15) := io.addr15
    PmpState.decodeRegions(state)
    val checker = Module(new PmpChecker())
    checker.io.state := state
    checker.io.address := address
    checker.io.size := size
    checker.io.access := access
    checker.io.privilege := io.privilege
    io.rowValid := held.valid
    io.rowIndex := held.bits.token.index
    io.rowTag := held.bits.token.tag
    io.rowAddress := held.bits.address
    io.rowData := held.bits.data
    io.rowSize := held.bits.size
    io.ownerLive := ownerLive
    io.atHead := atHead
    io.choice := choice
    io.queryAddress := address
    io.querySize := size
    io.queryAccess := access
    io.denied := checker.io.denied
    // Intentional: a denied selected head may enter the ordinary LSU fault path;
    // denial is not source-selection feedback and never means a physical write.
    io.fixtureAdmission := choice && io.sourceReady1 && io.sourceReady2 &&
        io.strictSerialCredit && io.commitEnable && !io.barrier &&
        !io.pendingException && !io.flush && !io.kill
}

object PreparedBareHeadStoreGsimMain extends App {
    require(args.length == 1)
    ChiselStage.emitCHIRRTLFile(new PreparedBareHeadStoreGsim, Array("--target-dir", args.head))
}
