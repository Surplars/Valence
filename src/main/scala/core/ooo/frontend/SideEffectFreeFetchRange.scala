package soc.core.ooo

/** Elaboration-time proof boundary for extra identity fetches. Integrators must
  * supply actual side-effect-free physical RAM, never ROM, MMIO, or a mere PMP
  * permission window. This range does not grant execute permission.
  */
final case class SideEffectFreeFetchRange(base: BigInt, bytes: BigInt) {
    require(base >= 0, "side-effect-free fetch RAM base must be nonnegative")
    require(bytes > 0, "side-effect-free fetch RAM range must be nonempty")
    val endExclusive: BigInt = base + bytes
    require(endExclusive <= (BigInt(1) << 64), "side-effect-free fetch RAM range must fit XLEN")
}
