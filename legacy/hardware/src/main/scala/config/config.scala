package soc.config

import chisel3._

import soc.isa.Extension

object InterruptControllerKind extends Enumeration {
    val None, PLIC, AIA = Value
}

object MemorySizes {
    val DefaultSramSize: Int = 0x10000
    val FirmwareSramSize: Int = 0x01000000
    val LinuxBootSramSize: Int = 0x08000000
}

object MemoryBases {
    val DefaultSramBase: BigInt = 0x10000000L
    val FirmwareSramBase: BigInt = 0x40000000L
}

object ISAProfiles {
    // Baseline MCU ISA: RV64IMAC plus the privileged/CSR pieces required by
    // bare-metal firmware and SBI-style supervisor handoff.
    val RV64IMAC: Set[Extension.Value] = Set(
        Extension.RV64I,
        Extension.Zicsr,
        Extension.Zifencei,
        Extension.S,
        Extension.C,
        Extension.RV64M,
        Extension.RV64A
    )

    // Default bring-up ISA keeps a small bitmanip subset enabled so the same
    // core can run compiler-generated embedded code without changing profiles.
    val RV64IMACB: Set[Extension.Value] = RV64IMAC ++ Set(
        Extension.Zba,
        Extension.Zbb,
        Extension.Zbs
    )
}

case class SoCFeatures(
    mmu: Boolean = false,
    iCache: Boolean = false,
    dCache: Boolean = true,
    // Cache transport mode is a platform contract, not a cache-size detail.
    // Single-core MCU/firmware profiles use TL-UL-style Get/Put traffic; future
    // multicore profiles can enable TL-C once a full coherence manager is used.
    coherentCaches: Boolean = false,
    iCacheSets: Int = 256,
    dCacheSets: Int = 256,
    frontendQueueEntries: Int = 4,
    sramBase: BigInt = MemoryBases.DefaultSramBase,
    sramSizeBytes: Int = MemorySizes.DefaultSramSize,
    uart: Boolean = true,
    clint: Boolean = true,
    interruptController: InterruptControllerKind.Value = InterruptControllerKind.PLIC
)

object SoCProfiles {
    // Smallest useful profile for smoke tests: no caches and no external
    // interrupt controller. Keep this available for fast direct-fetch tests.
    val MinimalMCU: SoCFeatures = SoCFeatures(
        mmu = false,
        iCache = false,
        dCache = false,
        uart = true,
        clint = true,
        interruptController = InterruptControllerKind.None
    )

    // Fixed MCU profile for the default build: no MMU, but keep the platform
    // devices expected by embedded firmware and RustSBI/OpenSBI-style probing.
    val BareMetalMCU: SoCFeatures = SoCFeatures(
        mmu = false,
        iCache = true,
        dCache = true,
        sramBase = MemoryBases.DefaultSramBase,
        sramSizeBytes = MemorySizes.DefaultSramSize,
        uart = true,
        clint = true,
        interruptController = InterruptControllerKind.PLIC
    )

    // Large-SRAM firmware profile for SBI/Linux bring-up: Sv39 MMU, caches,
    // CLINT, PLIC, UART, and a larger SRAM window for firmware plus payload.
    val LinuxCapablePLIC: SoCFeatures = SoCFeatures(
        mmu = true,
        iCache = true,
        dCache = true,
        sramBase = MemoryBases.FirmwareSramBase,
        sramSizeBytes = MemorySizes.FirmwareSramSize,
        uart = true,
        clint = true,
        interruptController = InterruptControllerKind.PLIC
    )

    // Linux boot profile keeps the same device contract as firmware smoke, but
    // uses enough RAM for a small kernel/initramfs bring-up path.
    val LinuxBootPLIC: SoCFeatures = LinuxCapablePLIC.copy(
        sramSizeBytes = MemorySizes.LinuxBootSramSize
    )

    val ModernAIA: SoCFeatures = LinuxBootPLIC.copy(interruptController = InterruptControllerKind.AIA)

    val CoherentMulticorePreview: SoCFeatures = LinuxBootPLIC.copy(coherentCaches = true)
}

case class AddressRegion(name: String, base: BigInt, size: BigInt) {
    def contains(addr: UInt, addrWidth: Int): Bool = {
        addr >= base.U(addrWidth.W) && addr < (base + size).U(addrWidth.W)
    }
}

object Config {
    val XLEN: Int                        = 64
    // Repository default is now the MCU contract. More advanced SoC profiles
    // are selected explicitly by simulation emission targets.
    val enabledExt: Set[Extension.Value] = ISAProfiles.RV64IMACB
    val features: SoCFeatures            = SoCProfiles.BareMetalMCU

    val DebugBase: BigInt = 0x00000000L
    val DebugSize: BigInt = 0x4000L
    val RomBase: BigInt   = 0x80000000L
    val RomSize: BigInt   = 0x20000L
    val SramBase: BigInt  = MemoryBases.DefaultSramBase
    val DefaultSramSize: Int = MemorySizes.DefaultSramSize  // 64 KB
    val FirmwareSramSize: Int = MemorySizes.FirmwareSramSize // 16 MB, enough for SBI firmware + payload smoke tests.
    val LinuxBootSramSize: Int = MemorySizes.LinuxBootSramSize // 128 MB, enough for small Linux bring-up images.
    val SramSize: BigInt  = DefaultSramSize
    val UartBase: BigInt  = 0x10010000L // after SRAM region
    val UartSize: BigInt  = 0x1000L
    val ClintBase: BigInt = 0x2000000L  // CLINT base
    val ClintSize: BigInt = 0x10000L    // 64 KB
    val PlicBase: BigInt  = 0x0c000000L
    val PlicSize: BigInt  = 0x4000000L  // standard PLIC aperture
    val plicSources: Int  = 31
    val UartPlicSource: Int = 1

    val romDepth: Int     = 16384 // 16 KB
    val ramDepth: Int     = DefaultSramSize
    val ramDataBytes: Int = XLEN / 8
    val romInit: Seq[Int] = Seq.fill(romDepth)(0)

    val resetVector: BigInt = RomBase

    val DebugRegion: AddressRegion = AddressRegion("debug", DebugBase, DebugSize)
    val RomRegion: AddressRegion   = AddressRegion("rom", RomBase, RomSize)
    val SramRegion: AddressRegion  = AddressRegion("sram", SramBase, SramSize)
    val UartRegion: AddressRegion  = AddressRegion("uart", UartBase, UartSize)
    val ClintRegion: AddressRegion = AddressRegion("clint", ClintBase, ClintSize)
    val PlicRegion: AddressRegion  = AddressRegion("plic", PlicBase, PlicSize)

    def sramRegionFor(features: SoCFeatures): AddressRegion =
        AddressRegion("sram", features.sramBase, BigInt(features.sramSizeBytes))
    def alwaysOnRegionsFor(features: SoCFeatures): Seq[AddressRegion] =
        Seq(DebugRegion, RomRegion, sramRegionFor(features))
    val alwaysOnRegions: Seq[AddressRegion]                           = Seq(DebugRegion, RomRegion, SramRegion)
    def optionalRegionsFor(features: SoCFeatures): Seq[AddressRegion] =
        Seq(
            Option.when(features.uart)(UartRegion),
            Option.when(features.clint)(ClintRegion),
            Option.when(features.interruptController == InterruptControllerKind.PLIC)(PlicRegion)
        ).flatten

    def mmioRegionsFor(features: SoCFeatures): Seq[AddressRegion] = alwaysOnRegionsFor(features) ++ optionalRegionsFor(features)
    def mmioMapFor(features: SoCFeatures): Seq[(BigInt, BigInt)]  =
        mmioRegionsFor(features).map(region => (region.base, region.size))
    def addrMapFor(features: SoCFeatures): Seq[UInt => Bool] = mkAddrMap(mmioRegionsFor(features), XLEN)
    def releaseSupportFor(features: SoCFeatures): Seq[Boolean] =
        mmioRegionsFor(features).map(region => features.coherentCaches && region.name == "sram")

    val optionalRegions: Seq[AddressRegion] = optionalRegionsFor(features)
    val MMIORegions: Seq[AddressRegion]     = alwaysOnRegions ++ optionalRegions
    val MMIOMap: Seq[(BigInt, BigInt)]      = MMIORegions.map(region => (region.base, region.size))
    val addrMap: Seq[UInt => Bool]          = mkAddrMap(MMIORegions, XLEN)

    // Reserved MMIO ranges remain device/uncached even when the device is not
    // instantiated, so accesses reach TLXbar and receive a denied response.
    val deviceRegions: Seq[AddressRegion] = Seq(DebugRegion, RomRegion, UartRegion, ClintRegion, PlicRegion)

    private def mkAddrMap(ranges: Seq[AddressRegion], addrWidth: Int): Seq[UInt => Bool] = {
        ranges.map(region => (addr: UInt) => region.contains(addr, addrWidth))
    }

}
