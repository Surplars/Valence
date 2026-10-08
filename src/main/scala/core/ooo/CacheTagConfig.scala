package soc.core.ooo

import chisel3._

/** Storage policy only: all request, coherence and backing addresses remain full width. */
case class CacheTagConfig(compact: Boolean = false) {
    def geometry(base: BigInt, bytes: BigInt, tagLow: Int, addressWidth: Int = 64): CacheTagGeometry =
        CacheTagGeometry(base, bytes, tagLow, addressWidth, compact)
}

object CacheTagConfig {
    val FullWidth: CacheTagConfig = CacheTagConfig()
    val Aperture: CacheTagConfig = CacheTagConfig(compact = true)
}

/** Absolute low-bit tags. Range qualification is mandatory before authorizing a hit. */
case class CacheTagGeometry(base: BigInt, bytes: BigInt, tagLow: Int, addressWidth: Int, compact: Boolean) {
    require(addressWidth >= 7 && addressWidth <= 64 && tagLow >= 6 && tagLow < addressWidth)
    require(base >= 0 && bytes >= 64 && base % 64 == 0 && bytes % 64 == 0 &&
        base + bytes <= (BigInt(1) << addressWidth), "invalid cache tag aperture")
    val retainedBits: Int = if (compact) math.max(tagLow + 1, (base + bytes - 1).bitLength) else addressWidth
    val tagBits: Int = retainedBits - tagLow
    def tag(address: UInt): UInt = address(retainedBits - 1, tagLow)
    def contains(address: UInt): Bool = {
        require(address.getWidth >= addressWidth && address.getWidth <= 64,
            "tag qualification must not receive a narrowed address")
        // Reuse the exact static-prefix aperture decoder: no new runtime
        // address addition/carry chain is introduced on the hit/probe path.
        if (address.getWidth >= 32) HomeRamRange.contains(address, address.getWidth, base, bytes)
        else address >= base.U((address.getWidth + 1).W) &&
            address < (base + bytes).U((address.getWidth + 1).W)
    }
    def qualifies(address: UInt): Bool = if (compact) contains(address) else true.B
    def widen(address: UInt): UInt = address.pad(addressWidth)
}
