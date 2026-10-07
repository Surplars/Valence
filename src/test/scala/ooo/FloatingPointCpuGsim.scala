package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import chisel3.util.experimental.BoringUtils
import soc.core.ooo._

/** External instruction device + observational probes, with no injected FP data. */
class FloatingPointCpuGsim(withMemory: Boolean = false, bufferedMemory: Boolean = false,
    compressed: Boolean = false, publishGc: Boolean = false) extends Module {
    require(!publishGc || (withMemory && compressed), "published GC fixture requires A/C memory geometry")
    private val p = OooParams(robEntries = 8, physicalRegs = 40, machineSystem = true,
        floatingPoint = FloatingPointConfig.fullFD, compressedInstructions = compressed,
        advertiseFloatingPoint = publishGc, atomicMemory = publishGc,
        branchPredictorEntries = 64, returnStackEntries = 2,
        pmpEntries = if (withMemory) 8 else 0, virtualMemoryLevels = if (withMemory) 3 else 0,
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = if (withMemory) 4096 else 0,
        bufferedRamStores = bufferedMemory, registeredMemoryRequests = bufferedMemory)
    val io = IO(new Bundle {
        val instruction0 = Input(Valid(UInt(32.W)))
        val instruction1 = Input(Valid(UInt(32.W)))
        val accepted0 = Output(Bool())
        val accepted1 = Output(Bool())
        val fetchPc = Output(UInt(64.W))
        val commitEnable = Input(Bool())
        val commit0 = Output(Valid(new CommitRecord(p)))
        val commit1 = Output(Valid(new CommitRecord(p)))
        val trap = Output(Valid(new HeadException(p)))
        val redirect = Output(Valid(new FrontendRedirect(p)))
        val inspectRegister = Input(UInt(5.W))
        val committedValue = Output(UInt(64.W))
        val fpBusy = Output(Bool())
        val fpFs = Output(UInt(2.W))
        val fpFcsr = Output(UInt(8.W))
        val fpStart = Output(Bool())
        val fpStartPc = Output(UInt(64.W))
        val fpRetire = Output(Bool())
        val fpComplete = Output(Bool())
        val fpCsrWrite = Output(Bool())
        val fpSetFs = Output(Bool())
        val memory = new DataPort
        val inspectFpRegister = Input(UInt(5.W))
        val committedFpValue = Output(UInt(64.W))
        val pauseFetch = Output(Bool())
    })
    val core = Module(new MachineCore(p))
    core.io.timerInterrupt := false.B
    core.io.timeValue := 0.U
    core.io.instructions(0) := io.instruction0
    core.io.instructions(1) := io.instruction1
    core.io.instructionFaults := VecInit(Seq.fill(2)(false.B))
    core.io.instructionPageFaults := VecInit(Seq.fill(2)(false.B))
    core.io.commitEnable := io.commitEnable
    core.io.inspectRegister := io.inspectRegister
    core.io.fenceIFlushReady := true.B
    core.io.msi.request.valid := false.B
    core.io.msi.request.bits := 0.U.asTypeOf(core.io.msi.request.bits)
    core.io.msi.response.ready := true.B
    if (withMemory) {
        io.memory <> core.io.memory
        core.io.fetchQuiescent.get := true.B
        core.io.vmFlushReady.get := true.B
        io.pauseFetch := core.io.pauseFetch.get
    } else {
        core.io.memory.request.ready := true.B
        core.io.memory.response.valid := false.B
        core.io.memory.response.bits := 0.U.asTypeOf(core.io.memory.response.bits)
        assert(!core.io.memory.request.valid, "FP CPU subset fixture has no memory instruction")
        io.memory.request.valid := false.B
        io.memory.request.bits := 0.U.asTypeOf(new DataRequest)
        io.memory.response.ready := false.B
        io.pauseFetch := false.B
    }
    io.accepted0 := core.io.accepted(0)
    io.accepted1 := core.io.accepted(1)
    io.fetchPc := core.io.fetchPc
    io.commit0 := core.io.commit(0)
    io.commit1 := core.io.commit(1)
    io.trap := core.io.trap
    io.redirect := core.io.redirect
    io.committedValue := core.io.committedValue
    val fp = core.core.backend.systemUnit.get.floatingPoint.get
    io.fpBusy := BoringUtils.bore(fp.io.busy)
    io.fpFs := BoringUtils.bore(fp.io.fs)
    io.fpFcsr := BoringUtils.bore(fp.io.fcsr)
    io.fpStart := BoringUtils.bore(fp.io.start.valid) && BoringUtils.bore(fp.io.start.ready)
    io.fpStartPc := BoringUtils.bore(fp.io.start.bits.pc)
    io.fpRetire := BoringUtils.bore(fp.fp.io.retireAccepted)
    io.fpComplete := BoringUtils.bore(fp.io.complete.valid)
    io.fpCsrWrite := BoringUtils.bore(fp.io.csr.valid) && BoringUtils.bore(fp.io.csr.ready) &&
        BoringUtils.bore(fp.io.csr.bits.write)
    io.fpSetFs := BoringUtils.bore(fp.io.setFs.valid) && BoringUtils.bore(fp.io.setFs.ready)
    // Observational only: every FPR update still originates from real CPU instructions.
    // Observe the committed architectural value, including a retired write
    // queued for the physical bank. Oracle expectations are unchanged.
    val committedFpRegisters = BoringUtils.bore(fp.fp.architecturalRegisters)
    io.committedFpValue := committedFpRegisters(io.inspectFpRegister)
}

object FloatingPointCpuGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FloatingPointCpuGsim, Array("--target-dir", args.head))
}

object FloatingPointMemoryCpuGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new FloatingPointCpuGsim(withMemory = true,
        bufferedMemory = args.lift(1).contains("buffered")), Array("--target-dir", args.head))
}

object FloatingPointIntegerRegressionGsimMain extends App {
    val p = OooParams(robEntries = 8, physicalRegs = 40, machineSystem = true,
        experimentalFloatingPoint = args.lift(1).contains("enabled"),
        speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096,
        bufferedRamStores = true)
    ChiselStage.emitCHIRRTLFile(new MachineCoreGsim(p), Array("--target-dir", args.head))
}
