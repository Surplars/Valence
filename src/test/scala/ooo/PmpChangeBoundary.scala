package ooo

import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** Test-only paired authorization boundary. Both sides receive the production
  * CSR unit's exact public raw/decoded state and common external handshakes.
  * No CSR internals or replacement state machine decide the positive oracle.
  */
class PmpChangeBoundaryPort extends Bundle {
    val request = Input(Valid(new DataRequest))
    val physicalReady = Input(Bool())
    val response = Input(Valid(new DataResponse))
    val responseReady = Input(Bool())
    val aggregateDrained = Input(Bool())
    val flush = Input(Bool())
    val query = Input(Valid(new VirtualLoadPrecheckRequest))
    val queryReply = Input(Valid(new SvTranslationResponse))
    val mutation = Input(UInt(3.W))
    val poisonInvalid = Input(Bool())
    val rawChanged = Output(Bool())
    val changed = Output(Bool())
    val oldChanged = Output(Bool())
    val epoch = Output(UInt(32.W))
    val postedEpoch = Output(UInt(32.W))
    val stable = Output(Bool())
    val idle = Output(Bool())
    val requestReady = Output(Bool())
    val physical = Output(Valid(new DataRequest))
    val physicalResponseReady = Output(Bool())
    val upstreamResponse = Output(Valid(new DataResponse))
    val queryValid = Output(Bool())
    val queryEpoch = Output(UInt(32.W))
    val mismatch = Output(Bool())
}

class PmpChangeBoundary(p: OooParams) extends Module {
    val io = IO(new Bundle {
        val test = new PmpChangeBoundaryPort
        val pmp = Input(new PmpState)
        val vm = Input(new VmCsrState)
        val rawChanged = Input(Bool())
        // Deliberately wrong candidate event sources, enabled only by the driver.
        val early = Input(Bool())
        val permission = Input(Bool())
        val writeEnable = Input(Bool())
    })
    val reference = Module(new DataTranslationAdapter(p, registerCheckedRequests = true))
    val fresh = Module(new DataTranslationAdapter(p, registerCheckedRequests = true, usePublishedPmpChanges = true))
    val delayed = RegNext(io.rawChanged, false.B)
    val held = RegInit(false.B)
    when(io.test.physicalReady) { held := io.rawChanged }
    fresh.io.pmpRawChanged.get := MuxLookup(io.test.mutation, io.rawChanged)(Seq(
        1.U -> io.early, 2.U -> delayed, 3.U -> io.permission, 4.U -> io.writeEnable, 5.U -> Mux(io.test.physicalReady, io.rawChanged, held)))
    for (adapter <- Seq(reference, fresh)) {
        adapter.io.vmState := io.vm
        adapter.io.pmpState := io.pmp
        adapter.io.virtual.request.valid := io.test.request.valid
        adapter.io.virtual.request.bits := (if (adapter eq fresh)
            Mux(io.test.poisonInvalid && !io.test.request.valid,
                (~io.test.request.bits.asUInt).asTypeOf(new DataRequest), io.test.request.bits)
            else io.test.request.bits)
        adapter.io.virtual.response.ready := io.test.responseReady
        adapter.io.physical.request.ready := io.test.physicalReady
        adapter.io.physical.response.valid := io.test.response.valid
        adapter.io.physical.response.bits := io.test.response.bits
        adapter.io.translation.request.ready := true.B
        adapter.io.translation.response.valid := false.B
        adapter.io.translation.response.bits := 0.U.asTypeOf(adapter.io.translation.response.bits)
        adapter.io.posted.foreach { port =>
            port.upstreamProof := 0.U.asTypeOf(port.upstreamProof)
            port.externalBusy := false.B
            port.aggregateDrained := io.test.aggregateDrained
        }
        adapter.io.loadPrecheck.foreach(_.request := io.test.query)
        adapter.io.translationPeek.foreach(_.response := io.test.queryReply)
        adapter.io.precheckFlush.foreach(_ := io.test.flush)
    }
    val oldChanged = BoringUtils.bore(reference.authorizationChanged)
    val newChanged = BoringUtils.bore(fresh.authorizationChanged)
    def validMismatch[T <: Data](a: ValidIO[T], b: ValidIO[T]): Bool =
        a.valid =/= b.valid || (a.valid && a.bits.asUInt =/= b.bits.asUInt)
    def decoupledMismatch[T <: Data](a: DecoupledIO[T], b: DecoupledIO[T]): Bool =
        a.valid =/= b.valid || (a.valid && a.bits.asUInt =/= b.bits.asUInt)
    val mismatches = Seq(
        oldChanged =/= newChanged,
        reference.io.virtual.request.ready =/= fresh.io.virtual.request.ready,
        decoupledMismatch(reference.io.virtual.response, fresh.io.virtual.response),
        decoupledMismatch(reference.io.physical.request, fresh.io.physical.request),
        reference.io.physical.response.ready =/= fresh.io.physical.response.ready,
        decoupledMismatch(reference.io.translation.request, fresh.io.translation.request),
        reference.io.translation.response.ready =/= fresh.io.translation.response.ready,
        reference.io.idle =/= fresh.io.idle,
        reference.io.pageFault =/= fresh.io.pageFault) ++
        reference.io.posted.toSeq.zip(fresh.io.posted.toSeq).map { case (a, b) =>
            a.contextEpoch =/= b.contextEpoch || a.contextChanging =/= b.contextChanging ||
                validMismatch(a.requestProof, b.requestProof)
        } ++
        reference.io.loadPrecheck.toSeq.zip(fresh.io.loadPrecheck.toSeq).map { case (a, b) =>
            a.epoch =/= b.epoch || a.stable =/= b.stable || validMismatch(a.response, b.response)
        } ++
        reference.io.translationPeek.toSeq.zip(fresh.io.translationPeek.toSeq).map { case (a, b) =>
            validMismatch(a.request, b.request)
        }
    io.test.mismatch := VecInit(mismatches).asUInt.orR
    io.test.rawChanged := io.rawChanged
    io.test.changed := newChanged
    io.test.oldChanged := oldChanged
    io.test.epoch := fresh.io.loadPrecheck.map(_.epoch).getOrElse(0.U)
    io.test.postedEpoch := fresh.io.posted.map(_.contextEpoch).getOrElse(0.U)
    io.test.stable := fresh.io.loadPrecheck.map(_.stable).getOrElse(false.B)
    io.test.idle := fresh.io.idle
    io.test.requestReady := fresh.io.virtual.request.ready
    io.test.physical.valid := fresh.io.physical.request.valid
    io.test.physical.bits := fresh.io.physical.request.bits
    io.test.physicalResponseReady := fresh.io.physical.response.ready
    io.test.upstreamResponse.valid := fresh.io.virtual.response.valid
    io.test.upstreamResponse.bits := fresh.io.virtual.response.bits
    io.test.queryValid := fresh.io.loadPrecheck.map(_.response.valid).getOrElse(false.B)
    io.test.queryEpoch := fresh.io.loadPrecheck.map(_.response.bits.epoch).getOrElse(0.U)
}

/** Abstract same-clock publication contract under consecutive atomic image
  * changes. The real one-command CSR producer cannot execute on adjacent edges;
  * this stresses the consumer contract without claiming impossible CSR duty.
  */
class PmpChangeWaveformGsim extends Module {
    val p = OooParams(machineSystem = true, pmpEntries = 16, virtualMemoryLevels = 3,
        publishedPmpChanges = true, virtualRamLoadPrecheck = true, postedStoreMerge = true,
        bufferedRamStores = true, registeredMemoryAddress = true, memoryEntries = 2,
        speculativeRamBase = BigInt("80000000", 16), speculativeRamBytes = 65536)
    val io = IO(new Bundle {
        val update = Input(Bool())
        val cfg = Input(UInt(8.W))
        val addr = Input(UInt(54.W))
        val test = new PmpChangeBoundaryPort
    })
    val cfg = RegInit(0.U(8.W))
    val addr = RegInit(0.U(54.W))
    when(io.update) { cfg := io.cfg; addr := io.addr }
    val change = io.update && (cfg =/= io.cfg || addr =/= io.addr)
    val pair = Module(new PmpChangeBoundary(p))
    pair.io.test <> io.test
    pair.io.pmp := 0.U.asTypeOf(new PmpState)
    pair.io.pmp.cfg(0) := cfg
    pair.io.pmp.addr(0) := addr
    PmpState.decodeRegions(pair.io.pmp)
    pair.io.vm := 0.U.asTypeOf(new VmCsrState)
    pair.io.vm.dataPrivilege := 3.U
    pair.io.rawChanged := RegNext(change, false.B)
    pair.io.early := change
    pair.io.permission := RegNext(io.update && (cfg =/= io.cfg ||
        (addr =/= io.addr && cfg(4, 3) =/= 0.U)), false.B)
    pair.io.writeEnable := RegNext(io.update, false.B)
}

object PmpChangeWaveformGsimMain extends App {
    _root_.circt.stage.ChiselStage.emitCHIRRTLFile(new PmpChangeWaveformGsim, Array("--target-dir", args.head))
}
