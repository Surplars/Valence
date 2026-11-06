package soc.core.inorder

import chisel3._
import chisel3.util._

class FiveStagePmpEntry(p: FiveStageConfig) extends Bundle {
    val config = UInt(8.W)
    val address = UInt((p.physicalBits - 2).W)
    val lower = UInt((p.physicalBits + 1).W)
    val upper = UInt((p.physicalBits + 1).W)
}

class FiveStageTranslationContext(p: FiveStageConfig) extends Bundle {
    val privilege = UInt(2.W)
    val dataPrivilege = UInt(2.W)
    val satp = UInt(p.xlen.W)
    val sum = Bool()
    val mxr = Bool()
    // Exact architectural sidecar, not an extra PMP permission-cache entry.
    val pmpAllOff = Bool()
    val guest = if (p.withH) Some(new I1GuestContext) else None
}

/** Optional M/S/U state. Only WB changes architectural state; serial CSR/xRET/SFENCE owners drain
  * older instructions. Optional RV64 F/D, H and M/S IMSIC; no Sstc. UXL/SXL are fixed, ASIDLEN=0, Sv39 uses Svade.
  */
class FiveStageMachineState(p: FiveStageConfig) extends Module {
    val io = IO(new Bundle {
        val readAddress = Input(UInt(12.W))
        val readData = Output(UInt(p.xlen.W))
        val readLegal = Output(Bool())
        val readDataForWrite = Output(UInt(p.xlen.W))
        val aiaSelectors = if (p.withAia) Some(Output(Vec(2, UInt(12.W)))) else None
        val write = Flipped(Valid(new Bundle {
            val address = UInt(12.W)
            val data = UInt(p.xlen.W)
        }))
        val retire = Input(Bool())
        val trap = Flipped(Valid(new Bundle {
            val pc = UInt(p.xlen.W)
            val cause = UInt(p.xlen.W)
            val tval = UInt(p.xlen.W)
            val guest = if (p.withH) Some(new Bundle {
                val address = Bool(); val physical = UInt(64.W); val implicitPte = Bool()
            }) else None
        }))
        val mret = Input(Bool()); val sret = Input(Bool()); val sfence = Input(Bool())
        val mretLegal = Output(Bool()); val sretLegal = Output(Bool())
        val sfenceLegal = Output(Bool()); val wfiLegal = Output(Bool())
        val time = Input(UInt(64.W))
        val externalIrq = Input(Bool()); val supervisorExternalIrq = Input(Bool())
        val timerIrq = Input(Bool()); val softwareIrq = Input(Bool())
        val irqPending = Output(Bool()); val irqCause = Output(UInt(p.xlen.W))
        val trapPc = Output(UInt(p.xlen.W))
        val returnPc = Output(UInt(p.xlen.W)); val supervisorReturnPc = Output(UInt(p.xlen.W))
        val context = Output(new FiveStageTranslationContext(p))
        val hypervisor = if (p.withH) Some(Output(new I1HypervisorControls)) else None
        val pmp = Output(Vec(p.pmpEntries, new FiveStagePmpEntry(p)))
        val contextBarrier = Output(Bool()); val invalidateTranslation = Output(Bool())
        val cycles = Output(UInt(64.W)); val instructions = Output(UInt(64.W))
        val fpRetire = Input(Bool()); val fpFlags = Input(UInt(5.W))
        val fpEnabled = Output(Bool()); val fpRounding = Output(UInt(3.W))
        val vectorRetire = if (p.spinor) Some(Input(Bool())) else None
        val vectorEnabled = if (p.spinor) Some(Output(Bool())) else None
        val committedFpFlags = if (p.spinor) Some(Output(UInt(5.W))) else None
    })
    val hypervisor = if (p.withH) Some(Module(new I1HypervisorState(p))) else None
    val virtualized = hypervisor.map(_.io.virtualized).getOrElse(false.B)
    val aiaSelectors = if (p.withAia) Some(RegInit(VecInit(Seq.fill(2)(0.U(12.W))))) else None
    io.aiaSelectors.foreach(_ := aiaSelectors.get)
    val lower = p.withUser || p.withSupervisor
    val fs = if (p.withF) RegInit(0.U(2.W)) else 0.U(2.W)
    val frm = if (p.withF) RegInit(0.U(3.W)) else 0.U(3.W)
    val fflags = if (p.withF) RegInit(0.U(5.W)) else 0.U(5.W)
    io.fpEnabled := p.withF.B && fs =/= 0.U && hypervisor.map(_.io.guestFpEnabled).getOrElse(true.B)
    io.fpRounding := frm
    val vs = if (p.spinor) Some(RegInit(0.U(2.W))) else None
    io.vectorEnabled.foreach(_ := vs.get =/= 0.U && hypervisor.map(_.io.guestVectorEnabled).getOrElse(true.B))
    io.committedFpFlags.foreach(_ := fflags)
    if (p.spinor) when(io.vectorRetire.get) { vs.get := 3.U }
    if (p.withF) when(io.fpRetire) { fs := 3.U; fflags := fflags | io.fpFlags }
    val privilege = if (lower) RegInit(3.U(2.W)) else 3.U(2.W)
    val mpp = if (lower) RegInit(3.U(2.W)) else 3.U(2.W)
    val mieGlobal = RegInit(false.B); val mpie = RegInit(false.B)
    val mprv = if (p.withUser) RegInit(false.B) else false.B
    val sieGlobal = if (p.withSupervisor) RegInit(false.B) else false.B
    val spie = if (p.withSupervisor) RegInit(false.B) else false.B
    val spp = if (p.withSupervisor) RegInit(false.B) else false.B
    val sum = if (p.withSupervisor) RegInit(false.B) else false.B
    val mxr = if (p.withSupervisor) RegInit(false.B) else false.B
    val tvm = if (p.withSv39) RegInit(false.B) else false.B
    val tw = if (lower) RegInit(false.B) else false.B
    val tsr = if (p.withSupervisor) RegInit(false.B) else false.B
    val mie = RegInit(0.U(12.W))
    val medeleg = if (p.withSupervisor) RegInit(0.U((if (p.withH) 32 else 16).W)) else 0.U(16.W)
    val midelegStorage = if (p.withSupervisor) RegInit(0.U(12.W)) else 0.U(12.W)
    val mideleg = midelegStorage | (if (p.withH) 0x444.U(12.W) else 0.U(12.W))
    val supervisorPending = if (p.withSupervisor) RegInit(0.U(3.W)) else 0.U(3.W) // SSIP/STIP/SEIP
    val mcounteren = if (lower) RegInit(0.U(3.W)) else 0.U(3.W)
    val scounteren = if (p.withSupervisor) RegInit(0.U(3.W)) else 0.U(3.W)
    val mtvec = RegInit(p.trapVector.U(p.xlen.W))
    val mscratch = RegInit(0.U(p.xlen.W)); val mepc = RegInit(0.U(p.xlen.W))
    val mcause = RegInit(0.U(p.xlen.W)); val mtval = RegInit(0.U(p.xlen.W))
    val stvec = if (p.withSupervisor) RegInit(0.U(p.xlen.W)) else 0.U(p.xlen.W)
    val sscratch = if (p.withSupervisor) RegInit(0.U(p.xlen.W)) else 0.U(p.xlen.W)
    val sepc = if (p.withSupervisor) RegInit(0.U(p.xlen.W)) else 0.U(p.xlen.W)
    val scause = if (p.withSupervisor) RegInit(0.U(p.xlen.W)) else 0.U(p.xlen.W)
    val stval = if (p.withSupervisor) RegInit(0.U(p.xlen.W)) else 0.U(p.xlen.W)
    val satp = if (p.withSv39) RegInit(0.U(p.xlen.W)) else 0.U(p.xlen.W)
    hypervisor.foreach { h =>
        h.io.privilege := privilege; h.io.mpp := mpp; h.io.mprv := mprv
        h.io.readAddress := io.readAddress
        h.io.write.valid := io.write.valid
        h.io.write.bits.address := io.write.bits.address; h.io.write.bits.data := io.write.bits.data
        h.io.mie := mie; h.io.time := io.time
        h.io.fpDirty := io.fpRetire || (io.write.valid && io.write.bits.address >= 1.U &&
            io.write.bits.address <= 3.U)
        h.io.vectorDirty := io.vectorRetire.getOrElse(false.B)
        h.io.mret := io.mret; h.io.sret := io.sret
        h.io.trap.valid := io.trap.valid
        h.io.trap.bits.pc := io.trap.bits.pc; h.io.trap.bits.cause := io.trap.bits.cause
        h.io.trap.bits.tval := io.trap.bits.tval
        h.io.trap.bits.guestAddress := io.trap.bits.guest.get.address
        h.io.trap.bits.guestPhysical := io.trap.bits.guest.get.physical
        h.io.trap.bits.implicitPte := io.trap.bits.guest.get.implicitPte
        io.context.guest.get := h.io.context
        val controls = io.hypervisor.get
        controls.virtualized := virtualized; controls.hu := h.io.hu; controls.tvm := tvm
        controls.csrVirtual := h.io.readVirtual
        controls.sretVirtual := virtualized && (privilege === 0.U || h.io.vtsr)
        controls.sfenceVirtual := virtualized && (privilege === 0.U || h.io.vtvm)
        controls.wfiVirtual := virtualized && !tw && (privilege === 0.U || h.io.vtw)
    }
    val hostWrite = io.write.valid && !hypervisor.map(_.io.shadowWrite).getOrElse(false.B)
    val pmpConfig = if (p.pmpEntries > 0) RegInit(VecInit(Seq.fill(p.pmpEntries)(0.U(8.W))))
        else Wire(Vec(0, UInt(8.W)))
    val pmpAddress = if (p.pmpEntries > 0)
        RegInit(VecInit(Seq.fill(p.pmpEntries)(0.U((p.physicalBits - 2).W))))
        else Wire(Vec(0, UInt((p.physicalBits - 2).W)))
    val pmpConfigNext = WireDefault(pmpConfig)
    val pmpAddressNext = WireDefault(pmpAddress)
    val pmpAllOff = if (p.fpgaTimingCuts && p.pmpEntries > 0) {
        val off = RegInit(true.B)
        off := !VecInit(pmpConfigNext.toSeq.map(_(4, 3).orR)).asUInt.orR
        when(!reset.asBool) {
            assert(off === !VecInit(pmpConfig.toSeq.map(_(4, 3).orR)).asUInt.orR,
                "PMP all-OFF proof must commit on the architectural CSR edge")
        }
        off
    } else if (p.pmpEntries == 0) true.B
    else !VecInit(pmpConfig.toSeq.map(_(4, 3).orR)).asUInt.orR
    // Cache all NAPOT ranges, not just the currently selected mode. Only ONE pmpaddr CSR can change per WB.
    // Config-byte writes select the cached modes atomically without replicating carry/variable-shift arithmetic.
    val pmpNapotLower = if (p.pmpEntries > 0)
        RegInit(VecInit(Seq.fill(p.pmpEntries)(0.U((p.physicalBits + 1).W))))
        else Wire(Vec(0, UInt((p.physicalBits + 1).W)))
    val pmpNapotUpper = if (p.pmpEntries > 0)
        RegInit(VecInit(Seq.fill(p.pmpEntries)(8.U((p.physicalBits + 1).W))))
        else Wire(Vec(0, UInt((p.physicalBits + 1).W)))
    val pmpNa4Upper = if (p.pmpEntries > 0)
        RegInit(VecInit(Seq.fill(p.pmpEntries)(4.U((p.physicalBits + 1).W))))
        else Wire(Vec(0, UInt((p.physicalBits + 1).W)))
    // Selected effective bounds are architectural-CSR sidecars, updated on
    // the SAME WB edge. Remove mode muxes/fanout from every IT/DT PMP query.
    val effectiveLower = if (p.fpgaTimingCuts && p.pmpEntries > 0) Some(RegInit(VecInit(
        Seq.fill(p.pmpEntries)(0.U((p.physicalBits + 1).W))))) else None
    val effectiveUpper = if (p.fpgaTimingCuts && p.pmpEntries > 0) Some(RegInit(VecInit(
        Seq.fill(p.pmpEntries)(8.U((p.physicalBits + 1).W))))) else None
    for (i <- 0 until p.pmpEntries) {
        val mode = pmpConfig(i)(4, 3)
        val normal = (pmpAddress(i) << 2).pad(p.physicalBits + 1)
        val previous = if (i == 0) 0.U((p.physicalBits + 1).W)
            else (pmpAddress(i - 1) << 2).pad(p.physicalBits + 1)
        io.pmp(i).config := pmpConfig(i); io.pmp(i).address := pmpAddress(i)
        val lower = Mux(mode === 1.U, previous, Mux(mode === 2.U, normal, pmpNapotLower(i)))
        val upper = Mux(mode === 1.U, normal, Mux(mode === 2.U, pmpNa4Upper(i), pmpNapotUpper(i)))
        io.pmp(i).lower := effectiveLower.map(_(i)).getOrElse(lower)
        io.pmp(i).upper := effectiveUpper.map(_(i)).getOrElse(upper)
        if (p.fpgaTimingCuts) when(!reset.asBool) {
            assert(io.pmp(i).lower === lower && io.pmp(i).upper === upper,
                "registered effective PMP range differs from architectural mode/address")
        }
    }
    val inhibit = RegInit(0.U(3.W))
    val cycles = RegInit(0.U(64.W)); val instructions = RegInit(0.U(64.W))
    when(!inhibit(0)) { cycles := cycles + 1.U }
    when(io.retire && !inhibit(2)) { instructions := instructions + 1.U }
    io.cycles := cycles; io.instructions := instructions
    val sPending = (supervisorPending(0).asUInt << 1) | (supervisorPending(1).asUInt << 5) |
        ((supervisorPending(2) || (p.withSupervisor.B && io.supervisorExternalIrq)).asUInt << 9)
    val mip = (io.externalIrq.asUInt << 11) | (io.timerIrq.asUInt << 7) |
        (io.softwareIrq.asUInt << 3) | sPending | hypervisor.map(_.io.virtualPending).getOrElse(0.U)
    val pending = mip & mie
    val machinePending = pending & ~mideleg
    val guestEligible = pending & mideleg & hypervisor.map(_.io.hideleg).getOrElse(0.U(12.W))
    val supervisorEligible = pending & mideleg & ~hypervisor.map(_.io.hideleg).getOrElse(0.U(12.W))
    val takeMachine = machinePending.orR && (privilege < 3.U || mieGlobal)
    val takeSupervisor = p.withSupervisor.B && supervisorEligible.orR &&
        (virtualized || privilege < 1.U || (privilege === 1.U && sieGlobal))
    val takeGuest = hypervisor.map(h => virtualized && guestEligible.orR &&
        (privilege === 0.U || h.io.guestInterruptEnable)).getOrElse(false.B)
    val eligible = Mux(takeMachine, machinePending, Mux(takeSupervisor, supervisorEligible, guestEligible))
    // Standard priority MEI, MSI, MTI, SEI, SSI, STI; no U interrupts.
    val irqId = MuxCase(5.U, Seq(eligible(11) -> 11.U, eligible(3) -> 3.U, eligible(7) -> 7.U,
        eligible(9) -> 9.U, eligible(1) -> 1.U, eligible(5) -> 5.U,
        eligible(10) -> 10.U, eligible(2) -> 2.U, eligible(6) -> 6.U))
    val qualifiedIrq = takeMachine || takeSupervisor || takeGuest
    val qualifiedCause = (BigInt(1) << (p.xlen - 1)).U(p.xlen.W) | irqId
    if (p.fpgaTimingCuts) {
        // Register eligibility and its matching cause together, BEFORE the
        // pipeline-drain/redirect fanout. Serial WB state changes invalidate
        // the snapshot at the same edge, so stale enables/delegation cannot
        // take an interrupt after a CSR disable or privilege return.
        val snapshotPending = RegInit(false.B)
        val snapshotCause = Reg(UInt(p.xlen.W))
        snapshotPending := qualifiedIrq
        when(qualifiedIrq) { snapshotCause := qualifiedCause }
        when(io.write.valid || io.trap.valid || io.mret || io.sret) { snapshotPending := false.B }
        io.irqPending := snapshotPending
        io.irqCause := snapshotCause
    } else {
        io.irqPending := qualifiedIrq
        io.irqCause := qualifiedCause
    }
    val trapId = io.trap.bits.cause(if (p.withH) 4 else 3, 0)
    val delegated = p.withSupervisor.B && privilege =/= 3.U &&
        Mux(io.trap.bits.cause(p.xlen - 1), mideleg.pad(if (p.withH) 32 else 16)(trapId), medeleg(trapId))
    hypervisor.foreach(_.io.delegated := delegated)
    val guestTrap = hypervisor.map(_.io.guestTrap).getOrElse(false.B)
    val vector = Mux(delegated, stvec, mtvec)
    val architecturalTrapPc = Cat(vector(p.xlen - 1, 2), 0.U(2.W)) +
        Mux(io.trap.bits.cause(p.xlen - 1) && vector(1, 0) === 1.U, trapId << 2, 0.U)
    if (p.fpgaTimingCuts) {
        def preparedVector(value: UInt): UInt = {
            // Only the low four BASE words can depend on the late cause.
            // Prepare the upper carry candidate from the CSR alone, before
            // delegation/cause selection; never start an XLEN carry chain
            // after MEM's trap/IRQ qualifier. Preserve modulo-XLEN overflow.
            val low = value(5, 2) +& trapId(3, 0)
            val high = value(p.xlen - 1, 6)
            val highPlusOne = I1TimingMath.incrementPowerOfTwo(high, 0, 8)
            val indexed = Cat(Mux(low(4), highPlusOne, high), low(3, 0), 0.U(2.W))
            Mux(io.trap.bits.cause(p.xlen - 1) && value(1, 0) === 1.U,
                indexed, Cat(value(p.xlen - 1, 2), 0.U(2.W)))
        }
        io.trapPc := Mux(delegated, preparedVector(stvec), preparedVector(mtvec))
        when(!reset.asBool) {
            assert(io.trapPc === Mux(guestTrap, hypervisor.map(_.io.guestTrapPc).getOrElse(0.U), architecturalTrapPc), "prepared trap vector changed BASE/cause/delegation")
        }
    } else io.trapPc := architecturalTrapPc
    hypervisor.foreach(h => when(guestTrap) { io.trapPc := h.io.guestTrapPc })
    io.returnPc := mepc
    io.supervisorReturnPc := Mux(virtualized, hypervisor.map(_.io.guestReturnPc).getOrElse(0.U), sepc)
    io.mretLegal := privilege === 3.U
    io.sretLegal := p.withSupervisor.B && privilege >= 1.U && !(privilege === 1.U && !virtualized && tsr) &&
        !hypervisor.map(h => virtualized && h.io.vtsr).getOrElse(false.B)
    io.sfenceLegal := p.withSupervisor.B && privilege >= 1.U && !(privilege === 1.U && !virtualized && tvm) &&
        !hypervisor.map(h => virtualized && h.io.vtvm).getOrElse(false.B)
    // WFI is a permitted no-op, not clock gating; TW is implemented conservatively as an immediate trap.
    io.wfiLegal := privilege >= 1.U && !(privilege < 3.U && tw) &&
        !hypervisor.map(h => virtualized && h.io.vtw).getOrElse(false.B)
    io.context.privilege := privilege
    io.context.dataPrivilege := Mux(privilege === 3.U && mprv, mpp, privilege)
    io.context.satp := satp; io.context.sum := sum; io.context.mxr := mxr
    io.context.pmpAllOff := pmpAllOff
    val mstatus = hypervisor.map(_.io.machineStatus).getOrElse(0.U(p.xlen.W)) | (mieGlobal.asUInt << 3) | (mpie.asUInt << 7) | (mpp << 11) |
        (sieGlobal.asUInt << 1) | (spie.asUInt << 5) | (spp.asUInt << 8) |
        (mprv.asUInt << 17) | (sum.asUInt << 18) | (mxr.asUInt << 19) |
        (tvm.asUInt << 20) | (tw.asUInt << 21) | (tsr.asUInt << 22) |
        (fs << 13) | ((fs === 3.U).asUInt << (p.xlen - 1)) |
        (if (p.spinor) (vs.get << 9) | ((vs.get === 3.U).asUInt << (p.xlen - 1)) else 0.U) |
        (if (p.xlen == 64) ((if (p.withUser) BigInt(2) << 32 else BigInt(0)) |
            (if (p.withSupervisor) BigInt(2) << 34 else BigInt(0))).U(64.W) else 0.U(32.W))
    val sstatusMask = (BigInt(1) << 1) | (BigInt(1) << 5) | (BigInt(1) << 8) |
        (BigInt(1) << 18) | (BigInt(1) << 19) | (if (p.xlen == 64) BigInt(3) << 32 else BigInt(0)) |
        (if (p.withF) (BigInt(3) << 13) | (BigInt(1) << (p.xlen - 1)) else BigInt(0)) |
        (if (p.spinor) BigInt(3) << 9 else BigInt(0))
    val misa = (BigInt(if (p.xlen == 64) 2 else 1) << (p.xlen - 2)) | (BigInt(1) << 8) |
        (if (p.withA) BigInt(1) else BigInt(0)) | (if (p.withC) BigInt(1) << 2 else BigInt(0)) |
        (if (p.withM) BigInt(1) << 12 else BigInt(0)) |
        (if (p.withF) BigInt(1) << 5 else BigInt(0)) | (if (p.withD) BigInt(1) << 3 else BigInt(0)) |
        (if (p.withUser) BigInt(1) << 20 else BigInt(0)) |
        (if (p.withSupervisor) BigInt(1) << 18 else BigInt(0)) |
        (if (p.withH) BigInt(1) << 7 else BigInt(0)) |
        // The integrated Spinor configuration exposes the architectural vector path.
        (if (p.spinor) BigInt(1) << 21 else BigInt(0))
    val pmpPairs = (0 until p.pmpCsrEntries).map(i => (0x3b0 + i).U ->
        (if (i < p.pmpEntries) pmpAddress(i).pad(p.xlen) else 0.U(p.xlen.W))) ++
        (0 until (p.pmpCsrEntries * 8 / p.xlen)).map { g =>
            val bytes = (0 until p.xlen / 8).map { b =>
                val i = g * (p.xlen / 8) + b
                if (i < p.pmpEntries) pmpConfig(i) else 0.U(8.W)
            }
            (0x3a0 + g * (if (p.xlen == 64) 2 else 1)).U -> Cat(bytes.reverse)
        }
    val readPairs = Seq(
        0x300.U -> mstatus.pad(p.xlen), 0x301.U -> misa.U(p.xlen.W), 0x304.U -> mie.pad(p.xlen),
        0x305.U -> mtvec, 0x320.U -> inhibit.pad(p.xlen), 0x340.U -> mscratch, 0x341.U -> mepc,
        0x342.U -> mcause, 0x343.U -> mtval, 0x344.U -> mip.pad(p.xlen),
        0xb00.U -> cycles(p.xlen - 1, 0), 0xb02.U -> instructions(p.xlen - 1, 0),
        0xc00.U -> cycles(p.xlen - 1, 0), 0xc01.U ->
            Mux(virtualized, hypervisor.map(_.io.guestTime).getOrElse(io.time), io.time)(p.xlen - 1, 0),
        0xc02.U -> instructions(p.xlen - 1, 0),
        0xf11.U -> 0.U(p.xlen.W), 0xf12.U -> 1.U(p.xlen.W), 0xf13.U -> 0.U(p.xlen.W),
        0xf14.U -> p.hartId.U(p.xlen.W)
    ) ++ (if (p.withF) Seq(0x001.U -> fflags.pad(p.xlen), 0x002.U -> frm.pad(p.xlen),
        0x003.U -> Cat(frm, fflags).pad(p.xlen)) else Nil) ++
        (if (lower) Seq(0x306.U -> mcounteren.pad(p.xlen)) else Nil) ++
        (if (p.withSupervisor) Seq(0x302.U -> medeleg.pad(p.xlen), 0x303.U -> mideleg.pad(p.xlen),
            0x100.U -> (mstatus & sstatusMask.U(p.xlen.W)), 0x104.U -> (mie & mideleg & (if (p.withH) 0x222.U(12.W) else 0xfff.U(12.W))).pad(p.xlen),
            0x105.U -> stvec, 0x106.U -> scounteren.pad(p.xlen), 0x140.U -> sscratch, 0x141.U -> sepc,
            0x142.U -> scause, 0x143.U -> stval, 0x144.U -> (mip & mideleg & (if (p.withH) 0x222.U(12.W) else 0xfff.U(12.W))).pad(p.xlen), 0x180.U -> satp)
        else Nil) ++ (if (p.withAia) Seq(
            0x350.U -> aiaSelectors.get(0).pad(p.xlen), 0x150.U -> aiaSelectors.get(1).pad(p.xlen),
            // Indirect data is supplied by the sole committed WB transaction, never by EX.
            0x351.U -> 0.U(p.xlen.W), 0x151.U -> 0.U(p.xlen.W),
            0x35c.U -> 0.U(p.xlen.W), 0x15c.U -> 0.U(p.xlen.W)) else Nil) ++
        (if (p.withH) Seq(0x30a.U -> 0.U(p.xlen.W), 0x10a.U -> 0.U(p.xlen.W)) else Nil) ++
        pmpPairs ++ (if (p.xlen == 32) Seq(0xb80.U -> cycles(63, 32),
            0xb82.U -> instructions(63, 32), 0xc80.U -> cycles(63, 32),
            0xc81.U -> io.time(63, 32), 0xc82.U -> instructions(63, 32)) else Nil)
    val counter = io.readAddress >= "hc00".U && io.readAddress <= "hc02".U ||
        (p.xlen == 32).B && io.readAddress >= "hc80".U && io.readAddress <= "hc82".U
    val counterIndex = io.readAddress(1, 0)
    val counterLegal = !counter || privilege === 3.U ||
        (mcounteren(counterIndex) && (privilege =/= 0.U || !p.withSupervisor.B || scounteren(counterIndex)))
    val ordinaryKnown = readPairs.map { case (address, _) => io.readAddress === address }.reduce(_ || _)
    val hypervisorKnown = hypervisor.map(_.io.readKnown).getOrElse(false.B)
    val privileged = Mux(hypervisorKnown && io.readAddress(9, 8) === 2.U,
        privilege === 3.U || (privilege === 1.U && !virtualized), privilege >= io.readAddress(9, 8))
    val guestCounterLegal = !virtualized || !counter ||
        hypervisor.map(_.io.counterEnable(counterIndex)).getOrElse(true.B)
    val guestSatpTrap = virtualized && io.readAddress === "h180".U &&
        hypervisor.map(_.io.vtvm).getOrElse(false.B)
    io.readLegal := (ordinaryKnown || hypervisorKnown) && privileged && counterLegal && guestCounterLegal &&
        !hypervisor.map(_.io.readVirtual).getOrElse(false.B) && !guestSatpTrap &&
        !(io.readAddress === "h180".U && privilege === 1.U && !virtualized && tvm) &&
        !(io.readAddress === "h680".U && privilege === 1.U && tvm) &&
        !(io.readAddress >= 1.U && io.readAddress <= 3.U && !io.fpEnabled)
    io.hypervisor.foreach(_.csrVirtual := hypervisor.get.io.readVirtual || guestSatpTrap ||
        virtualized && counter && mcounteren(counterIndex) &&
            (!hypervisor.get.io.counterEnable(counterIndex) || privilege === 0.U && !scounteren(counterIndex)) ||
        virtualized && privilege === 0.U && ordinaryKnown && io.readAddress(9, 8) === 1.U)
    io.readData := Mux(hypervisorKnown, hypervisor.map(_.io.readData).getOrElse(0.U),
        Mux1H(readPairs.map { case (address, value) => (io.readAddress === address) -> value }))
    // CSRRS/CSRRC mip.SEIP modifies ONLY the software latch, never the OR'ed external signal.
    val softwareMip = (supervisorPending(0).asUInt << 1) | (supervisorPending(1).asUInt << 5) |
        (supervisorPending(2).asUInt << 9) |
        (hypervisor.map(_.io.virtualPending).getOrElse(0.U) & 4.U)
    io.readDataForWrite := Mux(hypervisorKnown, hypervisor.map(_.io.readDataForWrite).getOrElse(0.U),
        Mux(io.readAddress === "h344".U, softwareMip, io.readData))
    val pmpWrite = io.write.bits.address >= "h3a0".U && io.write.bits.address <= "h3bf".U
    val mapWrite = io.write.bits.address === "h180".U || (p.withH.B &&
        (io.write.bits.address === "h280".U || io.write.bits.address === "h680".U)) ||
        (p.pmpEntries > 0).B && pmpWrite
    def alignedEpc(value: UInt): UInt = {
        val bits = if (p.withC) 1 else 2
        Cat(value(p.xlen - 1, bits), 0.U(bits.W))
    }
    io.contextBarrier := io.write.valid && (mapWrite || io.write.bits.address === "h300".U ||
        io.write.bits.address === "h100".U || (p.withH.B &&
            (io.write.bits.address === "h200".U || io.write.bits.address === "h600".U)))
    io.invalidateTranslation := io.sfence || (io.write.valid && mapWrite)
    when(hostWrite) {
        val data = io.write.bits.data
        if (p.withAia) {
            when(io.write.bits.address === "h350".U) { aiaSelectors.get(0) := data(11, 0) }
            when(io.write.bits.address === "h150".U) { aiaSelectors.get(1) := data(11, 0) }
        }
        if (p.spinor) when(io.write.bits.address === "h300".U ||
            (p.withSupervisor.B && io.write.bits.address === "h100".U)) { vs.get := data(10, 9) }
        if (p.withF) {
            when(io.write.bits.address === "h300".U || (p.withSupervisor.B && io.write.bits.address === "h100".U)) {
                fs := data(14, 13)
            }
            when(io.write.bits.address >= 1.U && io.write.bits.address <= 3.U && fs =/= 0.U) {
                fs := 3.U
                when(io.write.bits.address =/= 2.U) { fflags := data(4, 0) }
                when(io.write.bits.address =/= 1.U) {
                    frm := Mux(io.write.bits.address === 2.U, data(2, 0), data(7, 5))
                }
            }
        }
        switch(io.write.bits.address) {
            is(0x300.U) {
                mieGlobal := data(3); mpie := data(7)
                if (lower) {
                    mpp := Mux(data(12, 11) === 3.U, 3.U,
                        Mux(p.withSupervisor.B && data(12, 11) === 1.U, 1.U, 0.U))
                    tw := data(21)
                }
                if (p.withUser) mprv := data(17)
                if (p.withSupervisor) {
                    sieGlobal := data(1); spie := data(5); spp := data(8)
                    sum := data(18); mxr := data(19); tsr := data(22)
                }
                if (p.withSv39) tvm := data(20)
            }
            is(0x304.U) { mie := data(11, 0) & (if (p.withH) "heee".U else if (p.withSupervisor) "haaa".U else "h888".U) }
            is(0x305.U) { mtvec := Cat(data(p.xlen - 1, 2), 0.U(1.W), data(1, 0) === 1.U) }
            is(0x320.U) { inhibit := data(2, 0) & 5.U }
            is(0x340.U) { mscratch := data }
            is(0x341.U) { mepc := alignedEpc(data) }
            is(0x342.U) { mcause := data }
            is(0x343.U) { mtval := data }
            is(0xb00.U) { cycles := (if (p.xlen == 64) data else Cat(cycles(63, 32), data)) }
            is(0xb02.U) { instructions := (if (p.xlen == 64) data else Cat(instructions(63, 32), data)) }
        }
        if (lower) when(io.write.bits.address === "h306".U) { mcounteren := data(2, 0) }
        if (p.withSupervisor) {
            switch(io.write.bits.address) {
                is(0x302.U) { medeleg := (if (p.withH) data(31, 0) & "hf0b7ff".U else data(15, 0) & "hb3ff".U) }
                is(0x303.U) { midelegStorage := data(11, 0) & "h222".U }
                is(0x100.U) {
                    sieGlobal := data(1); spie := data(5); spp := data(8); sum := data(18); mxr := data(19)
                }
                is(0x104.U) {
                    val mask = mideleg & (if (p.withH) 0x222.U(12.W) else 0xfff.U(12.W))
                    mie := (mie & ~mask) | (data(11, 0) & mask)
                }
                is(0x105.U) { stvec := Cat(data(p.xlen - 1, 2), 0.U(1.W), data(1, 0) === 1.U) }
                is(0x106.U) { scounteren := data(2, 0) }
                is(0x140.U) { sscratch := data }
                is(0x141.U) { sepc := alignedEpc(data) }
                is(0x142.U) { scause := data }
                is(0x143.U) { stval := data }
                is(0x144.U) { when(mideleg(1)) { supervisorPending := Cat(supervisorPending(2, 1), data(1)) } }
                is(0x344.U) { supervisorPending := Cat(data(9), data(5), data(1)) }
            }
        }
        if (p.withSv39) when(io.write.bits.address === "h180".U && (data(63, 60) === 0.U || data(63, 60) === 8.U)) {
            satp := Mux(data(63, 60) === 8.U, Cat(8.U(4.W), 0.U((64 - p.physicalBits + 8).W),
                data(p.physicalBits - 13, 0)), 0.U)
        }
        if (p.xlen == 32) {
            when(io.write.bits.address === 0xb80.U) { cycles := Cat(data, cycles(31, 0)) }
            when(io.write.bits.address === 0xb82.U) { instructions := Cat(data, instructions(31, 0)) }
        }
        for (i <- 0 until p.pmpEntries) {
            val group = i / (p.xlen / 8)
            val byte = i % (p.xlen / 8)
            when(io.write.bits.address === (0x3a0 + group * (if (p.xlen == 64) 2 else 1)).U && !pmpConfig(i)(7)) {
                val cfg = data(8 * byte + 7, 8 * byte)
                // Reserved W=1/R=0 is WARL to W=0; bits 6:5 are always zero.
                pmpConfigNext(i) := Cat(cfg(7), 0.U(2.W), cfg(4, 3), cfg(2), cfg(1) && cfg(0), cfg(0))
            }
            val nextTorLocked = if (i + 1 < p.pmpEntries)
                pmpConfig(i + 1)(7) && pmpConfig(i + 1)(4, 3) === 1.U else false.B
            when(io.write.bits.address === (0x3b0 + i).U && !pmpConfig(i)(7) && !nextTorLocked) {
                pmpAddressNext(i) := data(p.physicalBits - 3, 0)
            }
        }
    }
    hypervisor.foreach { h =>
        when(io.write.valid && io.write.bits.address === "h604".U) {
            mie := (mie & ~0x444.U(12.W)) | (io.write.bits.data(11, 0) & 0x444.U)
        }
        when(h.io.guestIeWrite.valid) { mie := (mie & ~h.io.hideleg) | h.io.guestIeWrite.bits }
    }
    // Balanced trailing-one prefix replaces raw+1/xor/mask+1/lower+size chains.
    // Decode the new pmpaddr DATA once and route registered ranges to its one unlocked owner.
    val rawPmpData = io.write.bits.data(p.physicalBits - 3, 0)
    val prefix = VecInit((0 until p.physicalBits - 2).map(i => rawPmpData(i, 0).andR)).asUInt
    val napotMask = Cat(prefix, 7.U(3.W))
    val pmpNormalData = (rawPmpData << 2).pad(p.physicalBits + 1)
    val napotLowerData = pmpNormalData & ~napotMask
    val napotUpperData = if (p.fpgaTimingCuts)
        I1TimingMath.incrementPowerOfTwo((pmpNormalData | napotMask).pad(p.physicalBits + 2), 0)
        else (pmpNormalData | napotMask) +& 1.U
    val napotUpperClipped = Mux(napotUpperData(p.physicalBits + 1, p.physicalBits).orR,
        (BigInt(1) << p.physicalBits).U((p.physicalBits + 1).W),
        napotUpperData(p.physicalBits, 0))
    val na4UpperData = (if (p.fpgaTimingCuts)
        I1TimingMath.incrementPowerOfTwo(rawPmpData.pad(p.physicalBits - 1), 0)
        else rawPmpData +& 1.U) << 2
    for (i <- 0 until p.pmpEntries) {
        val nextTorLocked = if (i + 1 < p.pmpEntries)
            pmpConfig(i + 1)(7) && pmpConfig(i + 1)(4, 3) === 1.U else false.B
        when(io.write.valid && pmpWrite) { pmpConfig(i) := pmpConfigNext(i); pmpAddress(i) := pmpAddressNext(i) }
        when(io.write.valid && io.write.bits.address === (0x3b0 + i).U && !pmpConfig(i)(7) && !nextTorLocked) {
            pmpNapotLower(i) := napotLowerData; pmpNapotUpper(i) := napotUpperClipped
            pmpNa4Upper(i) := na4UpperData
        }
        if (p.fpgaTimingCuts) when(io.write.valid && pmpWrite) {
            val changed = io.write.bits.address === (0x3b0 + i).U &&
                !pmpConfig(i)(7) && !nextTorLocked
            val mode = pmpConfigNext(i)(4, 3)
            val normal = (pmpAddressNext(i) << 2).pad(p.physicalBits + 1)
            val previous = if (i == 0) 0.U((p.physicalBits + 1).W)
                else (pmpAddressNext(i - 1) << 2).pad(p.physicalBits + 1)
            val napotLower = Mux(changed, napotLowerData, pmpNapotLower(i))
            val napotUpper = Mux(changed, napotUpperClipped, pmpNapotUpper(i))
            val na4Upper = Mux(changed, na4UpperData, pmpNa4Upper(i))
            effectiveLower.get(i) := Mux(mode === 1.U, previous, Mux(mode === 2.U, normal, napotLower))
            effectiveUpper.get(i) := Mux(mode === 1.U, normal, Mux(mode === 2.U, na4Upper, napotUpper))
        }
    }
    when(io.mret) {
        mieGlobal := mpie; mpie := true.B
        if (lower) { privilege := mpp; mpp := 0.U }
        if (p.withUser) when(mpp =/= 3.U) { mprv := false.B }
    }
    if (p.withSupervisor) when(io.sret) {
        when(virtualized) { privilege := hypervisor.map(_.io.guestReturnPrivilege).getOrElse(0.U) }
            .otherwise {
                privilege := Mux(spp, 1.U, 0.U); spp := false.B
                sieGlobal := spie; spie := true.B
            }
        mprv := false.B
    }
    when(io.trap.valid) {
        when(guestTrap) { if (p.withSupervisor) privilege := 1.U }
        .elsewhen(delegated) {
            if (p.withSupervisor) {
                sepc := alignedEpc(io.trap.bits.pc)
                scause := io.trap.bits.cause; stval := io.trap.bits.tval
                spp := privilege === 1.U; spie := sieGlobal; sieGlobal := false.B; privilege := 1.U
            }
        }.otherwise {
            mepc := alignedEpc(io.trap.bits.pc)
            mcause := io.trap.bits.cause; mtval := io.trap.bits.tval; mpie := mieGlobal; mieGlobal := false.B
            if (lower) { mpp := privilege; privilege := 3.U }
        }
    }
    when(!reset.asBool) {
        assert(!io.write.valid || privilege >= io.write.bits.address(9, 8) ||
            (p.withH.B && privilege === 1.U && !virtualized && io.write.bits.address(9, 8) === 2.U), "unqualified privileged CSR commit")
        assert(!io.mret || io.mretLegal, "illegal MRET committed")
        assert(!io.sret || io.sretLegal, "illegal SRET committed")
    }
}
