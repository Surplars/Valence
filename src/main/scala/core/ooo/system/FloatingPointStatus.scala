package soc.core.ooo

import chisel3._

/** The current guest status owner; sampled only when FP issue/CSR access is accepted.
  * This is architectural V, not the FP memory pipeline's translation-active flag.
  */
class FloatingPointGuestContext extends Bundle {
    val virtualized = Bool()
    val fs = UInt(2.W)
}

/** Successful architectural mutation, not producer completion or numerical flags.
  * The host FS always becomes Dirty. A guest owner also dirties the single VS FS.
  * One combinational pulse per accepted CSR write or exact-token retirement;
  * no queue/backpressure or extra cycle. The status owner must consume that edge.
  */
class FloatingPointMutation extends Bundle {
    val guest = Bool()
}

/** Shared production FP permission and status-alias policy.
  * Status routes take an already authorized CSR write. Privilege checks, CSR
  * write intent and transaction serialization remain the caller's responsibility.
  */
object FloatingPointStatus {
    def accessAllowed(hostFs: UInt, guestFs: UInt, virtualized: Bool): Bool =
        hostFs =/= 0.U && (!virtualized || guestFs =/= 0.U)

    def writesHost(address: UInt, virtualized: Bool): Bool =
        address === 0x300.U || (address === 0x100.U && !virtualized)

    def writesGuest(address: UInt, virtualized: Bool): Bool =
        address === 0x200.U || (address === 0x100.U && virtualized)

    // SD is derived/read-only. FS=Initial changes metadata, never the FPR/fcsr bank.
    def bits(fs: UInt): UInt = (fs << 13) | ((fs === 3.U).asUInt << 63)
}
