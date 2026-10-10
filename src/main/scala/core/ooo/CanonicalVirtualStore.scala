package soc.core.ooo

import chisel3._
import chisel3.util._

/** Optional request-synchronous identity. It grants neither completion nor posted-store authority. */
class CanonicalStoreOrigin(p: OooParams) extends Bundle {
    val token = new RobToken(p)
    val epoch = UInt(32.W)
}

/** Store-only frozen binding. The existing origin carries its full token and epoch separately.
  * This payload grants neither an early response nor physical posted-store authority.
  * At ROB64/tag64 the sibling Valid fields total 103 + 140 = 243 bits, with no outer Valid.
  * DataRequest has no independent token: association is established at actual LSU start,
  * preserved on the exact request handshake at each hop, and matched against the tracker owner.
  * An adapter cannot diagnose an arbitrary common-mode substitution of that trusted origin.
  */
class FrozenStoreProof extends Bundle {
    val address = UInt(64.W) // Original virtual address, retained for precise faults.
    val physicalAddress = UInt(64.W)
    val size = UInt(3.W)
    val mask = UInt(8.W)
}

class CanonicalStoreDescriptor(p: OooParams) extends Bundle {
    val origin = new CanonicalStoreOrigin(p)
    val virtualAddress = UInt(64.W)
    // The extra bit permits malformed certificates to fail closed at the consumer.
    val size = UInt(3.W)
    val mask = UInt(8.W)
}

class CanonicalStoreCertificate(p: OooParams) extends CanonicalStoreDescriptor(p) {
    val physicalAddress = UInt(64.W)
}

class CanonicalStoreCpuPort(p: OooParams) extends Bundle {
    val requestOrigin = Output(Valid(new CanonicalStoreOrigin(p)))
    val requestFrozenProof = if (p.memoryProofFrontier) Some(Output(Valid(new FrozenStoreProof))) else None
    val checked = Input(Valid(new CanonicalStoreCertificate(p)))
}

private[ooo] object CanonicalVirtualStore {
    def frozenShape(p: OooParams, proof: FrozenStoreProof): Bool = {
        val start = Cat(0.U(1.W), proof.physicalAddress)
        val bytes = MuxLookup(proof.size, 0.U(65.W))(
            Seq(0.U -> 1.U(65.W), 1.U -> 2.U(65.W), 2.U -> 4.U(65.W), 3.U -> 8.U(65.W)))
        val end = start + bytes
        proof.size <= 3.U && AlignedMemoryDisjoint.aligned(proof.address, proof.size) &&
            AlignedMemoryDisjoint.aligned(proof.physicalAddress, proof.size) &&
            proof.address(11, 0) === proof.physicalAddress(11, 0) &&
            proof.mask === AlignedMemoryDisjoint.lanes(proof.physicalAddress, proof.size) &&
            start >= p.speculativeRamBase.U(65.W) &&
            end <= (p.speculativeRamBase + p.speculativeRamBytes).U(65.W) && end > start
    }

    def frozenMatches(p: OooParams, request: DataRequest, proof: FrozenStoreProof): Bool =
        request.virtualized && request.write && !request.atomic && !request.precheckedLoad && !request.uncached &&
            request.address === proof.address && request.size === proof.size && request.mask === proof.mask &&
            frozenShape(p, proof)

    def heldFrozen(p: OooParams, request: DecoupledIO[DataRequest], origin: ValidIO[CanonicalStoreOrigin],
        proof: ValidIO[FrozenStoreProof]): Unit = {
        val stalled = RegNext(request.valid && !request.ready, false.B)
        val oldProof = RegEnable(proof, request.valid && !request.ready)
        when(stalled) {
            assert(proof.valid === oldProof.valid &&
                (!oldProof.valid || proof.bits.asUInt === oldProof.bits.asUInt),
                "held frozen-store transport retains the complete immutable physical binding")
        }
        when(request.valid && proof.valid) {
            assert(origin.valid && frozenMatches(p, request.bits, proof.bits),
                "frozen store proof requires the matching actual ordinary virtual-store origin and shape")
        }
    }

    def held(request: DecoupledIO[DataRequest], origin: ValidIO[CanonicalStoreOrigin]): Unit = {
        val stalled = RegNext(request.valid && !request.ready, false.B)
        val oldRequest = RegEnable(request.bits, request.valid && !request.ready)
        val oldOrigin = RegEnable(origin, request.valid && !request.ready)
        when(stalled) {
            assert(request.valid && request.bits.asUInt === oldRequest.asUInt,
                "held canonical-store transport retains the original request")
            assert(origin.valid === oldOrigin.valid &&
                (!oldOrigin.valid || origin.bits.asUInt === oldOrigin.bits.asUInt),
                "held canonical-store transport retains the full token and epoch")
        }
        when(request.valid && origin.valid) {
            assert(request.bits.virtualized && request.bits.write && !request.bits.atomic &&
                !request.bits.precheckedLoad && !request.bits.uncached,
                "canonical-store origin belongs only to an actual ordinary virtual write")
        }
    }
}

/** One disposable record, II=one head-store lifetime. A checked event is usable only after capture.
  * This module owns no request/response credit and cannot hold a memory drain busy.
  */
class CanonicalStoreTracker(p: OooParams) extends Module {
    require(p.canonicalVirtualStoreOverlap)
    val io = IO(new Bundle {
        val start = Input(Valid(new CanonicalStoreDescriptor(p)))
        val checked = Input(Valid(new CanonicalStoreCertificate(p)))
        val ownerLive = Input(Bool())
        val invalidate = Input(Bool())
        val stable = Input(Bool())
        val epoch = Input(UInt(32.W))
        val tracked = Output(Bool())
        val owner = Output(new RobToken(p))
        val certificate = Output(Valid(new CanonicalStoreCertificate(p)))
    })
    val tracked = RegInit(false.B)
    val certified = RegInit(false.B)
    val record = Reg(new CanonicalStoreCertificate(p))
    io.tracked := tracked
    io.owner := record.origin.token
    io.certificate.valid := tracked && certified && io.ownerLive && io.stable &&
        record.origin.epoch === io.epoch
    io.certificate.bits := record
    val matching = io.checked.bits.origin.asUInt === record.origin.asUInt &&
        io.checked.bits.virtualAddress === record.virtualAddress &&
        io.checked.bits.size === record.size && io.checked.bits.mask === record.mask
    val shape = io.checked.bits.size <= 3.U &&
        AlignedMemoryDisjoint.aligned(io.checked.bits.physicalAddress, io.checked.bits.size) &&
        AlignedMemoryDisjoint.aligned(io.checked.bits.virtualAddress, io.checked.bits.size) &&
        io.checked.bits.mask === AlignedMemoryDisjoint.lanes(io.checked.bits.physicalAddress, io.checked.bits.size) &&
        io.checked.bits.virtualAddress(11, 0) === io.checked.bits.physicalAddress(11, 0) &&
        SpeculativeRamRange.contains(p, io.checked.bits.physicalAddress, io.checked.bits.size)
    when(tracked && !io.ownerLive) {
        tracked := false.B
        certified := false.B
    }
    when(io.start.valid) {
        assert(!tracked || !io.ownerLive, "only one actual head store can own canonical tracking")
        assert(io.start.bits.origin.epoch === io.epoch && io.stable)
        tracked := true.B
        certified := false.B
        record.origin := io.start.bits.origin
        record.virtualAddress := io.start.bits.virtualAddress
        record.size := io.start.bits.size
        record.mask := io.start.bits.mask
        record.physicalAddress := 0.U
    }
    when(io.checked.valid && tracked && io.ownerLive && matching && shape &&
        io.stable && io.checked.bits.origin.epoch === io.epoch) {
        assert(!certified, "an accepted store crosses checked capture only once")
        record.physicalAddress := io.checked.bits.physicalAddress
        certified := true.B
    }
    // Same-edge kill, final fault, retirement and context loss dominate every proof event.
    when(io.invalidate || !io.stable || (tracked && record.origin.epoch =/= io.epoch)) {
        tracked := false.B
        certified := false.B
    }
    when(certified) { assert(tracked) }
}
