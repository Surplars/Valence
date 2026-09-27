package soc.debug

// RISC-V Debug Module register addresses are DMI word addresses. The TileLink
// MMIO view maps them at address * 4.
object DebugModuleMap {
    val Data0        = 0x04
    val Data1        = 0x05
    val DMControl    = 0x10
    val DMStatus     = 0x11
    val HartInfo     = 0x12
    val AbstractCS   = 0x16
    val Command      = 0x17
    val AbstractAuto = 0x18
    val ProgBuf0     = 0x20
    val ProgBuf1     = 0x21
    val SBCS         = 0x38
    val SBAddress0   = 0x39
    val SBAddress1   = 0x3a
    val SBData0      = 0x3c
    val SBData1      = 0x3d
    val HaltSum0     = 0x40
    val IonCacheCtl  = 0x70
}

object DebugModuleConstants {
    // Advertise only the two instruction slots we can safely interpret today.
    // Unsupported load/store program-buffer sequences fail with cmderr instead
    // of touching architectural state.
    val AdvertisedProgBufWords = 2
    val BackingProgBufWords = 2
}
