package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Standalone instruction owner boundary; translation and physical-memory
  * responses come from the independent software fixture, not a DUT TLB.
  */
class InstructionPermissionGsim(words: Int, retimed: Boolean, aligned: Boolean) extends Module {
    require(Set(2, 4).contains(words))
    val io = IO(new Bundle {
        val virtualValid = Input(Bool())
        val virtualPc = Input(UInt(64.W))
        val virtualMask = Input(UInt(4.W))
        val virtualReady = Output(Bool())
        val virtualResponseReady = Input(Bool())
        val virtualResponseValid = Output(Bool())
        val virtualResponseLow = Output(UInt(64.W))
        val virtualResponseHigh = Output(UInt(64.W))
        val virtualErrors = Output(UInt(4.W))
        val virtualPages = Output(UInt(4.W))
        val satp = Input(UInt(64.W))
        val sum = Input(Bool())
        val mxr = Input(Bool())
        val privilege = Input(UInt(2.W))
        val cfg0 = Input(UInt(8.W))
        val cfg1 = Input(UInt(8.W))
        val addr0 = Input(UInt(54.W))
        val addr1 = Input(UInt(54.W))
        val translationReady = Input(Bool())
        val translationValid = Output(Bool())
        val translationPc = Output(UInt(64.W))
        val translationRoot = Output(UInt(44.W))
        val translationAsid = Output(UInt(16.W))
        val translationMode = Output(UInt(4.W))
        val translationPrivilege = Output(UInt(2.W))
        val translationAccess = Output(UInt(2.W))
        val translationSum = Output(Bool())
        val translationMxr = Output(Bool())
        val translationResponseValid = Input(Bool())
        val translationPhysical = Input(UInt(64.W))
        val translationPage = Input(Bool())
        val translationError = Input(Bool())
        val translationResponseReady = Output(Bool())
        val physicalReady = Input(Bool())
        val physicalValid = Output(Bool())
        val physicalPc = Output(UInt(64.W))
        val physicalMask = Output(UInt(4.W))
        val physicalResponseValid = Input(Bool())
        val physicalResponseLow = Input(UInt(64.W))
        val physicalResponseHigh = Input(UInt(64.W))
        val physicalErrors = Input(UInt(4.W))
        val physicalPages = Input(UInt(4.W))
        val physicalResponseReady = Output(Bool())
        val idle = Output(Bool())
    })
    val p = OooParams(renameWidth = words, commitWidth = words, completionWidth = words,
        compressedInstructions = words == 4 || aligned, machineSystem = true,
        pmpEntries = 16, virtualMemoryLevels = 4, alignedFetchPmp = aligned,
        bufferedFetchRequests = retimed, flowThroughFetchRequests = retimed,
        independentFetchCapture = retimed, parallelHomeQualification = retimed,
        registeredFabricBoundary = retimed, registeredTranslatedResponses = retimed,
        registeredTranslationHeads = retimed)
    val adapter = Module(new InstructionTranslationAdapter(p))
    adapter.io.virtual.request.valid := io.virtualValid
    adapter.io.virtual.request.bits := io.virtualPc
    adapter.io.virtual.requestMask := io.virtualMask(words - 1, 0)
    io.virtualReady := adapter.io.virtual.request.ready
    adapter.io.virtual.response.ready := io.virtualResponseReady
    io.virtualResponseValid := adapter.io.virtual.response.valid
    io.virtualResponseLow := adapter.io.virtual.response.bits(63, 0)
    io.virtualResponseHigh := (if (words == 4) adapter.io.virtual.response.bits(127, 64) else 0.U)
    io.virtualErrors := adapter.io.virtual.responseError
    io.virtualPages := adapter.io.virtual.responsePageFault
    adapter.io.vmState := 0.U.asTypeOf(new VmCsrState)
    adapter.io.vmState.satp := io.satp
    adapter.io.vmState.sum := io.sum
    adapter.io.vmState.mxr := io.mxr
    adapter.io.privilege := io.privilege
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := io.cfg0
    pmp.cfg(1) := io.cfg1
    pmp.addr(0) := io.addr0
    pmp.addr(1) := io.addr1
    PmpState.decodeRegions(pmp)
    adapter.io.pmpState := pmp
    adapter.io.translation.request.ready := io.translationReady
    io.translationValid := adapter.io.translation.request.valid
    val translation = adapter.io.translation.request.bits
    io.translationPc := translation.virtualAddress
    io.translationRoot := translation.rootPpn
    io.translationAsid := translation.asid
    io.translationMode := translation.mode
    io.translationPrivilege := translation.privilege
    io.translationAccess := translation.access
    io.translationSum := translation.sum
    io.translationMxr := translation.mxr
    adapter.io.translation.response.valid := io.translationResponseValid
    adapter.io.translation.response.bits := 0.U.asTypeOf(new SvTranslationResponse)
    adapter.io.translation.response.bits.physicalAddress := io.translationPhysical
    adapter.io.translation.response.bits.pageFault := io.translationPage
    adapter.io.translation.response.bits.accessFault := io.translationError
    io.translationResponseReady := adapter.io.translation.response.ready
    adapter.io.physical.request.ready := io.physicalReady
    io.physicalValid := adapter.io.physical.request.valid
    io.physicalPc := adapter.io.physical.request.bits
    io.physicalMask := adapter.io.physical.requestMask
    adapter.io.physical.response.valid := io.physicalResponseValid
    adapter.io.physical.response.bits := (if (words == 4)
        Cat(io.physicalResponseHigh, io.physicalResponseLow) else io.physicalResponseLow)
    adapter.io.physical.responseError := io.physicalErrors(words - 1, 0)
    adapter.io.physical.responsePageFault := io.physicalPages(words - 1, 0)
    io.physicalResponseReady := adapter.io.physical.response.ready
    io.idle := adapter.io.idle
}

object InstructionPermissionGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new InstructionPermissionGsim(args(1).toInt,
        args.drop(2).contains("retimed"), args.drop(2).contains("aligned")), Array("--target-dir", args.head))
}
