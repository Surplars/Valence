package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Adapter-only off/on fixture. The upstream port represents an already registered LSU request.
  * Its ordinary physical requests have already passed the core's current-access PMP check.
  * The external translation responder is a test model, not an SvTranslationService/page walker.
  * Debug outputs expose actual queue events, never oracle mappings or permission decisions.
  */
class PhysicalIngressFlowGsim(enabled: Boolean) extends Module {
    val p = BoardSocConfig.timingParams("staged-fetch-feedback").copy(
        machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3,
        identityDataRequestFlow = true, physicalLoadIngressFlow = enabled, dataNextLinePrefetch = true,
        speculativeRamBase = BigInt("80200000", 16), speculativeRamBytes = BigInt("80000000", 16))
    val io = IO(new Bundle {
        val upstream = Flipped(new DataPort)
        val physical = new DataPort
        val translation = new SvTranslationPort
        val context = Input(new VmCsrState)
        val idle = Output(Bool())
        val shortcut = Output(Bool())
        val ingressPush = Output(Bool())
        val ingressPop = Output(Bool())
        val ingressCount = Output(UInt(2.W))
        val checkedPush = Output(Bool())
        val checkedPop = Output(Bool())
        val checkedCount = Output(UInt(2.W))
        val translatedValid = Output(Bool())
        val waiting = Output(Bool())
    })
    // Keep these names compatible with the untouched 192-check translation_context.cpp oracle.
    val pmpCfg0 = IO(Input(UInt(8.W)))
    val pmpAddr0 = IO(Input(UInt(54.W)))
    val immediateTranslation = IO(Input(Bool()))
    val adapter = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    adapter.io.virtual <> io.upstream
    io.physical <> adapter.io.physical
    io.translation.request <> adapter.io.translation.request
    adapter.io.translation.response.valid := Mux(immediateTranslation,
        adapter.io.translation.request.fire, io.translation.response.valid)
    adapter.io.translation.response.bits := io.translation.response.bits
    io.translation.response.ready := adapter.io.translation.response.ready
    adapter.io.vmState := io.context
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := pmpCfg0
    pmp.addr(0) := pmpAddr0
    PmpState.decodeRegions(pmp)
    adapter.io.pmpState := pmp
    io.idle := adapter.io.idle
    io.shortcut := BoringUtils.bore(adapter.physicalIngressPass)
    io.ingressPush := BoringUtils.bore(adapter.virtualRequests.get.io.enq.valid) &&
        BoringUtils.bore(adapter.virtualRequests.get.io.enq.ready)
    io.ingressPop := BoringUtils.bore(adapter.virtualRequests.get.io.deq.valid) &&
        BoringUtils.bore(adapter.virtualRequests.get.io.deq.ready)
    io.ingressCount := BoringUtils.bore(adapter.virtualRequests.get.io.count)
    io.checkedPush := BoringUtils.bore(adapter.checked.get.enq.valid) &&
        BoringUtils.bore(adapter.checked.get.enq.ready)
    io.checkedPop := BoringUtils.bore(adapter.checked.get.deq.valid) &&
        BoringUtils.bore(adapter.checked.get.deq.ready)
    io.checkedCount := BoringUtils.bore(adapter.checked.get.count)
    io.translatedValid := BoringUtils.bore(adapter.translated.io.deq.valid)
    io.waiting := BoringUtils.bore(adapter.waiting)
}

object PhysicalIngressFlowGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PhysicalIngressFlowGsim(args.lift(1).contains("1")),
        Array("--target-dir", args.head))
}
