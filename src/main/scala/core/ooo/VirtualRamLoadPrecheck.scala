package soc.core.ooo

import chisel3._
import chisel3.util._

/** A side-effect-free, access-tagged hit-only TLB query. It never starts a demand or page walk. */
class SvTranslationPeekPort extends Bundle {
    val request = Output(Valid(new SvTranslationRequest))
    val response = Input(Valid(new SvTranslationResponse))
}

class VirtualLoadPrecheckRequest extends Bundle {
    val address = UInt(64.W)
    val size = UInt(3.W)
    val write = Bool()
}

class VirtualLoadPrecheckResponse extends Bundle {
    val physicalAddress = UInt(64.W)
    val pbmt = UInt(2.W)
    val epoch = UInt(32.W)
}

/** The adapter supplies the current authorization epoch even on a miss. */
class VirtualLoadPrecheckPort extends Bundle {
    val request = Output(Valid(new VirtualLoadPrecheckRequest))
    val response = Input(Valid(new VirtualLoadPrecheckResponse))
    val epoch = Input(UInt(32.W))
    val stable = Input(Bool())
}

class VirtualRamLoadCandidate(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val address = UInt(64.W)
    val size = UInt(2.W)
}

class VirtualRamLoadCertificate(p: OooParams) extends VirtualRamLoadCandidate(p) {
    val physicalAddress = UInt(64.W)
    val epoch = UInt(32.W)
    val allowed = Bool()
}

/** One query/cycle, two registered preparation stages, no demand ownership or backpressure.
  * The first stage isolates TLB lookup/address reconstruction from physical PMP and range checks;
  * the second isolates those checks from issue selection. Misses and denied hits also produce
  * a negative certificate, so head fallback never needs a combinational TLB-hit-to-issue path.
  * Unused proofs are disposable: draining a context-changing CSR must never wait on a younger proof.
  */
class VirtualRamLoadPreparation(p: OooParams) extends Module {
    require(p.virtualRamLoadPrecheck)
    val io = IO(new Bundle {
        val candidate = Input(Valid(new VirtualRamLoadCandidate(p)))
        val precheck = new VirtualLoadPrecheckPort
        val pmpState = Input(new PmpState)
        val privilege = Input(UInt(2.W))
        val flush = Input(Bool())
        val prepared = Output(Valid(new VirtualRamLoadCertificate(p)))
        val hit = Output(Bool())
    })
    val translatedValid = RegInit(false.B)
    val translated = Reg(new VirtualRamLoadCertificate(p))
    val normalMemory = Reg(Bool())
    val preparedValid = RegInit(false.B)
    val prepared = Reg(new VirtualRamLoadCertificate(p))
    io.precheck.request.valid := io.candidate.valid && !io.flush
    io.precheck.request.bits.address := io.candidate.bits.address
    io.precheck.request.bits.size := io.candidate.bits.size
    io.precheck.request.bits.write := false.B
    io.hit := io.precheck.request.valid && io.precheck.response.valid && io.precheck.stable
    val capture = io.precheck.request.valid && io.precheck.stable &&
        (!io.precheck.response.valid || io.precheck.response.bits.epoch === io.precheck.epoch)
    translatedValid := capture
    when(capture) {
        translated.token := io.candidate.bits.token
        translated.address := io.candidate.bits.address
        translated.size := io.candidate.bits.size
        translated.physicalAddress := Mux(io.hit, io.precheck.response.bits.physicalAddress, 0.U)
        translated.epoch := io.precheck.epoch
        translated.allowed := false.B
        normalMemory := io.hit && io.precheck.response.bits.pbmt === 0.U
    }
    val checkedSize = Mux(translatedValid, translated.size, 0.U)
    val alignmentMask = MuxLookup(checkedSize, 7.U(3.W))(Seq(0.U -> 0.U, 1.U -> 1.U, 2.U -> 3.U))
    val pmp = Module(new PmpChecker(p.pmpEntries, naturalAlignedAccess = true))
    pmp.io.state := io.pmpState
    pmp.io.address := Cat(translated.physicalAddress(63, 3),
        translated.physicalAddress(2, 0) & ~alignmentMask)
    pmp.io.size := checkedSize
    pmp.io.privilege := io.privilege
    pmp.io.access := PmpAccess.read
    val fresh = io.precheck.stable && translated.epoch === io.precheck.epoch
    preparedValid := translatedValid && fresh && !io.flush
    when(translatedValid) {
        prepared := translated
        prepared.allowed := normalMemory && !pmp.io.denied &&
            AlignedMemoryDisjoint.aligned(translated.address, translated.size) &&
            SpeculativeRamRange.contains(p, translated.physicalAddress, translated.size) &&
            translated.address(11, 0) === translated.physicalAddress(11, 0)
    }
    when(io.flush || !io.precheck.stable) {
        translatedValid := false.B
        preparedValid := false.B
    }
    io.prepared.valid := preparedValid && io.precheck.stable && prepared.epoch === io.precheck.epoch && !io.flush
    io.prepared.bits := prepared
}
