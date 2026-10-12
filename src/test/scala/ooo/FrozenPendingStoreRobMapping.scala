package ooo

import chisel3._
import chisel3.util._
import soc.core.ooo._

/** Frozen 1e90 backend mapping expressions. Do not weaken this reference with the candidate. */
object FrozenPendingStoreRobMapping {
    def apply(proofs: Seq[ValidIO[MemoryAddressProof]], tokens: Seq[RobToken],
        rowDisjoint: Seq[Bool]): (UInt, UInt) = {
        val present = tokens.indices.map { i =>
            proofs.map(proof => proof.valid && proof.bits.token.asUInt === tokens(i).asUInt &&
                proof.bits.token.index === i.U).reduce(_ || _)
        }
        val disjoint = tokens.indices.map { i =>
            proofs.indices.map(r => rowDisjoint(r) && proofs(r).bits.token.asUInt === tokens(i).asUInt &&
                proofs(r).bits.token.index === i.U).reduce(_ || _)
        }
        (VecInit(present).asUInt, VecInit(disjoint).asUInt)
    }
}
