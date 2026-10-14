package soc.core.ooo

import chisel3._
import chisel3.util._

/** The backend's current ROB-owner wiring, shared with its narrow qualification fixture. */
object PendingStoreProofRobOwner {
    def connect(owner: ValidIO[PendingStoreProofOwner], token: RobToken, request: IntegerRequest,
        pending: Bool, memoryLive: Bool, addressKnown: Bool, address: UInt, mask: UInt, index: Int): Unit = {
        // Readiness is deliberately absent: a relied-on physical binding survives until actual store capture.
        owner.valid := pending && memoryLive && addressKnown && token.index === index.U &&
            request.memory && request.store && !request.atomic && !request.system && !request.mulDiv &&
            !request.fetchFault && !request.fetchPageFault && request.operation === IntegerOp.add &&
            request.controlFlow === ControlFlow.none
        owner.bits.token := token
        owner.bits.address := address
        owner.bits.size := request.memorySize
        owner.bits.mask := mask
    }
}

/** Only for proofs from PendingVirtualStoreProof connected to these exact current ROB owners.
  * A valid row already checks full token, VA, size, mask and epoch against its indexed owner.
  * Thus its valid plus index implies the same-cycle full ROB token equality. No saved grant,
  * generation truncation or staged-memory-owner equivalence is implied by this decode.
  */
object PendingStoreProofRobMapping {
    def matches(proof: ValidIO[MemoryAddressProof], index: Int): Bool =
        proof.valid && proof.bits.token.index === index.U

    def assertIndexedOwner(proof: ValidIO[MemoryAddressProof], token: RobToken): Unit = {
        when(proof.valid) {
            assert(proof.bits.token.asUInt === token.asUInt,
                "a valid pending-store proof names the exact current indexed ROB token")
        }
    }
}

/** Select data by registered bound-row identity, never by late proof validity.
  * PendingVirtualStoreProof admits an index only when absent from all non-free
  * rows, and its later record writes retain that index. Thus bound rows have
  * distinct indices, including cycles that clear/consume a previous owner.
  * The caller must retain its full-token/descriptor/valid authorization. When
  * that authorization is false, this payload deliberately has no zeroing mux.
  */
object BoundStoreProofPayload {
    def select(bound: UInt, records: Seq[MemoryAddressProof], ownerIndex: UInt): MemoryAddressProof = {
        require(Set(1, 2).contains(records.length))
        if (records.length == 1) records.head
        else Mux(bound(0) && records.head.token.index === ownerIndex, records.head, records(1))
    }
}
