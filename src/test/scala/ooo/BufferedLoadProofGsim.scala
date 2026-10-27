package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** Scalar external authority fixture. The host alone supplies tickets, translation and raw PMP. */
class BufferedLoadProofGsim(sourceLocalCancellation: Boolean = false,
    sharedPmpBounds: Boolean = false, decodedPmp: Boolean = false) extends Module {
    val p = CommonA1RebuildProfile.FullR1M3BufferedThirdRankProof.config.coreParams.copy(
        speculativeRamBase = BigInt("80000000", 16), speculativeRamBytes = 4194304,
        sourceLocalLoadProofCancellation = sourceLocalCancellation,
        sharedLoadProofPmpBounds = sharedPmpBounds, decodedNaturalPmp = decodedPmp)
    require(p.robEntries == 16 && p.tagBits == 64)
    val io = IO(new Bundle {
        val current = Input(Valid(new VirtualRamLoadCandidate(p)))
        val lookahead0 = Input(Valid(new VirtualRamLoadCandidate(p)))
        val lookahead1 = Input(Valid(new VirtualRamLoadCandidate(p)))
        val issued = Input(Valid(new RobToken(p)))
        val precheck = new VirtualLoadPrecheckPort
        val descriptorLive0 = Input(Bool()); val descriptorLive1 = Input(Bool())
        val translatedLive = Input(Bool())
        val preparedLive0 = Input(Bool()); val preparedLive1 = Input(Bool())
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
        val privilege = Input(UInt(2.W)); val flush = Input(Bool())
        val descriptor0 = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val descriptor1 = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val translatedOwner = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val prepared0 = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val prepared1 = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val translatedPayload = Output(new VirtualRamLoadCertificate(p))
        val translatedNormal = Output(Bool())
        val preparedPayload0 = Output(new VirtualRamLoadCertificate(p))
        val preparedPayload1 = Output(new VirtualRamLoadCertificate(p))
        val prepared = Output(Valid(new VirtualRamLoadCertificate(p)))
        val hit = Output(Bool())
        val resultSpace = Output(Bool())
        val translatedAdvance = Output(Bool())
        val translatedSpace = Output(Bool())
        val queryOffer = Output(Bool())
        val queryAccept = Output(Bool())
        val queryFromDescriptor = Output(Bool())
        val descriptorTransfer = Output(Bool())
        val descriptorCapture = Output(Bool())
        val preparedPreempt = Output(Bool())
        val negativeExpire = Output(Bool())
        val queryDescriptorIndex = Output(UInt(1.W))
        val selectedPreparedIndex = Output(UInt(1.W))
        val descriptorCaptureIndex = Output(UInt(1.W))
        val captureLookaheadIndex = Output(UInt(1.W))
        val preparedInsertIndex = Output(UInt(1.W))
        val preparedVictimIndex = Output(UInt(1.W))
        // Independent, test-only PRF/ready phase fixture. None of these pins drive the proof module.
        val phaseWrite0 = Input(Valid(new Bundle { val address = UInt(6.W); val data = UInt(64.W) }))
        val phaseWrite1 = Input(Valid(new Bundle { val address = UInt(6.W); val data = UInt(64.W) }))
        val phaseWake0 = Input(Valid(UInt(6.W))); val phaseWake1 = Input(Valid(UInt(6.W)))
        val phaseWake2 = Input(Valid(UInt(6.W)))
        val phaseReserve0 = Input(Valid(UInt(6.W))); val phaseReserve1 = Input(Valid(UInt(6.W)))
        val phaseAddress = Input(UInt(6.W))
        val phaseData = Output(UInt(64.W)); val phaseReady = Output(UInt(48.W))
    })
    val dut = Module(new BufferedVirtualRamLoadPreparation(p))
    dut.io.current := io.current
    dut.io.lookahead(0) := io.lookahead0
    dut.io.lookahead(1) := io.lookahead1
    dut.io.issued := io.issued
    io.precheck <> dut.io.precheck
    dut.io.descriptorOwnerLive(0) := io.descriptorLive0
    dut.io.descriptorOwnerLive(1) := io.descriptorLive1
    dut.io.translatedOwnerLive := io.translatedLive
    dut.io.preparedOwnerLive(0) := io.preparedLive0
    dut.io.preparedOwnerLive(1) := io.preparedLive1
    dut.io.privilege := io.privilege
    dut.io.flush := io.flush
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    val cfg = Seq(io.cfg0, io.cfg1, io.cfg2, io.cfg3, io.cfg4, io.cfg5, io.cfg6, io.cfg7, io.cfg8, io.cfg9, io.cfg10, io.cfg11, io.cfg12, io.cfg13, io.cfg14, io.cfg15)
    val addr = Seq(io.addr0, io.addr1, io.addr2, io.addr3, io.addr4, io.addr5, io.addr6, io.addr7, io.addr8, io.addr9, io.addr10, io.addr11, io.addr12, io.addr13, io.addr14, io.addr15)
    for (i <- 0 until 16) { pmp.cfg(i) := cfg(i); pmp.addr(i) := addr(i) }
    PmpState.decodeRegions(pmp)
    dut.io.pmpState := pmp
    io.descriptor0 := dut.io.descriptorOwner(0)
    io.descriptor1 := dut.io.descriptorOwner(1)
    io.translatedOwner := dut.io.translatedOwner
    io.prepared0 := dut.io.preparedOwner(0)
    io.prepared1 := dut.io.preparedOwner(1)
    io.translatedPayload := BoringUtils.bore(dut.translated)
    io.translatedNormal := BoringUtils.bore(dut.normalMemory)
    io.preparedPayload0 := BoringUtils.bore(dut.prepared(0))
    io.preparedPayload1 := BoringUtils.bore(dut.prepared(1))
    io.prepared := dut.io.prepared
    io.hit := dut.io.hit
    io.resultSpace := BoringUtils.bore(dut.resultSpace)
    io.translatedAdvance := BoringUtils.bore(dut.translatedAdvance)
    io.translatedSpace := BoringUtils.bore(dut.translatedSpace)
    io.queryOffer := BoringUtils.bore(dut.queryOffer)
    io.queryAccept := BoringUtils.bore(dut.queryAccept)
    io.queryFromDescriptor := BoringUtils.bore(dut.queryFromDescriptor)
    io.descriptorTransfer := BoringUtils.bore(dut.descriptorTransfer)
    io.descriptorCapture := BoringUtils.bore(dut.descriptorCapture)
    io.preparedPreempt := BoringUtils.bore(dut.preparedPreempt)
    io.negativeExpire := BoringUtils.bore(dut.negativeExpire)
    io.queryDescriptorIndex := BoringUtils.bore(dut.queryDescriptorIndex)
    io.selectedPreparedIndex := BoringUtils.bore(dut.selectedPreparedIndex)
    io.descriptorCaptureIndex := BoringUtils.bore(dut.descriptorCaptureIndex)
    io.captureLookaheadIndex := BoringUtils.bore(dut.captureLookaheadIndex)
    io.preparedInsertIndex := BoringUtils.bore(dut.preparedInsertIndex)
    io.preparedVictimIndex := BoringUtils.bore(dut.preparedVictimIndex)
    val phasePrf = Module(new OwnerBankedPhysicalRegisterFile(48, 1, 2))
    phasePrf.io.write(0) := io.phaseWrite0
    phasePrf.io.write(1) := io.phaseWrite1
    phasePrf.io.address(0) := io.phaseAddress
    io.phaseData := phasePrf.io.data(0)
    val phaseReady = RegInit(VecInit((0 until 48).map(i => (i < 32).B)))
    val phaseUpdate = Module(new PhysicalReadyUpdate(48, 3, 2))
    phaseUpdate.io.current := phaseReady.asUInt
    phaseUpdate.io.wake(0) := io.phaseWake0
    phaseUpdate.io.wake(1) := io.phaseWake1
    phaseUpdate.io.wake(2) := io.phaseWake2
    phaseUpdate.io.reserve(0) := io.phaseReserve0
    phaseUpdate.io.reserve(1) := io.phaseReserve1
    for (r <- 0 until 48) { phaseReady(r) := phaseUpdate.io.next(r) }
    io.phaseReady := phaseReady.asUInt
}

object BufferedLoadProofGsimMain extends App {
    require(args.length == 1, "usage: BufferedLoadProofGsimMain output-directory")
    ChiselStage.emitCHIRRTLFile(new BufferedLoadProofGsim, Array("--target-dir", args.head))
}

/** Same independent oracle interface; only the selected cancellation implementation differs. */
object SourceLocalBufferedLoadProofGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new BufferedLoadProofGsim(sourceLocalCancellation = true, sharedPmpBounds = true),
        Array("--target-dir", args.head))
}
