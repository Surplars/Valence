package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._
import soc.ip.memory.NativeMemoryPort

/** Single-clock component preparation, not an executing H+F/D core.
  * Real decoded memory commands traverse production FP state, LSU, joint
  * response storage, the adapter and the nested walker. No injected FP result,
  * trap, cancellation, retirement architecture or automatic context bank.
  * Exact-token grants only release this component owner after checking it.
  */
class FpGuestMemoryGsim extends Module {
    private val p = OooParams(robEntries = 16, tagBits = 64, machineSystem = true,
        pmpEntries = 8, virtualMemoryLevels = 3, hypervisorExperiment = true,
        floatingPoint = FloatingPointConfig.fullFD.copy(resources = FloatingPointResourceConfig.fpga))
    val io = IO(new Bundle {
        val issueValid = Input(Bool())
        val issueReady = Output(Bool())
        val instruction = Input(UInt(32.W))
        val base = Input(UInt(64.W))
        val pc = Input(UInt(64.W))
        val token = Input(new RobToken(p))
        val headAuthorized = Input(Bool())
        val retire = Input(Valid(new RobToken(p)))
        val retireAccepted = Output(Bool())
        val setFs = Flipped(Decoupled(UInt(2.W)))
        val csr = Flipped(Decoupled(new FloatingPointCsr))
        val guestFs = Input(UInt(2.W))
        val context = Input(new GuestTranslationRequest)
        val hostSatp = Input(UInt(64.W))
        val pmpTop = Input(UInt(54.W))
        val pmpPermission = Input(UInt(3.W))
        val pmaDenied = Input(Bool())
        val physical = new NativeMemoryPort
        val pte = new SvPteReadPort
        val physicalCheck = Output(Valid(new GuestPhysicalAccess))
        val executeValid = Output(Bool())
        val executeFire = Output(Bool())
        val adapterFire = Output(Bool())
        val translatedHandling = Output(Bool())
        val virtualRequest = Output(Valid(new DataRequest))
        val adapterResponse = Output(Valid(new DataResponse))
        val adapterResponseFire = Output(Bool())
        val adapterFault = Output(new GuestFaultMetadata)
        val responseEpoch = Output(UInt(8.W))
        val bufferedResponse = Output(Valid(new DataResponse))
        val bufferedResponseFire = Output(Bool())
        val bufferedFault = Output(new GuestFaultMetadata)
        val pipelineComplete = Output(Valid(new BackendCompletion(p)))
        val convertedResult = Output(Valid(new FloatingPointResult(p)))
        val complete = Output(Valid(new BackendCompletion(p)))
        val mutation = Output(Valid(new FloatingPointMutation))
        val fs = Output(UInt(2.W))
        val fcsr = Output(UInt(8.W))
        val stateBusy = Output(Bool())
        val memoryBusy = Output(Bool())
        val adapterIdle = Output(Bool())
        val translatorIdle = Output(Bool())
        val f0 = Output(UInt(64.W))
        val f1 = Output(UInt(64.W))
        val f2 = Output(UInt(64.W))
        val f3 = Output(UInt(64.W))
        val f4 = Output(UInt(64.W))
        val f5 = Output(UInt(64.W))
        val f6 = Output(UInt(64.W))
        val f7 = Output(UInt(64.W))
        val f8 = Output(UInt(64.W))
        val f9 = Output(UInt(64.W))
        val f10 = Output(UInt(64.W))
        val f11 = Output(UInt(64.W))
        val f12 = Output(UInt(64.W))
        val f13 = Output(UInt(64.W))
        val f14 = Output(UInt(64.W))
        val f15 = Output(UInt(64.W))
        val f16 = Output(UInt(64.W))
        val f17 = Output(UInt(64.W))
        val f18 = Output(UInt(64.W))
        val f19 = Output(UInt(64.W))
        val f20 = Output(UInt(64.W))
        val f21 = Output(UInt(64.W))
        val f22 = Output(UInt(64.W))
        val f23 = Output(UInt(64.W))
        val f24 = Output(UInt(64.W))
        val f25 = Output(UInt(64.W))
        val f26 = Output(UInt(64.W))
        val f27 = Output(UInt(64.W))
        val f28 = Output(UInt(64.W))
        val f29 = Output(UInt(64.W))
        val f30 = Output(UInt(64.W))
        val f31 = Output(UInt(64.W))
    })
    val state = Module(new FloatingPointState(p, dualFs = true))
    val memory = Module(new FloatingPointMemoryPipeline(p))
    val adapter = Module(new GuestDataTranslationAdapter)
    val translator = Module(new GuestTranslationService(p.pmpEntries))
    state.io.headAuthorized := io.headAuthorized
    state.io.flush := false.B
    // Permission context is the issuing instruction's architectural guest owner.
    // Translation input perturbations below do not perform a context switch.
    state.io.guestContext.get.virtualized := true.B
    state.io.guestContext.get.fs := io.guestFs
    state.io.setFs <> io.setFs
    state.io.csr <> io.csr
    state.io.retire := io.retire
    io.retireAccepted := state.io.retireAccepted
    state.io.issue.valid := io.issueValid
    io.issueReady := state.io.issue.ready
    state.io.issue.bits := 0.U.asTypeOf(new FloatingPointCommand(p))
    val command = state.io.issue.bits
    command.token := io.token
    command.instruction := io.instruction
    command.integerSource := io.base
    command.sources(0) := io.instruction(19, 15)
    command.sources(1) := io.instruction(24, 20)
    command.sources(2) := io.instruction(31, 27)
    command.destination := io.instruction(11, 7)
    command.singleResult := io.instruction(14, 12) === 2.U
    command.writesFp := io.instruction(6, 0) === 7.U
    // Raw FSW operands must not undergo computational NaN-box checks.
    when(state.io.issue.fire) {
        assert(FloatingPointSubset.memory(io.instruction), "fixture accepts only actual FP memory encodings")
    }
    val pc = RegEnable(io.pc, state.io.issue.fire)
    memory.io.execute <> state.io.execute
    memory.io.pc := pc
    memory.io.trap := false.B
    memory.io.dataPrivilege := io.context.effectivePrivilege
    val translated = FloatingPointMemoryContext.translated(p.virtualMemoryLevels,
        io.context.effectivePrivilege, io.hostSatp, io.context.virtualized)
    memory.io.virtualized := translated
    memory.io.guestAddress.get := io.context.virtualized
    memory.io.guestFault.get := adapter.io.guestFault
    val pmp = WireDefault(0.U.asTypeOf(new PmpState))
    pmp.cfg(0) := Cat(0.U(3.W), 1.U(2.W), io.pmpPermission)
    pmp.addr(0) := io.pmpTop
    PmpState.decodeRegions(pmp)
    memory.io.pmpState := pmp
    translator.io.pmpState := pmp
    adapter.io.virtual <> memory.io.memory
    adapter.io.context := io.context
    adapter.io.cancel := false.B
    adapter.io.pmaDenied := io.pmaDenied
    io.physical <> adapter.io.physical
    io.physicalCheck := adapter.io.physicalCheck
    adapter.io.translation.request <> translator.io.request
    adapter.io.translation.response <> translator.io.response
    translator.io.cancel := false.B
    io.pte <> translator.io.memory
    state.io.result.valid := memory.io.complete.valid
    state.io.result.bits := FloatingPointResultTransport.fromMemory(p, memory.io.complete.bits)
    memory.io.complete.ready := state.io.result.ready
    io.complete.valid := state.io.complete.valid
    io.complete.bits := FloatingPointResultTransport.toBackend(p, state.io.complete.bits, pc + 4.U)
    io.pipelineComplete.valid := memory.io.complete.valid
    io.pipelineComplete.bits := memory.io.complete.bits
    io.convertedResult.valid := state.io.result.valid
    io.convertedResult.bits := state.io.result.bits
    io.executeValid := state.io.execute.valid
    io.executeFire := memory.io.execute.fire
    io.adapterFire := adapter.io.virtual.request.fire
    io.translatedHandling := translated
    io.virtualRequest.valid := memory.io.memory.request.valid
    io.virtualRequest.bits := memory.io.memory.request.bits
    io.adapterResponse.valid := adapter.io.virtual.response.valid
    io.adapterResponse.bits := adapter.io.virtual.response.bits
    io.adapterResponseFire := adapter.io.virtual.response.fire
    io.adapterFault := adapter.io.guestFault
    io.responseEpoch := adapter.io.responseEpoch
    io.bufferedResponse.valid := BoringUtils.bore(memory.responses.io.upstream.response.valid)
    io.bufferedResponse.bits := BoringUtils.bore(memory.responses.io.upstream.response.bits)
    io.bufferedResponseFire := io.bufferedResponse.valid &&
        BoringUtils.bore(memory.responses.io.upstream.response.ready)
    io.bufferedFault := BoringUtils.bore(memory.responses.io.upstreamGuestFault.get)
    io.mutation := state.io.mutation.get
    io.fs := state.io.fs
    io.fcsr := state.io.fcsr
    io.stateBusy := state.io.busy
    io.memoryBusy := memory.io.busy
    io.adapterIdle := adapter.io.idle
    io.translatorIdle := translator.io.idle
    val architectural = BoringUtils.bore(state.architecturalRegisters)
    io.f0 := architectural(0)
    io.f1 := architectural(1)
    io.f2 := architectural(2)
    io.f3 := architectural(3)
    io.f4 := architectural(4)
    io.f5 := architectural(5)
    io.f6 := architectural(6)
    io.f7 := architectural(7)
    io.f8 := architectural(8)
    io.f9 := architectural(9)
    io.f10 := architectural(10)
    io.f11 := architectural(11)
    io.f12 := architectural(12)
    io.f13 := architectural(13)
    io.f14 := architectural(14)
    io.f15 := architectural(15)
    io.f16 := architectural(16)
    io.f17 := architectural(17)
    io.f18 := architectural(18)
    io.f19 := architectural(19)
    io.f20 := architectural(20)
    io.f21 := architectural(21)
    io.f22 := architectural(22)
    io.f23 := architectural(23)
    io.f24 := architectural(24)
    io.f25 := architectural(25)
    io.f26 := architectural(26)
    io.f27 := architectural(27)
    io.f28 := architectural(28)
    io.f29 := architectural(29)
    io.f30 := architectural(30)
    io.f31 := architectural(31)
}

object FpGuestMemoryGsimMain extends App {
    require(args.length == 1, "output-directory")
    ChiselStage.emitCHIRRTLFile(new FpGuestMemoryGsim, Array("--target-dir", args.head))
}
