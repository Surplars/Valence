package soc.core.ooo

import chisel3._
import chisel3.util._
import soc.ip.interrupt.ImsicCsrRequest
import soc.ip.bus.RegisterResponse

class SystemRequest(p: OooParams) extends Bundle {
    val token       = new RobToken(p)
    val pc          = UInt(64.W)
    val instruction = UInt(32.W)
    val operand     = UInt(64.W)
    val operand2 = if (p.hypervisorExperiment) Some(UInt(64.W)) else None
}
class SystemResult(p: OooParams) extends Bundle {
    val completion = new BackendCompletion(p)
    val redirect   = Bool()
    val invalidateFetch = Bool()
}
class MachineCsrPort extends Bundle {
    val request  = Decoupled(new ImsicCsrRequest)
    val response = Flipped(Decoupled(new RegisterResponse))
}
class VmCsrState extends Bundle {
    val satp = UInt(64.W)
    val sum  = Bool()
    val mxr  = Bool()
    val dataPrivilege = UInt(2.W)
}

/** One irrevocable, ROB-head-authorized system transaction. Capacity one.
  * Capture the complete command before CSR/FP decoding; minimum completion
  * latency is two cycles, with no speculative CSR state or rollback copy.
  */
class MachineSystemUnit(p: OooParams, experimentalHypervisor: Boolean = false,
    guestFiles: Int = 0) extends Module {
    require(!experimentalHypervisor || p.virtualMemoryLevels >= 3,
        "experimental H state requires a supervisor translation configuration")
    require(experimentalHypervisor || guestFiles == 0)
    require(experimentalHypervisor == p.hypervisorExperiment, "H state and precise metadata must be enabled together")
    require(!experimentalHypervisor || !p.fpEnabled, "guest FP state is not yet integrated")
    private def alignedEpc(value: UInt): UInt =
        if (p.compressedInstructions) Cat(value(63, 1), 0.U(1.W)) else Cat(value(63, 2), 0.U(2.W))
    val io = IO(new Bundle {
        val guestExternal = if (experimentalHypervisor)
            Some(Input(UInt(math.max(1, guestFiles).W))) else None
        val virtualized = if (experimentalHypervisor) Some(Output(Bool())) else None
        val guestTopIdentities = if (experimentalHypervisor) Some(Input(UInt(math.max(1, guestFiles * 11).W))) else None
        val guestDataContext = if (p.hypervisorExperiment) Some(Output(new GuestTranslationRequest)) else None
        val guestFetchContext = if (p.hypervisorExperiment) Some(Output(new GuestTranslationRequest)) else None
        val hMemory = if (p.hypervisorExperiment) Some(new DataPort) else None
        val hMemoryFault = if (p.hypervisorExperiment) Some(Input(new GuestFaultMetadata)) else None
        val hMemoryBusy = if (p.hypervisorExperiment) Some(Output(Bool())) else None
        val start                       = Flipped(Decoupled(new SystemRequest(p)))
        val complete                    = Decoupled(new SystemResult(p))
        val imsic                       = new MachineCsrPort
        val trap                        = Input(Valid(new HeadException(p)))
        val trapReady                   = Output(Bool())
        val fpRetire = if (p.fpEnabled) Some(Input(Valid(new RobToken(p)))) else None
        val fpMemory = if (p.fpEnabled) Some(new DataPort) else None
        val fpMemoryBusy = if (p.fpEnabled) Some(Output(Bool())) else None
        val trapTarget                  = Output(UInt(64.W))
        val externalInterrupt           = Input(Bool())
        val supervisorExternalInterrupt = Input(Bool())
        val timerInterrupt              = Input(Bool())
        val timeValue                   = Input(UInt(64.W))
        val interruptCause              = Output(UInt((if (experimentalHypervisor) 6 else 4).W))
        val interruptPending            = Output(Bool())
        val fetchPrivilege              = Output(UInt(2.W))
        val dataPrivilege               = Output(UInt(2.W))
        val pmpState                    = Output(new PmpState)
        val pmpRawChanged = if (p.pmpChangePublicationEnabled) Some(Output(Bool())) else None
        val vmState                     = if (p.virtualMemoryLevels > 0) Some(Output(new VmCsrState)) else None
        val vmFlush                     = if (p.virtualMemoryLevels > 0) Some(Output(Bool())) else None
        val vmFlushReady                = if (p.virtualMemoryLevels > 0) Some(Input(Bool())) else None
        val fenceIFlush                 = Output(Bool())
        val fenceIFlushReady            = Input(Bool())
    })
    private val systemStates = Enum(if (p.hypervisorExperiment) 9 else 8)
    val Seq(idle, execute, send, waitResponse, waitVmFlush, waitFenceI, waitFp, finish) = systemStates.take(8)
    val waitHMemory = if (p.hypervisorExperiment) systemStates(8) else idle
    val floatingPoint = if (p.fpEnabled) Some(Module(new FloatingPointSystem(p))) else None
    val fpFs = floatingPoint.map(_.io.fs).getOrElse(0.U(2.W))
    val fpFcsr = floatingPoint.map(_.io.fcsr).getOrElse(0.U(8.W))
    val fpStatus = (fpFs << 13) | ((fpFs === 3.U).asUInt << 63)
    val state                                         = RegInit(idle)
    val request                                       = Reg(new SystemRequest(p))
    val result                                        = RegInit(0.U.asTypeOf(new SystemResult(p)))
    val external                                      = RegInit(0.U.asTypeOf(new ImsicCsrRequest))
    val privilege                                     = RegInit(3.U(2.W))
    val hLsu = if (p.hypervisorExperiment) Some(Module(new LoadStoreUnit(p))) else None
    val hypervisor = if (experimentalHypervisor)
        Some(Module(new HypervisorState(p.compressedInstructions, guestFiles))) else None
    val virtualized = hypervisor.map(_.io.virtualized).getOrElse(false.B)
    io.virtualized.foreach(_ := virtualized)
    val mie                                           = RegInit(false.B)
    val mtie                                          = RegInit(false.B)
    val meie                                          = RegInit(false.B)
    val seie                                          = RegInit(false.B)
    val seipSoftware                                  = RegInit(false.B)
    val supervisorExternalPending = io.supervisorExternalInterrupt || seipSoftware
    val ssie                                          = RegInit(false.B)
    val stie                                          = RegInit(false.B)
    val ssip                                          = RegInit(false.B)
    val stipSoftware                                  = RegInit(false.B)
    val stimecmp                                      = RegInit("hffffffffffffffff".U(64.W))
    val stce                                          = RegInit(false.B)
    val mcounterenTm                                  = RegInit(false.B)
    val scounterenTm                                  = RegInit(false.B)
    val mpie                                          = RegInit(false.B)
    val mpp                                           = RegInit(0.U(2.W))
    val mprv                                          = RegInit(false.B)
    val sum                                           = RegInit(false.B)
    val mxr                                           = RegInit(false.B)
    val satp                                          = RegInit(0.U(64.W))
    val pmpCfg                                        = RegInit(VecInit(Seq.fill(16)(0.U(8.W))))
    val pmpAddr                                       = RegInit(VecInit(Seq.fill(16)(0.U(54.W))))
    // OFF retains the original direct register writes and live range decoder.
    // ON sends the exact same filtered writes to the next-state decoder so raw
    // CSR state and derived bounds publish at one edge, with no request stage.
    val pmpCfgWrite = if (p.registeredPmpRegions) WireDefault(pmpCfg) else pmpCfg
    val pmpAddrWrite = if (p.registeredPmpRegions) WireDefault(pmpAddr) else pmpAddr
    val pmpRegionWrite = if (p.registeredPmpRegions)
        Some(WireDefault(VecInit(Seq.fill(p.pmpEntries)(false.B)))) else None
    // Publish after the same edge as the raw CSR bank. This is an every-cycle
    // level, not a handshaken pulse: consecutive changes remain high, and every
    // non-changing edge clears it. The adapter shares this clock and reset.
    val pmpRawChangeWrite = if (p.pmpChangePublicationEnabled) Some(WireDefault(false.B)) else None
    io.pmpRawChanged.foreach(_ := RegNext(pmpRawChangeWrite.get, false.B))
    val sie                                           = RegInit(false.B)
    val spie                                          = RegInit(false.B)
    val spp                                           = RegInit(false.B)
    val medeleg                                       = RegInit(0.U(64.W))
    val seideleg                                      = RegInit(false.B)
    val ssideleg                                      = RegInit(false.B)
    val stideleg                                      = RegInit(false.B)
    val stvec                                         = RegInit(0.U(64.W))
    val sepc                                          = RegInit(0.U(64.W))
    val scause                                        = RegInit(0.U(64.W))
    val stval                                         = RegInit(0.U(64.W))
    val sscratch                                      = RegInit(0.U(64.W))
    val mtvec                                         = RegInit(0.U(64.W))
    val mepc                                          = RegInit(0.U(64.W))
    val mcause                                        = RegInit(0.U(64.W))
    val mtval                                         = RegInit(0.U(64.W))
    val mscratch                                      = RegInit(0.U(64.W))
    val miselect                                      = RegInit(0.U(12.W))
    val siselect                                      = RegInit(0.U(12.W))
    hypervisor.foreach { h =>
        h.io.privilege := privilege; h.io.mpp := mpp; h.io.mprv := mprv
        h.io.hsGlobalEnable := sie; h.io.time := io.timeValue; h.io.machineStce := stce
        h.io.guestExternal := io.guestExternal.get
        h.io.readAddress := request.instruction(31, 20)
        h.io.write.valid := false.B
        h.io.write.bits := 0.U.asTypeOf(h.io.write.bits)
        h.io.mret := false.B; h.io.sret := false.B
        h.io.trap.valid := io.trap.valid
        h.io.trap.bits.pc := io.trap.bits.pc
        h.io.trap.bits.cause := io.trap.bits.cause
        h.io.trap.bits.tval := io.trap.bits.tval
        val addressCause = Seq(0, 1, 3, 4, 5, 6, 7, 12, 13, 15, 20, 21, 23)
            .map(c => io.trap.bits.cause === c.U).reduce(_ || _)
        h.io.trap.bits.guestAddress := io.trap.bits.guestFault.get.guestAddress || (virtualized && addressCause)
        h.io.trap.bits.guestPhysicalAddress := io.trap.bits.guestFault.get.guestPhysicalAddress
        h.io.trap.bits.implicitPte := io.trap.bits.guestFault.get.implicitPte
    }
    val guestEpoch = if (p.hypervisorExperiment) Some(RegInit(0.U(8.W))) else None
    guestEpoch.foreach { epoch =>
        when(io.trap.valid || (state === execute)) { epoch := epoch + 1.U }
    }
    for ((context, isFetch) <- Seq(io.guestDataContext -> false, io.guestFetchContext -> true); output <- context) {
        val h = hypervisor.get
        output := 0.U.asTypeOf(new GuestTranslationRequest)
        output.virtualized := (if (isFetch) virtualized else h.io.dataVirtualized)
        output.vsatp := Mux(output.virtualized, h.io.vsatp, satp)
        output.hgatp := h.io.hgatp
        output.effectivePrivilege := (if (isFetch) privilege else Mux(privilege === 3.U && mprv, mpp, privilege))
        output.vsSum := Mux(output.virtualized, h.io.vsSum, sum)
        output.vsMxr := Mux(output.virtualized, h.io.vsMxr, mxr)
        output.hsMxr := mxr
        output.access := (if (isFetch) PmpAccess.execute else PmpAccess.read)
        output.size := 2.U
        output.epoch := guestEpoch.get
        if (!isFetch) {
            when(HypervisorInstruction.memory(request.instruction) && state =/= idle) {
                output.virtualized := true.B
                output.vsatp := h.io.vsatp
                output.effectivePrivilege := Mux(h.io.spvp, 1.U, 0.U)
                output.vsSum := h.io.vsSum
                output.vsMxr := h.io.vsMxr
                output.forceExecute := HypervisorInstruction.load(request.instruction) && request.instruction(24, 20) === 3.U
            }
        }
    }
    val mstatus                                       = "h0000000a00000000".U(64.W) | fpStatus | (mprv.asUInt << 17) |
        (sum.asUInt << 18) | (mxr.asUInt << 19) |
        hypervisor.map(_.io.machineStatus).getOrElse(0.U(64.W)) |
        (mpp << 11) | (spp.asUInt << 8) |
        (mpie.asUInt << 7) | (spie.asUInt << 5) | (mie.asUInt << 3) | (sie.asUInt << 1)
    val misa = p.misaValue.U(64.W)
    val sstatus              = "h0000000200000000".U(64.W) | fpStatus | (sum.asUInt << 18) | (mxr.asUInt << 19) |
        (spp.asUInt << 8) | (spie.asUInt << 5) | (sie.asUInt << 1)
    io.vmState.foreach { state =>
        state.satp := satp
        state.sum := sum
        state.mxr := mxr
        state.dataPrivilege := io.dataPrivilege
    }
    io.vmFlush.foreach(_ := state === waitVmFlush)
    io.fenceIFlush := state === waitFenceI
    io.fetchPrivilege := privilege
    io.dataPrivilege  := Mux(privilege === 3.U && mprv, mpp, privilege)
    for (i <- 0 until 16) {
        io.pmpState.cfg(i)  := pmpCfg(i)
        io.pmpState.addr(i) := pmpAddr(i)
    }
    if (p.registeredPmpRegions) {
        val nextPmpState = Wire(new PmpState)
        nextPmpState.cfg := pmpCfgWrite
        nextPmpState.addr := pmpAddrWrite
        PmpState.decodeRegions(nextPmpState)
        pmpCfg := pmpCfgWrite
        pmpAddr := pmpAddrWrite
        for (i <- 0 until p.pmpEntries) {
            // OFF with raw address zero decodes to low 0/end 7/inactive.
            // Retain all 65 end bits, including inactive TOR top-zero underflow.
            val regionLow = RegInit(0.U(65.W)).suggestName(s"pmpRegionLow_$i")
            val regionEnd = RegInit(7.U(65.W)).suggestName(s"pmpRegionEnd_$i")
            val regionActive = RegInit(false.B).suggestName(s"pmpRegionActive_$i")
            when(pmpRegionWrite.get(i)) {
                regionLow := nextPmpState.regionLow(i)
                regionEnd := nextPmpState.regionEnd(i)
                regionActive := nextPmpState.regionActive(i)
            }
            io.pmpState.regionLow(i) := regionLow
            io.pmpState.regionEnd(i) := regionEnd
            io.pmpState.regionActive(i) := regionActive
        }
        for (i <- p.pmpEntries until 16) {
            io.pmpState.regionLow(i) := 0.U
            io.pmpState.regionEnd(i) := 7.U
            io.pmpState.regionActive(i) := false.B
        }
    } else {
        PmpState.decodeRegions(io.pmpState)
    }
    val machineGlobalEnable  = privilege =/= 3.U || mie
    val supervisorGlobalEnable = privilege === 0.U || (privilege === 1.U && (virtualized || sie))
    val machineExternalReady = io.externalInterrupt && meie && machineGlobalEnable
    val machineTimerReady    = io.timerInterrupt && mtie && machineGlobalEnable
    // Register the wide timer comparison before it enters interrupt arbitration.
    val stipHardware = RegNext(io.timeValue >= stimecmp, false.B)
    val stip         = Mux(stce, stipHardware, stipSoftware)
    val supervisorExternalReady = supervisorExternalPending && seie && Mux(
        seideleg,
        supervisorGlobalEnable,
        machineGlobalEnable
    )
    val supervisorSoftwareReady = ssip && ssie && Mux(
        ssideleg,
        supervisorGlobalEnable,
        machineGlobalEnable
    )
    val supervisorTimerReady = stip && stie && Mux(
        stideleg,
        supervisorGlobalEnable,
        machineGlobalEnable
    )
    val rawMie = (meie.asUInt << 11) | (seie.asUInt << 9) | (mtie.asUInt << 7) |
        (stie.asUInt << 5) | (ssie.asUInt << 1) | hypervisor.map(_.io.mieBits).getOrElse(0.U)
    val rawMip = (io.externalInterrupt.asUInt << 11) | (supervisorExternalPending.asUInt << 9) |
        (io.timerInterrupt.asUInt << 7) | (stip.asUInt << 5) | (ssip.asUInt << 1) |
        hypervisor.map(_.io.mipBits).getOrElse(0.U)
    val rawMideleg = (seideleg.asUInt << 9) | (stideleg.asUInt << 5) | (ssideleg.asUInt << 1) |
        (if (experimentalHypervisor) (if (guestFiles > 0) 0x1444 else 0x444).U else 0.U)
    val aia = Module(new AiaHartControl)
    aia.io.mCandidates := rawMip & rawMie & ~rawMideleg
    aia.io.hsCandidates := rawMip & rawMie & rawMideleg &
        ~hypervisor.map(_.io.hideleg).getOrElse(0.U(64.W))
    aia.io.vsip := hypervisor.map(_.io.vsip).getOrElse(0.U)
    aia.io.vsie := hypervisor.map(_.io.vsie).getOrElse(0.U)
    aia.io.vgein := hypervisor.map(_.io.vgein).getOrElse(0.U)
    aia.io.guestFileValid := (guestFiles > 0).B && aia.io.vgein =/= 0.U && aia.io.vgein <= guestFiles.U
    val selectedIdentity = if (experimentalHypervisor && guestFiles > 0)
        (io.guestTopIdentities.get >> ((aia.io.vgein - 1.U) * 11.U))(10, 0) else 0.U(11.W)
    aia.io.guestTopei := Mux(aia.io.guestFileValid, (selectedIdentity << 16) | selectedIdentity, 0.U)
    aia.io.commit := true.B
    aia.io.hvictlWrite.valid := false.B; aia.io.hvictlWrite.bits := 0.U
    val machinePending = aia.io.mtopi.orR && machineGlobalEnable
    val hostPending = aia.io.stopi.orR && supervisorGlobalEnable
    val guestPending = aia.io.vstopi.orR && virtualized && (privilege === 0.U ||
        (privilege === 1.U && hypervisor.map(_.io.vsGlobalEnable).getOrElse(false.B)))
    val nominatedGuest = guestPending && !machinePending && !hostPending
    val guestIid = aia.io.vstopi(21, 16)
    // Standard VS IDs are converted back to raw H trap numbering for the common
    // ROB interface. HVCTL-injected other identities retain their six-bit number.
    val rawGuestIid = Mux(guestIid === 1.U || guestIid === 5.U || guestIid === 9.U, guestIid + 1.U, guestIid)
    io.interruptPending := machinePending || hostPending || guestPending
    io.interruptCause := Mux(machinePending, aia.io.mtopi(21, 16),
        Mux(hostPending, aia.io.stopi(21, 16), rawGuestIid))
    hypervisor.foreach { h =>
        h.io.nominatedGuestInterrupt := io.trap.bits.cause(63) && nominatedGuest &&
            io.trap.bits.cause(62, 0) === rawGuestIid
        h.io.nominatedGuestCause := guestIid
    }
    val delegated = privilege =/= 3.U && Mux(
        io.trap.bits.cause(63),
        (io.trap.bits.cause(62, 0) === 9.U && seideleg) ||
            (io.trap.bits.cause(62, 0) === 1.U && ssideleg) ||
            (io.trap.bits.cause(62, 0) === 5.U && stideleg) ||
            (experimentalHypervisor.B && (io.trap.bits.cause(62, 0) === 2.U ||
                io.trap.bits.cause(62, 0) === 6.U || io.trap.bits.cause(62, 0) === 10.U ||
                (guestFiles > 0).B && io.trap.bits.cause(62, 0) === 12.U)),
        io.trap.bits.cause(62, 6) === 0.U && medeleg(io.trap.bits.cause(5, 0))
    )
    hypervisor.foreach(_.io.delegated := delegated)
    val guestTrap = hypervisor.map(_.io.guestTrap).getOrElse(false.B)
    val trapVector = Mux(delegated, stvec, mtvec)
    val hostTrapTarget = (trapVector & "hfffffffffffffffc".U) + Mux(
        io.trap.bits.cause(63) && trapVector(1, 0) === 1.U,
        (if (experimentalHypervisor) io.trap.bits.cause(5, 0) else io.trap.bits.cause(3, 0)) << 2,
        0.U
    )
    io.trapTarget := Mux(guestTrap, hypervisor.map(_.io.guestTrapPc).getOrElse(0.U), hostTrapTarget)
    io.start.ready          := state === idle && !floatingPoint.map(_.io.busy).getOrElse(false.B)
    when(io.start.fire) {
        assert(!io.trap.valid, "trap cannot also authorize a new system command")
        request := io.start.bits
        state := execute
    }
    // A faulted FP command stays busy until its precise trap. Trap admission must
    // not depend on new-command credit, or that exception would deadlock.
    io.trapReady := state === idle
    io.complete.valid       := state === finish
    io.complete.bits        := result
    io.imsic.request.valid  := state === send
    io.imsic.request.bits   := external
    io.imsic.response.ready := state === waitResponse
    when(io.complete.fire) { state := idle }
    when(io.imsic.request.fire) { state := waitResponse }
    when(io.imsic.response.fire) {
        result.completion.data      := io.imsic.response.bits.data
        result.completion.exception := io.imsic.response.bits.error
        state                       := finish
    }
    if (p.virtualMemoryLevels > 0) {
        when(state === waitVmFlush && io.vmFlushReady.get) { state := finish }
    }
    when(state === waitFenceI && io.fenceIFlushReady) { state := finish }
    val inst            = request.instruction
    val address         = inst(31, 20)
    val csr             = inst(6, 0) === "h73".U && inst(14, 12) =/= 0.U && inst(14, 12) =/= 4.U
    val operation       = inst(13, 12)
    val source          = Mux(inst(14), Cat(0.U(59.W), inst(19, 15)), request.operand)
    val write           = operation === 1.U || inst(19, 15) =/= 0.U
    val read            = operation =/= 1.U || inst(11, 7) =/= 0.U
    val guestImsic = experimentalHypervisor.B && (address === "h251".U || address === "h25c".U ||
        virtualized && (address === "h151".U || address === "h15c".U))
    val imsic = address === "h351".U || address === "h35c".U || address === "h151".U || address === "h15c".U || guestImsic
    val supervisorImsic = address === "h151".U || address === "h15c".U
    val hostReadValue       = MuxLookup(address, 0.U(64.W))(
        Seq(
            "h300".U -> mstatus,
            "h301".U -> misa,
            "h302".U -> medeleg,
            "h303".U -> ((seideleg.asUInt << 9) | (stideleg.asUInt << 5) | (ssideleg.asUInt << 1) |
                (if (experimentalHypervisor) (if (guestFiles > 0) 0x1444 else 0x444).U else 0.U)),
            "h100".U -> sstatus,
            "h104".U -> (Mux(seideleg, seie.asUInt << 9, 0.U) | Mux(stideleg, stie.asUInt << 5, 0.U) |
                Mux(ssideleg, ssie.asUInt << 1, 0.U)),
            "h105".U -> stvec,
            "h140".U -> sscratch,
            "h141".U -> sepc,
            "h142".U -> scause,
            "h143".U -> stval,
            "h144".U -> (Mux(seideleg, supervisorExternalPending.asUInt << 9, 0.U) |
                Mux(stideleg, stip.asUInt << 5, 0.U) |
                Mux(ssideleg, ssip.asUInt << 1, 0.U)),
            "h14d".U -> stimecmp,
            "h106".U -> (scounterenTm.asUInt << 1),
            "h150".U -> siselect,
            "h305".U -> mtvec,
            "h304".U -> ((meie.asUInt << 11) | (seie.asUInt << 9) | (mtie.asUInt << 7) |
                (stie.asUInt << 5) | (ssie.asUInt << 1) | hypervisor.map(_.io.mieBits).getOrElse(0.U)),
            "h344".U -> ((io.externalInterrupt.asUInt << 11) | (supervisorExternalPending.asUInt << 9) |
                (io.timerInterrupt.asUInt << 7) | (stip.asUInt << 5) | (ssip.asUInt << 1) |
                hypervisor.map(_.io.mipBits).getOrElse(0.U)),
            "h306".U -> (mcounterenTm.asUInt << 1),
            "h30a".U -> (stce.asUInt << 63),
            "hc01".U -> Mux(virtualized, hypervisor.map(_.io.guestTime).getOrElse(io.timeValue), io.timeValue),
            "h340".U -> mscratch,
            "h341".U -> mepc,
            "h342".U -> mcause,
            "h343".U -> mtval,
            "h350".U -> miselect,
            "h308".U -> 0.U(64.W),
            "h309".U -> ((seipSoftware.asUInt << 9) | (Mux(stce, false.B, stipSoftware).asUInt << 5) | (ssip.asUInt << 1)),
            "hfb0".U -> aia.io.mtopi,
            "hdb0".U -> Mux(virtualized, aia.io.vstopi, aia.io.stopi)
        ) ++ (if (experimentalHypervisor) Seq(
            "h609".U -> aia.io.hvictl, "heb0".U -> aia.io.vstopi
        ) else Seq.empty) ++
        (if (p.fpEnabled) Seq(
            1.U -> fpFcsr(4, 0).pad(64), 2.U -> fpFcsr(7, 5).pad(64), 3.U -> fpFcsr.pad(64)
        ) else Seq.empty) ++
        (if (p.virtualMemoryLevels > 0) Seq("h180".U -> satp) else Seq.empty) ++
        (if (p.pmpEntries > 0) Seq(
            "h3a0".U -> Cat((0 until 8).reverse.map(pmpCfg(_))),
            "h3a2".U -> Cat((8 until 16).reverse.map(pmpCfg(_)))
        ) ++ (0 until p.pmpEntries).map(i => (0x3b0 + i).U -> Cat(0.U(10.W), pmpAddr(i))) else Seq.empty)
    )
    val readValue = Mux(hypervisor.map(_.io.readKnown).getOrElse(false.B),
        hypervisor.map(_.io.readData).getOrElse(0.U), hostReadValue)
    val hostExists = (Seq(0x308, 0x309, 0xfb0, 0xdb0,0x100, 0x104, 0x105, 0x106, 0x140, 0x141, 0x142, 0x143, 0x144, 0x14d, 0x150, 0x151, 0x15c,
        0x300, 0x301, 0x302, 0x303, 0x304, 0x305, 0x306, 0x30a, 0x340, 0x341, 0x342, 0x343, 0x344, 0x350,
        0x351, 0x35c, 0xc01, 0xf11, 0xf12, 0xf13, 0xf14) ++
        (if (experimentalHypervisor) Seq(0x609, 0xeb0) else Seq.empty) ++
        (if (p.fpEnabled) Seq(1, 2, 3) else Seq.empty) ++
        (if (p.virtualMemoryLevels > 0) Seq(0x180) else Seq.empty) ++
        (if (p.pmpEntries > 0) Seq(0x3a0, 0x3a2) ++ (0 until p.pmpEntries).map(0x3b0 + _) else Seq.empty))
        .map(a => address === a.U)
        .reduce(_ || _)
    val exists = hostExists || hypervisor.map(_.io.readKnown).getOrElse(false.B)
    val timeAccessAllowed = privilege === 3.U || (mcounterenTm && (privilege === 1.U || scounterenTm))
    val stimecmpAccessAllowed = privilege === 3.U || (stce && mcounterenTm)
    val timerCompareCsr = address === "h14d".U || address === "h24d".U
    val guestTimerAccessAllowed = hypervisor.map(h => h.io.stce && h.io.counterEnable(1)).getOrElse(false.B)
    // Compare CSRs must pass M qualification before any virtual-instruction classification.
    val virtualTimerCsr = virtualized && timerCompareCsr && stimecmpAccessAllowed &&
        (address === "h24d".U || privilege === 0.U || !guestTimerAccessAllowed)
    val fpCsr = address === 1.U || address === 2.U || address === 3.U
    val csrPrivilegeAllowed = privilege >= address(9, 8) ||
        (experimentalHypervisor.B && !virtualized && privilege === 1.U && address(9, 8) === 2.U)
    val selectedIndirect = Mux(guestImsic, hypervisor.map(_.io.vsiselect).getOrElse(0.U),
        Mux(supervisorImsic, siselect, miselect))
    val indirect = address === "h351".U || address === "h151".U || (experimentalHypervisor.B && address === "h251".U)
    val priorityWindow = indirect && selectedIndirect >= 0x30.U && selectedIndirect <= 0x3f.U
    val priorityIllegal = priorityWindow && (selectedIndirect(0) || guestImsic)
    // RV64 odd EIP/EIE selectors fault virtually in VS (AIA IMSIC 2.1.8.3/4).
    // Do not reclassify arbitrary IMSIC errors: other extension windows remain illegal.
    val oddImsicBitmap = indirect && selectedIndirect >= 0x80.U && selectedIndirect <= 0xff.U &&
        selectedIndirect(0)
    val virtualCsr = (hypervisor.map(_.io.virtualCsr).getOrElse(false.B) && !timerCompareCsr) ||
        (virtualized && exists && address(9, 8) === 2.U && !timerCompareCsr) ||
        (virtualized && guestImsic && (priorityWindow || oddImsicBitmap)) ||
        (virtualized && aia.io.vti && (address === 0x104.U || address === 0x144.U ||
            (address === 0x14d.U && write && stimecmpAccessAllowed))) ||
        (virtualized && exists && address(9, 8) === 1.U && privilege === 0.U &&
            (address =/= "h14d".U || stimecmpAccessAllowed)) ||
        (virtualized && address === "hc01".U && mcounterenTm &&
            (!hypervisor.map(_.io.counterEnable(1)).getOrElse(true.B) || (privilege === 0.U && !scounterenTm))) ||
        virtualTimerCsr ||
        (virtualized && guestImsic && hypervisor.map(_.io.vgein === 0.U).getOrElse(false.B))
    val hostTvmCsr = !virtualized && privilege === 1.U && (address === "h180".U || address === "h680".U) &&
        hypervisor.map(_.io.tvm).getOrElse(false.B)
    val invalidGuestFile = guestImsic && hypervisor.map(_.io.vgein === 0.U).getOrElse(false.B)
    val legalCsr = (!fpCsr || fpFs =/= 0.U) && exists && csrPrivilegeAllowed &&
        !(write && address(11, 10) === 3.U) && !virtualCsr && !hostTvmCsr && !invalidGuestFile && !priorityIllegal &&
        (address =/= "hc01".U || timeAccessAllowed) && (!timerCompareCsr || stimecmpAccessAllowed)
    // MIP.SEIP CSR RMW operates on the software bit, never latches the external wire.
    val readForWrite = Mux(address === "h344".U,
        (readValue & "hfffffffffffffdff".U) | (seipSoftware.asUInt << 9), readValue)
    val newValue = MuxLookup(operation, source)(Seq(2.U -> (readForWrite | source), 3.U -> (readForWrite & ~source)))
    val sfenceVma = inst(31, 25) === "b0001001".U && inst(14, 7) === 0.U && inst(6, 0) === "h73".U
    // Share each filtered, lock-qualified local comparison between fetch
    // permission invalidation and exact raw-image change publication. OFF-mode
    // address writes change the raw image even when no permission changes.
    // readValue is the exact selected raw pmpaddr for every pmpaddr CSR hit.
    val selectedPmpAddrChanged = readValue(53, 0) =/= newValue(53, 0)
    val pmpChanges = (0 until p.pmpEntries).map { i =>
        val cfgAddress = if (i < 8) "h3a0".U else "h3a2".U
        val raw = newValue(8 * (i % 8) + 7, 8 * (i % 8))
        val nextCfg = Cat(raw(7), 0.U(2.W), raw(4, 2), raw(1) && raw(0), raw(0))
        val nextTor = if (i + 1 < p.pmpEntries) pmpCfg(i + 1)(4, 3) === 1.U else false.B
        val nextTorLocked = if (i + 1 < p.pmpEntries) nextTor && pmpCfg(i + 1)(7) else false.B
        val cfgChanged = address === cfgAddress && !pmpCfg(i)(7) && nextCfg =/= pmpCfg(i)
        val addrChanged = address === (0x3b0 + i).U && !pmpCfg(i)(7) && !nextTorLocked &&
            selectedPmpAddrChanged
        (cfgChanged, addrChanged, pmpCfg(i)(4, 3) =/= 0.U || nextTor)
    }
    val pmpPermissionsChange = if (p.pmpEntries > 0)
        VecInit(pmpChanges.map { case (cfg, addr, active) => cfg || (addr && active) }).asUInt.orR else false.B
    val pmpRawStateChange = if (p.pmpChangePublicationEnabled)
        VecInit(pmpChanges.map { case (cfg, addr, _) => cfg || addr }).asUInt.orR else false.B
    floatingPoint.foreach { fp =>
        io.fpMemory.get <> fp.io.memory
        io.fpMemoryBusy.get := fp.io.memoryBusy
        fp.io.pmpState := io.pmpState
        fp.io.dataPrivilege := io.dataPrivilege
        fp.io.virtualized := (if (p.virtualMemoryLevels > 0)
            io.dataPrivilege =/= 3.U && satp(63, 60) =/= 0.U else false.B)
        fp.io.start.valid := state === execute && FloatingPointDecode.supported(inst, p.fpConfig)
        fp.io.start.bits := request
        fp.io.retire := io.fpRetire.get
        fp.io.trap := io.trap.valid
        fp.io.complete.ready := state === waitFp
        fp.io.csr.valid := state === execute && csr && legalCsr && fpCsr
        fp.io.csr.bits.address := address
        fp.io.csr.bits.operation := operation - 1.U
        fp.io.csr.bits.write := write
        fp.io.csr.bits.value := source
        fp.io.setFs.valid := state === execute && csr && legalCsr && write &&
            (address === "h300".U || address === "h100".U)
        fp.io.setFs.bits := newValue(14, 13)
        when(fp.io.start.valid) { assert(fp.io.start.ready, "FP head command credit") }
        when(fp.io.csr.valid) { assert(fp.io.csr.ready, "FP CSR serialization") }
        when(fp.io.setFs.valid) { assert(fp.io.setFs.ready, "FP context serialization") }
        when(fp.io.complete.fire) {
            result.completion := fp.io.complete.bits
            state := finish
        }
    }
    val hMemoryInstruction = experimentalHypervisor.B && HypervisorInstruction.memory(inst)
    val hFenceInstruction = experimentalHypervisor.B && HypervisorInstruction.fence(inst)
    val hMemoryAllowed = !virtualized && (privilege =/= 0.U || hypervisor.map(_.io.hu).getOrElse(false.B))
    val hFenceAllowed = !virtualized && privilege >= 1.U &&
        (!HypervisorInstruction.fenceGuest(inst) || privilege === 3.U || !hypervisor.map(_.io.tvm).getOrElse(false.B))
    hLsu.foreach { lsu =>
        lsu.io.memory <> io.hMemory.get
        lsu.io.guestFault.get := io.hMemoryFault.get
        io.hMemoryBusy.get := lsu.io.busy
        lsu.io.cancel := false.B
        lsu.io.fastStoreRetire := false.B; lsu.io.fastLoadRetire := false.B
        lsu.io.start.valid := state === execute && hMemoryInstruction && hMemoryAllowed
        lsu.io.start.bits := 0.U.asTypeOf(new MemoryOperation(p))
        lsu.io.start.bits.token := request.token
        lsu.io.start.bits.pc := request.pc
        lsu.io.start.bits.address := request.operand
        lsu.io.start.bits.data := request.operand2.get
        lsu.io.start.bits.virtualized := true.B
        lsu.io.start.bits.guestAddress.get := true.B
        lsu.io.start.bits.store := HypervisorInstruction.store(inst)
        lsu.io.start.bits.size := inst(27, 26)
        lsu.io.start.bits.unsigned := HypervisorInstruction.load(inst) && inst(24, 20) =/= 0.U
        lsu.io.complete.ready := state === waitHMemory
        when(lsu.io.start.valid) { assert(lsu.io.start.ready, "H memory head has exclusive LSU ownership") }
        when(lsu.io.complete.fire) {
            result.completion := lsu.io.complete.bits
            result.completion.guestFault.get.guestAddress := true.B
            state := finish
        }
    }
    when(state === execute) {
        state                    := finish
        result                   := 0.U.asTypeOf(new SystemResult(p))
        result.completion.token  := request.token
        result.completion.nextPc := request.pc + 4.U
        result.completion.cause  := 2.U
        result.completion.tval   := inst
        when(hMemoryInstruction) {
            result.completion.exception := !hMemoryAllowed
            result.completion.cause := Mux(virtualized, 22.U, 2.U)
            when(hMemoryAllowed) { state := waitHMemory }
        }.elsewhen(hFenceInstruction) {
            result.completion.exception := !hFenceAllowed
            result.completion.cause := Mux(virtualized, 22.U, 2.U)
            when(hFenceAllowed) {
                result.redirect := true.B; result.invalidateFetch := true.B; state := waitVmFlush
            }
        }.elsewhen(p.fpEnabled.B && FloatingPointDecode.supported(inst, p.fpConfig)) {
            state := waitFp
        }.elsewhen(inst(6, 0) === "h0f".U && (inst(14, 12) === 0.U || inst(14, 12) === 1.U)) {
            // The backend authorizes this full barrier only after older memory has drained.
            result.completion.data := 0.U
            result.redirect := inst(14, 12) === 1.U
            result.invalidateFetch := inst(14, 12) === 1.U
            when(inst(14, 12) === 1.U) { state := waitFenceI }
        }.elsewhen(inst === "h10500073".U) {
            val illegal = privilege =/= 3.U && hypervisor.map(_.io.tw).getOrElse(false.B)
            val virtualWfi = virtualized && (privilege === 0.U || hypervisor.map(_.io.vtw).getOrElse(false.B)) && !illegal
            result.completion.exception := illegal || virtualWfi
            result.completion.cause := Mux(virtualWfi, 22.U, 2.U)
            result.completion.data := 0.U
        }.elsewhen(sfenceVma && (p.virtualMemoryLevels > 0).B && privilege >= 1.U &&
            !hypervisor.map(h => Mux(virtualized, h.io.vtvm, privilege === 1.U && h.io.tvm)).getOrElse(false.B)) {
            // The ROB-head barrier has drained older data and fetches before this transaction starts.
            result.redirect := true.B
            result.invalidateFetch := true.B
            state := waitVmFlush
        }.elsewhen(csr) {
            result.completion.exception := !legalCsr
            result.completion.cause := Mux(virtualCsr && !(write && address(11, 10) === 3.U), 22.U, 2.U)
            result.completion.data      := Mux(read, readValue, 0.U)
            when(legalCsr) {
                aia.io.hvictlWrite.valid := experimentalHypervisor.B && write && address === "h609".U
                aia.io.hvictlWrite.bits := newValue
                hypervisor.foreach { h =>
                    h.io.write.valid := write
                    h.io.write.bits.address := address
                    h.io.write.bits.data := newValue
                }
                if (experimentalHypervisor) {
                    when(write && (address === "h180".U || address === "h280".U || address === "h680".U)) {
                        result.redirect := true.B; result.invalidateFetch := true.B; state := waitVmFlush
                    }
                }
                // A permission update refetches all younger instructions under the new policy.
                when(write && pmpPermissionsChange) {
                    result.redirect := true.B
                    result.invalidateFetch := true.B
                    if (p.virtualMemoryLevels > 0) { state := waitVmFlush }
                }
                when(priorityWindow) {
                    result.completion.data := 0.U // All physical iprio priority fields are RO0.
                }.elsewhen(imsic) {
                    external.file := Mux(guestImsic,
                        hypervisor.map(_.io.vgein +& 1.U).getOrElse(0.U), Mux(supervisorImsic, 1.U, 0.U))
                    external.selector := Mux(guestImsic, hypervisor.map(_.io.vsiselect).getOrElse(0.U),
                        Mux(supervisorImsic, siselect, miselect))
                    external.topei := address === "h35c".U || address === "h15c".U || address === "h25c".U
                    external.operation := Mux(write, operation, 0.U)
                    external.data      := source
                    state              := send
                }.elsewhen(write && !hypervisor.map(_.io.shadow).getOrElse(false.B)) {
                    switch(address) {
                        is("h300".U) {
                            mie  := newValue(3)
                            mpie := newValue(7)
                            mpp  := Mux(newValue(12, 11) === 2.U, 3.U, newValue(12, 11))
                            sie  := newValue(1)
                            spie := newValue(5)
                            spp  := newValue(8)
                            mprv := newValue(17)
                            if (p.virtualMemoryLevels > 0) {
                                sum := newValue(18)
                                mxr := newValue(19)
                            }
                        }
                        is("h302".U) { medeleg := newValue & (if (experimentalHypervisor) "hf0b7ff".U else "hb3ff".U) }
                        is("h303".U) {
                            seideleg := newValue(9)
                            stideleg := newValue(5)
                            ssideleg := newValue(1)
                        }
                        is("h100".U) {
                            sie := newValue(1); spie := newValue(5); spp := newValue(8)
                            if (p.virtualMemoryLevels > 0) {
                                sum := newValue(18); mxr := newValue(19)
                            }
                        }
                        is("h104".U) {
                            when(seideleg) { seie := newValue(9) }
                            when(stideleg) { stie := newValue(5) }
                            when(ssideleg) { ssie := newValue(1) }
                        }
                        is("h144".U) { when(ssideleg) { ssip := newValue(1) } }
                        is("h14d".U) { stimecmp := newValue }
                        is("h106".U) { scounterenTm := newValue(1) }
                        is("h105".U) { stvec := Cat(newValue(63, 2), Mux(newValue(1, 0) === 1.U, 1.U(2.W), 0.U(2.W))) }
                        is("h140".U) { sscratch := newValue }
                        is("h141".U) { sepc := alignedEpc(newValue) }
                        is("h142".U) { scause := newValue }
                        is("h143".U) { stval := newValue }
                        is("h150".U) { siselect := newValue(11, 0) }
                        is("h180".U) {
                            if (p.virtualMemoryLevels > 0) {
                                val mode = newValue(63, 60)
                                when(mode === 0.U || (mode >= 8.U && mode <= (p.virtualMemoryLevels + 5).U)) {
                                    satp := Mux(mode === 0.U, 0.U, newValue)
                                    result.redirect := true.B
                                    result.invalidateFetch := true.B
                                }
                            }
                        }
                        is("h305".U) { mtvec := Cat(newValue(63, 2), Mux(newValue(1, 0) === 1.U, 1.U(2.W), 0.U(2.W))) }
                        is("h304".U) {
                            meie := newValue(11)
                            seie := newValue(9)
                            mtie := newValue(7)
                            stie := newValue(5)
                            ssie := newValue(1)
                        }
                        is("h309".U) {
                            ssip := newValue(1); seipSoftware := newValue(9)
                            when(!stce) { stipSoftware := newValue(5) }
                        }
                        is("h344".U) {
                            seipSoftware := newValue(9)
                            ssip := newValue(1)
                            when(!stce) { stipSoftware := newValue(5) }
                        }
                        is("h306".U) { mcounterenTm := newValue(1) }
                        is("h30a".U) { stce := newValue(63) }
                        is("h340".U) { mscratch := newValue }
                        is("h341".U) { mepc := alignedEpc(newValue) }
                        is("h342".U) { mcause := newValue }
                        is("h343".U) { mtval := newValue }
                        is("h350".U) { miselect := newValue(11, 0) }
                    }
                    if (p.pmpEntries > 0) {
                        // Same execute/legal CSR/write branch as the actual writes below.
                        pmpRawChangeWrite.foreach(_ := pmpRawStateChange)
                        when(address === "h3a0".U) {
                            for (i <- 0 until math.min(8, p.pmpEntries)) {
                                val raw = newValue(8 * i + 7, 8 * i)
                                when(!pmpCfg(i)(7)) {
                                    pmpCfgWrite(i) := Cat(raw(7), 0.U(2.W), raw(4, 2), raw(1) && raw(0), raw(0))
                                    pmpRegionWrite.foreach(_(i) := true.B)
                                }
                            }
                        }
                        when(address === "h3a2".U) {
                            for (i <- 8 until p.pmpEntries) {
                                val raw = newValue(8 * (i - 8) + 7, 8 * (i - 8))
                                when(!pmpCfg(i)(7)) {
                                    pmpCfgWrite(i) := Cat(raw(7), 0.U(2.W), raw(4, 2), raw(1) && raw(0), raw(0))
                                    pmpRegionWrite.foreach(_(i) := true.B)
                                }
                            }
                        }
                        for (i <- 0 until p.pmpEntries) {
                            when(address === (0x3b0 + i).U) {
                                val nextTorLocked = if (i + 1 < p.pmpEntries)
                                    pmpCfg(i + 1)(7) && pmpCfg(i + 1)(4, 3) === 1.U else false.B
                                when(!pmpCfg(i)(7) && !nextTorLocked) {
                                    pmpAddrWrite(i) := newValue(53, 0)
                                    pmpRegionWrite.foreach { enables =>
                                        // Even an OFF entry has observable decoded bounds.
                                        enables(i) := true.B
                                        if (i + 1 < p.pmpEntries) {
                                            // A single CSR write cannot change cfg concurrently.
                                            // This predecessor write changes the next TOR low/active.
                                            when(pmpCfg(i + 1)(4, 3) === 1.U) { enables(i + 1) := true.B }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }.elsewhen(inst === "h30200073".U && privilege === 3.U) {
            hypervisor.foreach(_.io.mret := true.B)
            result.redirect          := true.B
            result.invalidateFetch   := (p.pmpEntries > 0).B || experimentalHypervisor.B
            result.completion.nextPc := mepc
            privilege                := mpp
            mie                      := mpie
            mpie                     := true.B
            mpp                      := 0.U
            when(mpp =/= 3.U) { mprv := false.B }
        }.elsewhen(inst === "h10200073".U && privilege >= 1.U &&
            !hypervisor.map(h => Mux(virtualized, h.io.vtsr, privilege === 1.U && h.io.tsr)).getOrElse(false.B)) {
            hypervisor.foreach(_.io.sret := true.B)
            result.redirect          := true.B
            result.invalidateFetch   := (p.pmpEntries > 0).B
            result.completion.nextPc := Mux(virtualized, hypervisor.map(_.io.guestReturnPc).getOrElse(0.U), sepc)
            privilege := Mux(virtualized, hypervisor.map(_.io.guestReturnPrivilege).getOrElse(0.U), Mux(spp, 1.U, 0.U))
            when(!virtualized) { sie := spie; spie := true.B; spp := false.B }
            if (experimentalHypervisor) { mprv := false.B; result.invalidateFetch := true.B }
        }.otherwise {
            result.completion.exception := true.B
            when(inst === "h00000073".U) {
                result.completion.cause := Mux(privilege === 3.U, 11.U,
                    Mux(privilege === 1.U, Mux(virtualized, 10.U, 9.U), 8.U))
                result.completion.tval  := 0.U
            }.elsewhen(virtualized && (sfenceVma || inst === "h10200073".U)) {
                result.completion.cause := 22.U
            }.elsewhen(inst === "h00100073".U) {
                result.completion.cause := 3.U
                result.completion.tval  := request.pc
            }
        }
    }
    when(io.trap.valid) {
        assert(state === idle, "trap overlapped an irrevocable system transaction")
        when(guestTrap) {
            privilege := 1.U
        }.elsewhen(delegated) {
            sepc      := alignedEpc(io.trap.bits.pc)
            scause    := io.trap.bits.cause
            stval     := io.trap.bits.tval
            spie      := sie
            sie       := false.B
            spp       := privilege === 1.U
            privilege := 1.U
        }.otherwise {
            mepc      := alignedEpc(io.trap.bits.pc)
            mcause    := io.trap.bits.cause
            mtval     := io.trap.bits.tval
            mpie      := mie
            mie       := false.B
            mpp       := privilege
            privilege := 3.U
        }
    }
}
