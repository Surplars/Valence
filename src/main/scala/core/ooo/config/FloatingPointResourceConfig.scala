package soc.core.ooo

/** Physical implementation choices; no instruction or numerical semantics change.
  * Baseline is explicitly recoverable for matched-vector and synthesis comparison.
  * The FPGA profile keeps complete F/D enabled and the same single-owner contract.
  */
case class FloatingPointResourceConfig(
    committedStateMemory: Boolean = false,
    sharedFormatRounders: Boolean = false,
    sharedMultiplyFused: Boolean = false
) {
    require(!sharedMultiplyFused || sharedFormatRounders, "shared multiplication requires the common raw rounding boundary")
}
object FloatingPointResourceConfig {
    val baseline: FloatingPointResourceConfig = FloatingPointResourceConfig()
    val roundOnly: FloatingPointResourceConfig = FloatingPointResourceConfig(
        committedStateMemory = true, sharedFormatRounders = true)
    val fpga: FloatingPointResourceConfig = roundOnly.copy(sharedMultiplyFused = true)
    def named(name: String): FloatingPointResourceConfig = name match {
        case "baseline" => baseline
        case "round" => roundOnly
        case "fpga" => fpga
        case _ => throw new IllegalArgumentException(s"Unknown FP resource profile: $name")
    }
}
