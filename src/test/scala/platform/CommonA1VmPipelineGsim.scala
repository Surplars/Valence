package soc.core.ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import java.nio.file.{Files, Paths}
import soc.bus.tilelink._
import soc.platform._

/** Actual production Common A1 tile; the host supplies raw instruction bytes,
  * native page-table service and legal L1D grants. No CPU resource is reduced.
  * MPRV ordinary stores exercise demand translation, not prechecked load bypass.
  * Only passive observation is added; no production counter or datapath edit.
  */
class CommonA1VmPipelineGsim(profile: String) extends Module {
    private val selected = CommonA1RebuildProfile.named(profile)
    private val config = selected.config
    private val p = config.coreParams
    private val boundary = CommonCpuTilePortParams()
    require(p.renameWidth == 2 && p.issueWidth == 2 && p.commitWidth == 2)
    require(p.robEntries == 16 && p.physicalRegs == 48 && p.tagBits == 64)
    require(p.machineSystem && p.fpEnabled && p.pmpEntries == 16 && p.virtualMemoryLevels == 3)
    require(config.instructionCacheLines == 512 && config.dataCacheLines == 512 && config.cacheWays == 2)
    require(config.ramBase == BigInt("80200000", 16) && CommonPlatformAbi.romBytes == 128 * 1024)
    val io = IO(new Bundle {
        val hold = Input(Bool())
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Valid(new HeadException(p)))
        val instructionA = Decoupled(new TLBundleA(boundary.instruction))
        val instructionD = Flipped(Decoupled(new TLBundleD(boundary.instruction)))
        val scalar0 = new CommonTileScalarPort(boundary)
        val scalar1 = new CommonTileScalarPort(boundary)
        val acceptedInstructions = Output(UInt(2.W))
        val virtualFetchFire = Output(Bool())
        val physicalFetchFire = Output(Bool())
        val fetchIdle = Output(Bool())
        val privateIdle = Output(Bool())
        val ownersIdle = Output(Bool())
        val memoryBusy = Output(Bool())
        val robOccupancy = Output(UInt(p.countBits.W))
        val unexpectedCoherent = Output(Bool())
        val dataA = Decoupled(new TLBundleA(boundary.coherent))
        val dataC = Decoupled(new TLBundleC(boundary.coherent))
        val dataE = Decoupled(new TLBundleE(boundary.coherent))
        val dataGrant = Flipped(Decoupled(new Bundle {
            val source = UInt(boundary.coherent.sourceBits.W)
            val sink = UInt(boundary.coherent.sinkBits.W)
            val cap = UInt(2.W)
            val denied = Bool(); val corrupt = Bool()
            val data0 = UInt(64.W)
            val data1 = UInt(64.W)
            val data2 = UInt(64.W)
            val data3 = UInt(64.W)
            val data4 = UInt(64.W)
            val data5 = UInt(64.W)
            val data6 = UInt(64.W)
            val data7 = UInt(64.W)
        }))
        val registeredTranslation = Output(Bool())
        val circularPayload = Output(Bool())
        val vm = Output(new VmCsrState)
        val fetchPrivilege = Output(UInt(2.W))
        val pmpConfig0 = Output(UInt(8.W)); val pmpAddress0 = Output(UInt(54.W))
        val dtlbHit = Output(Bool()); val dPteRead = Output(Bool())
        val upstream = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
        val upstreamOrigin = Output(Valid(new CanonicalStoreOrigin(p)))
        val translationRequest = Output(Valid(new SvTranslationRequest))
        val translationResponse = Output(Valid(new SvTranslationResponse))
        val translationWaiting = Output(Bool())
        val translationHitPass = Output(Bool())
        val translated = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
        val translatedOrigin = Output(Valid(new CanonicalStoreOrigin(p)))
        val checked = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
        val checkedOrigin = Output(Valid(new CanonicalStoreOrigin(p)))
        val checkedFault = Output(Bool()); val checkedPageFault = Output(Bool())
        val certificate = Output(Valid(new CanonicalStoreCertificate(p)))
        val physical = Output(Valid(new DataRequest(p.dataReturnHandleBits)))
        val physicalResponse = Output(Bool())
        val packetPresent = Output(UInt(2.W)); val packetConsume = Output(UInt(2.W))
        val packetExpectedNext = Output(Bool()); val packetFlush = Output(Bool())
        val acceptedPrefixEnabled = Output(Bool())
    })
    val tile = Module(new CommonA1CpuTile(config, boundary,
        selected.memoryProfile))
    tile.io.hold := io.hold
    tile.io.inspectRegister := io.inspectRegister
    io.committedValue := tile.io.committedValue
    io.commit0 := tile.io.commit(0)
    io.commit1 := tile.io.commit(1)
    io.trap := tile.io.trap
    io.memoryBusy := tile.io.memoryBusy
    io.instructionA <> tile.io.bus.instructionFetch.a
    tile.io.bus.instructionFetch.d <> io.instructionD
    TLBundle.tieoffSlaveCoherence(tile.io.bus.instructionFetch)
    assert(!tile.io.bus.instructionFetch.c.valid && !tile.io.bus.instructionFetch.e.valid,
        "instruction-only fixture received unexpected coherent I traffic")
    io.scalar0 <> tile.io.bus.scalar(0)
    io.scalar1 <> tile.io.bus.scalar(1)
    // Lane zero is the deliberately inactive coherent I-client. The actual
    // L1D on lane one is connected to a bounded legal external Home manager.
    val inactive = tile.io.bus.coherent(0)
    inactive.a.ready := false.B; inactive.b.valid := false.B
    inactive.b.bits := 0.U.asTypeOf(inactive.b.bits); inactive.c.ready := false.B
    inactive.d.valid := false.B; inactive.d.bits := 0.U.asTypeOf(inactive.d.bits)
    inactive.e.ready := false.B
    tile.io.bus.lineGrant(0).valid := false.B
    tile.io.bus.lineGrant(0).bits := 0.U.asTypeOf(tile.io.bus.lineGrant(0).bits)
    io.dataA <> tile.io.bus.coherent(1).a
    io.dataC <> tile.io.bus.coherent(1).c
    io.dataE <> tile.io.bus.coherent(1).e
    tile.io.bus.coherent(1).b.valid := false.B
    tile.io.bus.coherent(1).b.bits := 0.U.asTypeOf(tile.io.bus.coherent(1).b.bits)
    tile.io.bus.coherent(1).d.valid := false.B
    tile.io.bus.coherent(1).d.bits := 0.U.asTypeOf(tile.io.bus.coherent(1).d.bits)
    val grant = tile.io.bus.lineGrant(1)
    grant.valid := io.dataGrant.valid; io.dataGrant.ready := grant.ready
    grant.bits.source := io.dataGrant.bits.source; grant.bits.sink := io.dataGrant.bits.sink
    grant.bits.cap := io.dataGrant.bits.cap; grant.bits.denied := io.dataGrant.bits.denied
    grant.bits.corrupt := io.dataGrant.bits.corrupt
    grant.bits.data := Cat(io.dataGrant.bits.data7, io.dataGrant.bits.data6, io.dataGrant.bits.data5, io.dataGrant.bits.data4, io.dataGrant.bits.data3, io.dataGrant.bits.data2, io.dataGrant.bits.data1, io.dataGrant.bits.data0)
    io.unexpectedCoherent := tile.io.bus.coherent.map(port =>
        port.a.valid || port.c.valid || port.e.valid).reduce(_ || _)
    tile.io.bus.msi.request.valid := false.B
    tile.io.bus.msi.request.bits := 0.U.asTypeOf(tile.io.bus.msi.request.bits)
    tile.io.bus.msi.response.ready := true.B
    tile.io.bus.timerInterrupt := false.B
    tile.io.bus.softwareInterrupt := false.B
    tile.io.bus.timeSnapshot := 0.U
    tile.io.bus.maintenance.valid := false.B
    tile.io.bus.maintenance.bits := 0.U.asTypeOf(tile.io.bus.maintenance.bits)
    tile.io.bus.maintenanceStatus.ready := false.B
    tile.io.bus.fabricDrainedEpoch.valid := false.B
    tile.io.bus.fabricDrainedEpoch.bits := 0.U
    assert(!tile.io.bus.maintenanceStatus.valid, "bounded VM guests exclude FENCE.I/global fabric maintenance")
    // All taps are observations; none changes request, response or acceptance.
    io.acceptedInstructions := PopCount(BoringUtils.bore(tile.core.io.accepted))
    io.virtualFetchFire := BoringUtils.bore(tile.frontend.io.memory.request.valid) &&
        BoringUtils.bore(tile.frontend.io.memory.request.ready)
    io.physicalFetchFire := BoringUtils.bore(tile.fetchCache.io.fetch.request.valid) &&
        BoringUtils.bore(tile.fetchCache.io.fetch.request.ready)
    io.fetchIdle := BoringUtils.bore(tile.fetchIdle)
    io.privateIdle := BoringUtils.bore(tile.privateIdle) && BoringUtils.bore(tile.cache.io.quiescent)
    io.ownersIdle := BoringUtils.bore(tile.core.core.core.backend.io.ownersIdle)
    io.robOccupancy := BoringUtils.bore(tile.core.io.robOccupancy)
    // Passive test-only taps: no new production counters or control fanout.
    val adapter = tile.core.observationTranslation.get
    def observed[T <: Data](value: T): T = BoringUtils.bore(value)
    def fire(value: DecoupledIO[_]): Bool = observed(value.valid) && observed(value.ready)
    io.registeredTranslation := p.registeredDataTranslation.B
    io.circularPayload := p.circularFetchPayload.B
    io.vm := observed(adapter.io.vmState)
    io.fetchPrivilege := observed(tile.core.io.fetchPrivilege.get)
    io.pmpConfig0 := observed(adapter.io.pmpState.cfg(0))
    io.pmpAddress0 := observed(adapter.io.pmpState.addr(0))
    io.dtlbHit := tile.io.tlbHit(1); io.dPteRead := tile.io.pteRead(1)
    io.upstream.valid := fire(adapter.io.virtual.request)
    io.upstream.bits := observed(adapter.io.virtual.request.bits)
    io.upstreamOrigin := observed(adapter.io.canonicalStoreOrigin.get)
    io.translationRequest.valid := fire(adapter.io.translation.request)
    io.translationRequest.bits := observed(adapter.io.translation.request.bits)
    io.translationResponse.valid := fire(adapter.io.translation.response)
    io.translationResponse.bits := observed(adapter.io.translation.response.bits)
    io.translationWaiting := observed(adapter.waiting)
    io.translationHitPass := observed(adapter.translationHitPass)
    io.translated.valid := fire(adapter.translated.io.enq)
    io.translated.bits := observed(adapter.translated.io.enq.bits.request)
    io.translatedOrigin := observed(adapter.translated.io.enq.bits.canonicalStoreOrigin.get)
    io.checked.valid := fire(adapter.checked.get.enq)
    io.checked.bits := observed(adapter.checked.get.enq.bits.request)
    io.checkedOrigin := observed(adapter.head.canonicalStoreOrigin.get)
    io.checkedFault := observed(adapter.checked.get.enq.bits.fault)
    io.checkedPageFault := observed(adapter.checked.get.enq.bits.pageFault)
    io.certificate := observed(adapter.io.canonicalStoreCertificate.get)
    io.physical.valid := fire(adapter.io.physical.request)
    io.physical.bits := observed(adapter.io.physical.request.bits)
    io.physicalResponse := fire(adapter.io.physical.response)
    val packet = tile.core.core.core.fetchPacket.get
    require(packet.acceptedPrefixValidation == p.fetchAcceptedPrefixValidation,
        "CPU comparison must preserve actual profile accepted-prefix configuration")
    io.packetPresent := PopCount(VecInit(packet.io.instructions.map(v => observed(v.valid))))
    io.packetConsume := PopCount(observed(packet.io.consume))
    io.packetExpectedNext := observed(packet.io.expectedNext.valid)
    io.packetFlush := observed(packet.io.flush.valid)
    io.acceptedPrefixEnabled := packet.acceptedPrefixValidation.B

}

object CommonA1VmPipelineGsimMain extends App {
    require(args.length == 2, "output-directory full-candidate|full-m2|full-r1|full-m2-r1")
    require(Set("full-candidate", "full-m2", "full-r1", "full-m2-r1").contains(args(1)))
    val profile = CommonA1RebuildProfile.named(args(1)); val config = profile.config
    val out = Paths.get(args(0)); Files.createDirectories(out)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-config.json"), config)
    _root_.platform.CommonA1CpuRetirementFixture.writeFields(out.resolve("effective-parameters.json"), config.coreParams)
    Files.writeString(out.resolve("scope.txt"), "Actual CommonA1CpuTile; M-mode fetch and Sv39/MPRV S-mode ordinary store demand. No Board/CDC/PPA qualification.\n")
    ChiselStage.emitCHIRRTLFile(new CommonA1VmPipelineGsim(args(1)), Array("--target-dir", args(0)))
}
