package soc.core.ooo

import chisel3._
import chisel3.util._

/** Acceptance-time translation context, never reconstructed from live CSRs. */
class GuestTranslationRequest extends Bundle {
    val virtualAddress = UInt(64.W)
    val vsatp = UInt(64.W) // satp for a non-virtualized request.
    val hgatp = UInt(64.W)
    val virtualized = Bool()
    val effectivePrivilege = UInt(2.W)
    val access = UInt(2.W)
    val size = UInt(3.W)
    val vsSum = Bool()
    val vsMxr = Bool()
    val hsMxr = Bool()
    val forceExecute = Bool() // HLVX: PTE X, final physical R and X, load exception class.
    val epoch = UInt(8.W)
}

class GuestTranslationResponse extends SvWalkResponse {
    val virtualAddress = UInt(64.W)
    val guestPageFault = Bool()
    val guestPhysicalAddress = UInt(64.W) // Unshifted GPA, including an implicit VS PTE address.
    val implicitPte = Bool()
    val guestAddress = Bool()
    val epoch = UInt(8.W)
    val cancelled = Bool()
}

/** Master-facing port: one response for every accepted request. */
class GuestTranslationPort extends Bundle {
    val request = Decoupled(new GuestTranslationRequest)
    val response = Flipped(Decoupled(new GuestTranslationResponse))
}

/** Conservative, uncached nested Sv39/Sv39x4 translation owner.
  * Capacity=1, II=full walk+response retirement, one physical PTE read outstanding.
  * Every accepted request returns exactly once, including cancelled requests. A
  * cancellation preserves an already offered memory request until acceptance and
  * drains its response; no subsequent read is launched. A held completion cannot
  * be changed by cancel: the consumer must additionally reject stale epochs.
  * Svade: A/D faults, no speculative PTE writes. No TLB, so a fence needs only
  * drain this owner and the downstream PTE cache before changing CSR/PMP state.
  * Caller supplies stable PMP state until idle, checks final PMA (including X+R
  * for HLVX), handles misalignment/split-page accesses before requesting translation,
  * preserves the original access exception class, and never caches a
  * combined translation using level alone. This bring-up module supports base
  * Sv39 PTEs; Svnapot/Svpbmt and Sv48/Sv57 are deliberately not advertised here.
  */
class GuestTranslationService(pmpEntries: Int = 16) extends Module {
    val io = IO(new Bundle {
        val request = Flipped(Decoupled(new GuestTranslationRequest))
        val response = Decoupled(new GuestTranslationResponse)
        val memory = new SvPteReadPort
        val pmpState = Input(new PmpState)
        val cancel = Input(Bool())
        val idle = Output(Bool())
    })
    val Seq(idle, beginVs, vsAddress, beginG, gAddress, checkRead, offerRead, waitRead,
        parseVs, parseG, finalCheck, finalExecuteCheck, finish) = Enum(13)
    val state = RegInit(idle)
    val saved = Reg(new GuestTranslationRequest)
    val result = RegInit(0.U.asTypeOf(new GuestTranslationResponse))
    val killed = RegInit(false.B)
    val vsTable = Reg(UInt(44.W))
    val vsLevel = Reg(UInt(2.W))
    val gTable = Reg(UInt(44.W))
    val gLevel = Reg(UInt(2.W))
    val gpa = Reg(UInt(64.W))
    val implicitRead = RegInit(false.B)
    val physicalRead = Reg(UInt(64.W))
    val readIsG = RegInit(false.B)
    val pte = Reg(UInt(64.W))
    val vsGlobal = RegInit(false.B)
    val vsTranslated = saved.vsatp(63, 60) =/= 0.U && saved.effectivePrivilege =/= 3.U
    val cancelledNow = killed || io.cancel
    val explicitPermission = Mux(saved.forceExecute, PmpAccess.execute, saved.access)
    val gPermission = Mux(implicitRead, PmpAccess.read, explicitPermission)

    val pmp = Module(new PmpChecker(pmpEntries))
    pmp.io.state := io.pmpState
    val finalAccess = state === finalCheck || state === finalExecuteCheck
    pmp.io.address := Mux(finalAccess, result.physicalAddress, physicalRead)
    pmp.io.size := Mux(finalAccess, saved.size, 3.U)
    pmp.io.privilege := Mux(finalAccess && !saved.virtualized, saved.effectivePrivilege, 1.U)
    pmp.io.access := Mux(state === finalExecuteCheck, PmpAccess.execute,
        Mux(finalAccess, saved.access, PmpAccess.read))

    io.idle := state === idle
    io.request.ready := state === idle && !io.cancel
    io.response.valid := state === finish
    io.response.bits := result
    io.memory.request.valid := state === offerRead
    io.memory.request.bits := physicalRead
    io.memory.response.ready := state === waitRead

    def terminate(page: Bool = false.B, guest: Bool = false.B, access: Bool = false.B): Unit = {
        result.pageFault := page
        result.guestPageFault := guest
        result.accessFault := access
        result.guestPhysicalAddress := Mux(guest, gpa, 0.U)
        result.implicitPte := guest && implicitRead
        state := finish
    }
    def cancelComplete(): Unit = {
        result.pageFault := false.B
        result.guestPageFault := false.B
        result.accessFault := false.B
        result.cancelled := true.B
        result.guestPhysicalAddress := 0.U
        result.implicitPte := false.B
        state := finish
    }
    def beginGuest(address: UInt, implicitAccess: Bool): Unit = {
        gpa := address
        implicitRead := implicitAccess
        state := beginG
    }
    def gTranslated(address: UInt): Unit = {
        when(implicitRead) {
            physicalRead := address
            readIsG := false.B
            state := checkRead
        }.otherwise {
            result.physicalAddress := address
            result.guestPhysicalAddress := Mux(saved.virtualized, gpa, 0.U)
            state := finalCheck
        }
    }
    def permissions(p: UInt, access: UInt, mxr: Bool): Bool = MuxLookup(access, false.B)(Seq(
        PmpAccess.read -> (p(1) || (mxr && p(3))),
        PmpAccess.write -> p(2),
        PmpAccess.execute -> p(3),
        PmpAccess.readWrite -> (p(1) && p(2))))
    def leafAddress(ppn: UInt, address: UInt, level: UInt): UInt = {
        val high = ppn(43, 18)
        val middle = Mux(level === 2.U, address(29, 21), ppn(17, 9))
        val low = Mux(level =/= 0.U, address(20, 12), ppn(8, 0))
        Cat(0.U(8.W), high, middle, low, address(11, 0))
    }
    val leaf = pte(1) || pte(3)
    val ppn = pte(53, 10)
    val invalid = !pte(0) || (pte(2) && !pte(1)) || pte(63, 54).orR ||
        (!leaf && (pte(7, 6).orR || pte(4)))
    def misaligned(level: UInt): Bool = (level === 2.U && ppn(17, 0).orR) ||
        (level === 1.U && ppn(8, 0).orR)
    def dirtyNeeded(access: UInt): Bool = access === PmpAccess.write || access === PmpAccess.readWrite

    when(io.request.fire) {
        saved := io.request.bits
        result := 0.U.asTypeOf(new GuestTranslationResponse)
        result.virtualAddress := io.request.bits.virtualAddress
        result.guestAddress := io.request.bits.virtualized
        result.epoch := io.request.bits.epoch
        killed := false.B
        vsGlobal := false.B
        state := beginVs
    }
    when(state === beginVs) {
        when(!vsTranslated) {
            beginGuest(saved.virtualAddress, false.B)
        }.elsewhen(saved.vsatp(63, 60) =/= 8.U ||
            saved.virtualAddress(63, 39) =/= Fill(25, saved.virtualAddress(38))) {
            terminate(page = true.B)
        }.otherwise {
            vsTable := saved.vsatp(43, 0)
            vsLevel := 2.U
            state := vsAddress
        }
    }
    when(state === vsAddress) {
        val index = MuxLookup(vsLevel, saved.virtualAddress(20, 12))(Seq(
            1.U -> saved.virtualAddress(29, 21), 2.U -> saved.virtualAddress(38, 30)))
        beginGuest(Cat(0.U(8.W), vsTable, 0.U(12.W)) + (index << 3), true.B)
    }
    when(state === beginG) {
        when(!saved.virtualized || saved.hgatp(63, 60) === 0.U) {
            gTranslated(gpa)
        }.elsewhen(saved.hgatp(63, 60) =/= 8.U || gpa(63, 41).orR ||
            saved.hgatp(1, 0).orR) {
            terminate(guest = true.B)
        }.otherwise {
            gTable := saved.hgatp(43, 0)
            gLevel := 2.U
            state := gAddress
        }
    }
    when(state === gAddress) {
        // The root is 16 KiB, with 11 index bits. Lower levels remain 9 bits.
        val index = MuxLookup(gLevel, Cat(0.U(2.W), gpa(20, 12)))(Seq(
            1.U -> Cat(0.U(2.W), gpa(29, 21)), 2.U -> gpa(40, 30)))
        physicalRead := Cat(0.U(8.W), gTable, 0.U(12.W)) + (index << 3)
        readIsG := true.B
        state := checkRead
    }
    when(state === checkRead) {
        when(pmp.io.denied || physicalRead(63, 56).orR) { terminate(access = true.B) }
            .otherwise { state := offerRead }
    }
    when(io.memory.request.fire) { state := waitRead }
    when(io.memory.response.fire) {
        pte := io.memory.response.bits.data
        when(cancelledNow) { cancelComplete() }
            .elsewhen(io.memory.response.bits.error) { terminate(access = true.B) }
            .otherwise { state := Mux(readIsG, parseG, parseVs) }
    }
    when(state === parseVs) {
        val userAllowed = Mux(saved.effectivePrivilege === 0.U, pte(4),
            Mux(saved.access === PmpAccess.execute, !pte(4), !pte(4) || saved.vsSum))
        when(invalid) { terminate(page = true.B) }
            .elsewhen(!leaf) {
                when(vsLevel === 0.U) { terminate(page = true.B) }
                    .otherwise {
                        vsTable := ppn
                        vsLevel := vsLevel - 1.U
                        vsGlobal := vsGlobal || pte(5)
                        state := vsAddress
                    }
            }.elsewhen(misaligned(vsLevel) || !userAllowed ||
                !permissions(pte, explicitPermission, saved.hsMxr || saved.vsMxr) || !pte(6) ||
                (dirtyNeeded(saved.access) && !pte(7))) { terminate(page = true.B) }
            .otherwise {
                result.level := vsLevel
                result.global := vsGlobal || pte(5)
                beginGuest(leafAddress(ppn, saved.virtualAddress, vsLevel), false.B)
            }
    }
    when(state === parseG) {
        when(invalid) { terminate(guest = true.B) }
            .elsewhen(!leaf) {
                when(gLevel === 0.U) { terminate(guest = true.B) }
                    .otherwise { gTable := ppn; gLevel := gLevel - 1.U; state := gAddress }
            }.elsewhen(misaligned(gLevel) || !pte(4) || !permissions(pte, gPermission, saved.hsMxr) ||
                !pte(6) || (dirtyNeeded(gPermission) && !pte(7))) { terminate(guest = true.B) }
            .otherwise {
                // G-stage global is ignored. The combined page is no larger than either leaf.
                when(!implicitRead) { result.level := Mux(vsTranslated && result.level < gLevel,
                    result.level, gLevel) }
                gTranslated(leafAddress(ppn, gpa, gLevel))
            }
    }
    when(state === finalCheck) {
        when(pmp.io.denied || result.physicalAddress(63, 56).orR) { terminate(access = true.B) }
            .elsewhen(saved.forceExecute) { state := finalExecuteCheck }
            .otherwise { state := finish }
    }
    when(state === finalExecuteCheck) {
        when(pmp.io.denied) { terminate(access = true.B) }.otherwise { state := finish }
    }
    // Do not revoke a Decoupled offer or change a held completion. Kill is sticky
    // while the single physical memory owner finishes, then emits a tombstone.
    when(state =/= idle && state =/= finish && io.cancel) { killed := true.B }
    when(state =/= idle && state =/= finish && state =/= offerRead && state =/= waitRead && cancelledNow) {
        cancelComplete()
    }
    when(io.response.fire) { state := idle }
    when(!reset.asBool) {
        assert(!(io.response.valid && io.memory.request.valid), "translation completion retained a PTE offer")
        when(io.request.fire) {
            assert(io.request.bits.size <= 3.U, "translation access exceeds one scalar beat")
            val alignmentMask = (1.U(9.W) << io.request.bits.size) - 1.U
            assert((io.request.bits.virtualAddress(7, 0) & alignmentMask(7, 0)) === 0.U,
                "translation caller must reject or split a misaligned access")
            assert(!io.request.bits.virtualized || io.request.bits.effectivePrivilege =/= 3.U,
                "M-mode requests cannot be virtualized")
            assert(!io.request.bits.forceExecute || io.request.bits.access === PmpAccess.read,
                "HLVX must retain the load access class")
        }
    }
}
