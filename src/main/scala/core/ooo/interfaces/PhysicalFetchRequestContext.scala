package soc.core.ooo

import chisel3._

/** Immutable physical-demand identity. This has no separate handshake: it is
  * part of the address/mask request owner through every queue and held offer.
  * PMP configuration changes still require the existing complete fetch drain.
  */
class PhysicalFetchRequestContext(val withSpeculationContext: Boolean = false) extends Bundle {
    val privilege = UInt(2.W)
    // Original ordered fetch transaction, not a ROB token or architectural epoch.
    // Non-certified producers drive identityTranslation=false; zero is not a certificate.
    val sourceSequence = if (withSpeculationContext) Some(UInt(64.W)) else None
    val identityTranslation = if (withSpeculationContext) Some(Bool()) else None
}
