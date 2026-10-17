// Arithmetic/IEEE adapter copied from the local pinned-HardFloat integration; no OoO state/control.
// Provenance: src/main/scala/core/ooo/FloatingPointResourceConfig.scala. Keep numerical changes independently SoftFloat-tested.
package soc.core.inorder

/** Physical implementation choices; no instruction or numerical semantics change.
  * Baseline is explicitly recoverable for matched-vector and synthesis comparison.
  * The FPGA profile keeps complete F/D enabled and the same single-owner contract.
  */
case class I1FloatingPointResourceConfig(
    committedStateMemory: Boolean = false,
    sharedFormatRounders: Boolean = false,
    sharedMultiplyFused: Boolean = false
) {
    require(!sharedMultiplyFused || sharedFormatRounders, "shared multiplication requires the common raw rounding boundary")
}
object I1FloatingPointResourceConfig {
    val baseline: I1FloatingPointResourceConfig = I1FloatingPointResourceConfig()
    val roundOnly: I1FloatingPointResourceConfig = I1FloatingPointResourceConfig(
        committedStateMemory = true, sharedFormatRounders = true)
    val fpga: I1FloatingPointResourceConfig = roundOnly.copy(sharedMultiplyFused = true)
    def named(name: String): I1FloatingPointResourceConfig = name match {
        case "baseline" => baseline
        case "round" => roundOnly
        case "fpga" => fpga
        case _ => throw new IllegalArgumentException(s"Unknown FP resource profile: $name")
    }
}
