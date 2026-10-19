// Arithmetic/IEEE adapter copied from the local pinned-HardFloat integration; no OoO state/control.
// Provenance: src/main/scala/core/ooo/FloatingPointConfig.scala. Keep numerical changes independently SoftFloat-tested.
package soc.core.inorder

/** Elaboration-time configuration: D requires F; disabled units are not instantiated.
  * Removing an instruction group creates an experimental subset, not full F/D.
  * Integer issue width is independent of this conservative, serialized FP port.
  */
case class I1FloatingPointConfig(
    f: Boolean = false, d: Boolean = false,
    addSubtract: Boolean = true, multiply: Boolean = true,
    divide: Boolean = true, squareRoot: Boolean = true,
    fusedMultiplyAdd: Boolean = true, compareMinMax: Boolean = true,
    signClassMove: Boolean = true, conversions: Boolean = true,
    memory: Boolean = true,
    resources: I1FloatingPointResourceConfig = I1FloatingPointResourceConfig.baseline
) {
    require(!d || f, "D requires F")
    def complete: Boolean = f && addSubtract && multiply && divide && squareRoot &&
        fusedMultiplyAdd && compareMinMax && signClassMove && conversions && memory
}
object I1FloatingPointConfig {
    val disabled: I1FloatingPointConfig = I1FloatingPointConfig()
    val fullF: I1FloatingPointConfig = I1FloatingPointConfig(f = true)
    val fullFD: I1FloatingPointConfig = I1FloatingPointConfig(f = true, d = true)
}
