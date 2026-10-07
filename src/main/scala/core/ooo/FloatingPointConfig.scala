package soc.core.ooo

/** Elaboration-time configuration: D requires F; disabled units are not instantiated.
  * Removing an instruction group creates an experimental subset, not full F/D.
  * Integer issue width is independent of this conservative, serialized FP port.
  */
case class FloatingPointConfig(
    f: Boolean = false, d: Boolean = false,
    addSubtract: Boolean = true, multiply: Boolean = true,
    divide: Boolean = true, squareRoot: Boolean = true,
    fusedMultiplyAdd: Boolean = true, compareMinMax: Boolean = true,
    signClassMove: Boolean = true, conversions: Boolean = true,
    memory: Boolean = true
) {
    require(!d || f, "D requires F")
    def complete: Boolean = f && addSubtract && multiply && divide && squareRoot &&
        fusedMultiplyAdd && compareMinMax && signClassMove && conversions && memory
}
object FloatingPointConfig {
    val disabled: FloatingPointConfig = FloatingPointConfig()
    val fullF: FloatingPointConfig = FloatingPointConfig(f = true)
    val fullFD: FloatingPointConfig = FloatingPointConfig(f = true, d = true)
}
