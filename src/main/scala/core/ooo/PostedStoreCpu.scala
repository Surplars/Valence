package soc.core.ooo

import chisel3._
import chisel3.util._

/** Optional CPU transport; no DataRequest ABI or independent proof handshake. */
class PostedStoreCpuPort(c: PostedStoreMergeConfig) extends Bundle {
    val requestProof = Output(Valid(new PostedStoreProof(c)))
    val contextEpoch = Input(UInt(c.epochBits.W))
    val externalBusy = Input(Bool())
    val blockNew = Input(Bool())
    val busy = Output(Bool())
    val starting = Output(Bool())
    val seal = Output(Bool())
}

class PostedStoreTranslationPort(c: PostedStoreMergeConfig) extends Bundle {
    val upstreamProof = Input(Valid(new PostedStoreProof(c)))
    val requestProof = Output(Valid(new PostedStoreProof(c)))
    val contextEpoch = Output(UInt(c.epochBits.W))
    val contextChanging = Output(Bool())
    val aggregateDrained = Input(Bool())
    val externalBusy = Input(Bool())
}

/** Shared assertions compare saved immutable payload, never a later ROB lookup. */
private[ooo] object PostedStoreCpu {
    def matches(proof: PostedStoreProof, request: DataRequest): Bool =
        proof.address === request.address && proof.data === request.data &&
            proof.mask === request.mask && proof.size === request.size &&
            request.write && !request.atomic && !request.virtualized &&
            !request.precheckedLoad && !request.uncached &&
            AlignedMemoryDisjoint.aligned(request.address, request.size)

    def held(request: DecoupledIO[DataRequest], proof: ValidIO[PostedStoreProof]): Unit = {
        val stalled = RegNext(request.valid && !request.ready, false.B)
        val oldRequest = RegEnable(request.bits, request.valid && !request.ready)
        val oldProof = RegEnable(proof, request.valid && !request.ready)
        when(stalled) {
            assert(request.valid && request.bits.asUInt === oldRequest.asUInt,
                "held posted transport must retain the original request")
            assert(proof.valid === oldProof.valid && (!oldProof.valid || proof.bits.asUInt === oldProof.bits.asUInt),
                "held posted transport must retain full token, context and authority")
        }
        when(request.valid && proof.valid) { assert(matches(proof.bits, request.bits)) }
    }
}
