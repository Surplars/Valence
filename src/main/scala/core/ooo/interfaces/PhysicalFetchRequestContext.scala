package soc.core.ooo

import chisel3._

/** Immutable physical-demand identity. This has no separate handshake: it is
  * part of the address/mask request owner through every queue and held offer.
  * PMP configuration changes still require the existing complete fetch drain.
  */
class PhysicalFetchRequestContext extends Bundle {
    val privilege = UInt(2.W)
}
