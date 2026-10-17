package ooo

import _root_.circt.stage.ChiselStage
import chisel3._
import chisel3.util._
import soc.core.ooo._

class PreparedStorePoolInputs extends Bundle {
    val original = UInt(16.W)
    val prepared = UInt(16.W)
    val bare = Bool()
    val postedWindow = Bool()
    val head = UInt(4.W)
    val resident = UInt(4.W)
    val savedIndex = UInt(4.W)
    val savedTag = UInt(64.W)
    val rowTag = UInt(64.W)
    val present = Bool()
    val pending = Bool()
    val issued = Bool()
}

/** Actual production pool helper and actual resident selector; no copied ranking logic. */
class PreparedStorePoolSelector(candidate: Boolean, postedPriority: Boolean, predecoded: Boolean = true)
    extends Module {
    private val p = OooParams(robEntries = 16, physicalRegs = 48, tagBits = 64)
    val io = IO(new Bundle {
        val in = Input(new PreparedStorePoolInputs)
        val result = Output(UInt(27.W))
    })
    val lateEnable = candidate && !postedPriority
    val fallback = PreparedStorePool.fallback(io.in.original, io.in.prepared, io.in.bare, lateEnable)
    val eligible = if (postedPriority) {
        val prepared = io.in.prepared & Fill(16, io.in.bare)
        val base = Mux(io.in.original.orR, io.in.original, prepared)
        Mux(io.in.postedWindow && io.in.bare && io.in.original.orR, io.in.original | prepared, base)
    } else fallback._1
    val planner = Module(new ResidentMemoryPreparationSelector(p, predecodedHead = predecoded,
        latePoolEnable = lateEnable, directSelectedRank = lateEnable))
    planner.io.eligible := eligible
    planner.io.poolEnabled.foreach(_ := fallback._2)
    planner.io.head := io.in.head
    planner.io.headMask.foreach(_ := VecInit((0 until 16).map(i => i.U >= io.in.head)).asUInt)
    planner.io.resident.valid := io.in.present && io.in.pending && io.in.savedIndex === io.in.resident &&
        io.in.savedTag === io.in.rowTag
    planner.io.resident.bits := io.in.resident
    planner.io.issued := io.in.issued
    io.result := Cat(planner.io.selectedIndex, planner.io.selectedValid, planner.io.useResident,
        planner.io.freshIndex, planner.io.freshValid, planner.io.freshOwner)
}

class PreparedStorePoolGsim extends Module {
    val io = IO(new Bundle {
        val in = Input(new PreparedStorePoolInputs)
        val original = Output(UInt(27.W))
        val candidate = Output(UInt(27.W))
        val postedOriginal = Output(UInt(27.W))
        val postedCandidate = Output(UInt(27.W))
        val binaryCandidate = Output(UInt(27.W))
        val equivalent = Output(Bool())
    })
    val variants = Seq((false, false, true), (true, false, true), (false, true, true),
        (true, true, true), (true, false, false)).map { case (candidate, posted, predecoded) =>
        val dut = Module(new PreparedStorePoolSelector(candidate, posted, predecoded))
        dut.io.in := io.in
        dut.io.result
    }
    io.original := variants(0)
    io.candidate := variants(1)
    io.postedOriginal := variants(2)
    io.postedCandidate := variants(3)
    io.binaryCandidate := variants(4)
    io.equivalent := variants(0) === variants(1) && variants(2) === variants(3) &&
        variants(0) === variants(4)
}

object PreparedStorePoolGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new PreparedStorePoolGsim, Array("--target-dir", args.head))
}

object PreparedStorePoolAreaMain extends App {
    ChiselStage.emitSystemVerilogFile(new PreparedStorePoolSelector(args(1).toBoolean, postedPriority = false),
        Array("--target-dir", args.head), firtoolOpts = Array("--disable-all-randomization", "--strip-debug-info"))
}

/** Full production virtual qualification, before any prepared mask abstraction. */
class VirtualStoreOperandQualification extends Module {
    val io = IO(new Bundle {
        val flags = Input(UInt(15.W))
        val operation = Input(UInt(6.W))
        val control = Input(UInt(4.W))
        val virtualOperands = Output(Bool())
        val off = Output(Bool())
        val on = Output(Bool())
    })
    val f = io.flags
    val request = WireDefault(0.U.asTypeOf(new IntegerRequest))
    request.memory := f(4); request.store := f(5); request.atomic := f(6)
    request.system := f(7); request.mulDiv := f(8)
    request.fetchFault := f(9); request.fetchPageFault := f(10)
    request.operation := io.operation; request.controlFlow := io.control
    val virtualOperands = PreparedStorePool.virtualOperands(f(0), f(1), f(2), f(3), request,
        f(11), f(12), f(14))
    // Frozen old qualification, including the physical Bare range requirement.
    val bareOperands = f(0) && f(1) && !f(2) && f(3) &&
        request.memory && request.store && !request.atomic && !request.system && !request.mulDiv &&
        request.controlFlow === ControlFlow.none && request.operation === IntegerOp.add &&
        !request.fetchFault && !request.fetchPageFault && f(11) && f(12) && f(13)
    io.virtualOperands := virtualOperands
    io.off := bareOperands && !f(14)
    io.on := Mux(f(14), virtualOperands, bareOperands)
}

/** The real production pool plus the real Q/S planner, with full-tag owner inputs. */
class VirtualStoreOperandPoolGsim extends Module {
    private val p = CombinedTimingRepairR1Profile.config(true).coreParams
    val io = IO(new Bundle {
        val flags = Input(UInt(15.W))
        val operation = Input(UInt(6.W))
        val control = Input(UInt(4.W))
        val original = Input(UInt(16.W))
        val prepared = Input(UInt(16.W))
        val head = Input(UInt(4.W))
        val resident = Input(UInt(4.W))
        val descriptor = Input(UInt(4.W))
        val residentPresent = Input(Bool())
        val descriptorPresent = Input(Bool())
        val residentPending = Input(Bool())
        val descriptorPending = Input(Bool())
        val residentSavedIndex = Input(UInt(4.W))
        val descriptorSavedIndex = Input(UInt(4.W))
        val residentSavedTag = Input(UInt(64.W))
        val descriptorSavedTag = Input(UInt(64.W))
        val residentRowTag = Input(UInt(64.W))
        val descriptorRowTag = Input(UInt(64.W))
        val residentKilled = Input(Bool())
        val descriptorKilled = Input(Bool())
        val freshKilled = Input(Bool())
        val clear = Input(Bool())
        val issued = Input(Bool())
        val qualification = Output(UInt(3.W))
        val off = Output(UInt(25.W))
        val on = Output(UInt(25.W))
    })
    val qualification = Module(new VirtualStoreOperandQualification)
    qualification.io.flags := io.flags
    qualification.io.operation := io.operation
    qualification.io.control := io.control
    io.qualification := Cat(qualification.io.on, qualification.io.off, qualification.io.virtualOperands)
    def arm(enabled: Boolean): UInt = {
        val qualified = if (enabled) qualification.io.on else qualification.io.off
        val pool = PreparedStorePool.fallback(io.original, io.prepared & Fill(16, qualified),
            (if (enabled) true.B else !io.flags(14)), lateEnable = true)
        val planner = Module(new MemoryPreparationDescriptorSelector(p))
        planner.io.eligible := pool._1
        planner.io.enabled := pool._2
        planner.io.head := io.head
        planner.io.headMask := VecInit((0 until 16).map(i => i.U >= io.head)).asUInt
        planner.io.resident.valid := io.residentPresent && io.residentPending &&
            io.residentSavedIndex === io.resident && io.residentSavedTag === io.residentRowTag
        planner.io.resident.bits := io.resident
        planner.io.descriptor.valid := io.descriptorPresent && io.descriptorPending &&
            io.descriptorSavedIndex === io.descriptor && io.descriptorSavedTag === io.descriptorRowTag
        planner.io.descriptor.bits := io.descriptor
        planner.io.issued := io.issued
        // Existing caller kill/clear gates, after ranking; these do not make a new candidate.
        Cat(planner.io.keepDescriptor && !io.clear && !io.descriptorKilled,
            planner.io.keepResident && !io.clear && !io.residentKilled,
            planner.io.transfer && !io.clear && !io.descriptorKilled,
            planner.io.capture && !io.clear && !io.freshKilled,
            planner.io.freshValid, planner.io.freshIndex, planner.io.freshOwner)
    }
    io.off := arm(false)
    io.on := arm(true)
}
object VirtualStoreOperandPoolGsimMain extends App {
    ChiselStage.emitCHIRRTLFile(new VirtualStoreOperandPoolGsim, Array("--target-dir", args(0)))
}
object VirtualStoreOperandQualificationVerilogMain extends App {
    ChiselStage.emitSystemVerilogFile(new VirtualStoreOperandQualification, Array("--target-dir", args(0)),
        firtoolOpts = Array("--disable-all-randomization", "--strip-debug-info"))
}
