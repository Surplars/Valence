package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.platform.CommonA1RebuildProfile

/** External raw lookup/PMP/owner boundary; expected authority is computed only by the C++ host. */
class ElasticLoadProofGsim extends Module {
    val p = CommonA1RebuildProfile.FullR1M3CheckedFlowStoreRowElasticProof.config.coreParams.copy(
        speculativeRamBase = BigInt("80000000", 16), speculativeRamBytes = 4194304)
    require(p.robEntries == 16 && p.tagBits == 64, "logical state counts are for the current 16/64 shape only")
    val io = IO(new Bundle {
        val current = Input(Valid(new VirtualRamLoadCandidate(p)))
        val lookahead = Input(Valid(new VirtualRamLoadCandidate(p)))
        val issued = Input(Valid(new RobToken(p)))
        val precheck = new VirtualLoadPrecheckPort
        val descriptorOwnerLive = Input(Bool())
        val translatedOwnerLive = Input(Bool())
        val preparedOwnerLive = Input(Bool())
        // Explicit scalar pins avoid depending on GSIM's Vec flattening API.
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
        val privilege = Input(UInt(2.W))
        val flush = Input(Bool())
        val descriptorOwner = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val translatedOwner = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val preparedOwner = Output(Valid(new ElasticVirtualRamLoadOwner(p)))
        val translatedPayload = Output(new VirtualRamLoadCertificate(p))
        val translatedNormal = Output(Bool())
        val preparedPayload = Output(new VirtualRamLoadCertificate(p))
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
        val descriptorPreempt = Output(Bool())
        val translatedPreempt = Output(Bool())
        val preparedPreempt = Output(Bool())
        val negativeExpire = Output(Bool())
        val descriptorBits = Output(UInt(10.W))
        val translatedBits = Output(UInt(10.W))
        val preparedBits = Output(UInt(10.W))
    })
    val dut = Module(new ElasticVirtualRamLoadPreparation(p))
    dut.io.current := io.current
    dut.io.lookahead := io.lookahead
    dut.io.issued := io.issued
    io.precheck <> dut.io.precheck
    dut.io.descriptorOwnerLive := io.descriptorOwnerLive
    dut.io.translatedOwnerLive := io.translatedOwnerLive
    dut.io.preparedOwnerLive := io.preparedOwnerLive
    dut.io.privilege := io.privilege
    dut.io.flush := io.flush
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    val cfg = Seq(io.cfg0, io.cfg1, io.cfg2, io.cfg3, io.cfg4, io.cfg5, io.cfg6, io.cfg7,
        io.cfg8, io.cfg9, io.cfg10, io.cfg11, io.cfg12, io.cfg13, io.cfg14, io.cfg15)
    val addr = Seq(io.addr0, io.addr1, io.addr2, io.addr3, io.addr4, io.addr5, io.addr6, io.addr7,
        io.addr8, io.addr9, io.addr10, io.addr11, io.addr12, io.addr13, io.addr14, io.addr15)
    for (i <- 0 until 16) { pmp.cfg(i) := cfg(i); pmp.addr(i) := addr(i) }
    PmpState.decodeRegions(pmp)
    dut.io.pmpState := pmp
    io.descriptorOwner := dut.io.descriptorOwner
    io.translatedOwner := dut.io.translatedOwner
    io.preparedOwner := dut.io.preparedOwner
    io.translatedPayload := BoringUtils.bore(dut.translated)
    io.translatedNormal := BoringUtils.bore(dut.normalMemory)
    io.preparedPayload := BoringUtils.bore(dut.prepared)
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
    io.descriptorPreempt := false.B // Contract constant, not an unbound literal bore target.
    io.translatedPreempt := BoringUtils.bore(dut.translatedPreempt)
    io.preparedPreempt := BoringUtils.bore(dut.preparedPreempt)
    io.negativeExpire := BoringUtils.bore(dut.negativeExpire)
    val descriptorBits = (new ElasticVirtualRamLoadOwner(p)).getWidth + 1
    val translatedBits = (new VirtualRamLoadCertificate(p)).getWidth + 2
    val preparedBits = (new VirtualRamLoadCertificate(p)).getWidth + 1
    require(descriptorBits == 167 && translatedBits == 233 && preparedBits == 232)
    io.descriptorBits := descriptorBits.U
    io.translatedBits := translatedBits.U
    io.preparedBits := preparedBits.U
}

object ElasticLoadProofGsimMain extends App {
    require(args.length == 1, "usage: ElasticLoadProofGsimMain output-directory")
    ChiselStage.emitCHIRRTLFile(new ElasticLoadProofGsim, Array("--target-dir", args.head))
}
