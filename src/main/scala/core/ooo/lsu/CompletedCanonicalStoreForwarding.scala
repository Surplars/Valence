package soc.core.ooo

import chisel3._
import chisel3.util._

/** Successful completed-store data is joined to the exact live physical certificate.
  * Zero latency / II=1, no storage, request credit, or new completion authority.
  * `source.valid` comes only from the LSU's selected registered successful done owner;
  * `load.valid` is the strict read-permission certificate, not a write-proof substitute.
  * The backend still applies its system/interrupt/recovery admission veto. The LSU
  * may consume this join only while that SAME store completion frees its own slot.
  */
class CompletedCanonicalStoreForwarding(p: OooParams) extends Module {
    require(p.completedCanonicalStoreForwarding)
    val io = IO(new Bundle {
        val source = Input(Valid(new StoreForward(p)))
        val store = Input(Valid(new CanonicalStoreCertificate(p)))
        val load = Input(Valid(new VirtualRamLoadCertificate(p)))
        val ordinaryVirtualLoad = Input(Bool())
        val sourceOlder = Input(Bool())
        val pendingOlderStore = Input(Bool())
        val stable = Input(Bool())
        val epoch = Input(UInt(32.W))
        val qualified = Output(Bool())
    })
    val source = io.source.bits
    val store = io.store.bits
    val load = io.load.bits
    val storeShape = CompletedCanonicalStoreForwarding.storeShape(p, store)
    val loadShape = AlignedMemoryDisjoint.aligned(load.address, load.size) &&
        AlignedMemoryDisjoint.aligned(load.physicalAddress, load.size) &&
        load.address(11, 0) === load.physicalAddress(11, 0) &&
        SpeculativeRamRange.contains(p, load.physicalAddress, load.size)
    io.qualified := io.source.valid && io.store.valid && io.load.valid && load.allowed &&
        io.ordinaryVirtualLoad && io.sourceOlder && !io.pendingOlderStore && io.stable &&
        source.token.asUInt === store.origin.token.asUInt &&
        source.address === store.virtualAddress && source.size === store.size &&
        load.token.asUInt =/= source.token.asUInt &&
        store.origin.epoch === io.epoch && load.epoch === io.epoch && storeShape && loadShape &&
        CompletedCanonicalStoreForwarding.covers(store, load.physicalAddress, load.size)
}

object CompletedCanonicalStoreForwarding {
    def storeShape(p: OooParams, store: CanonicalStoreCertificate): Bool =
        store.size <= 3.U && AlignedMemoryDisjoint.aligned(store.virtualAddress, store.size) &&
            AlignedMemoryDisjoint.aligned(store.physicalAddress, store.size) &&
            store.virtualAddress(11, 0) === store.physicalAddress(11, 0) &&
            store.mask === AlignedMemoryDisjoint.lanes(store.physicalAddress, store.size) &&
            SpeculativeRamRange.contains(p, store.physicalAddress, store.size)

    def covers(store: CanonicalStoreCertificate, loadAddress: UInt, loadSize: UInt): Bool = {
        val loadMask = AlignedMemoryDisjoint.lanes(loadAddress, loadSize)
        store.physicalAddress(63, 3) === loadAddress(63, 3) && (store.mask & loadMask) === loadMask
    }
}
