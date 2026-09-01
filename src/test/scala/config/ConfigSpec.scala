package config

import org.scalatest.funsuite.AnyFunSuite
import soc.config.{Config, DeviceTree, ISAProfiles, InitrdRange, InterruptControllerKind, MemoryBases, MemorySizes, SoCFeatures, SoCProfiles}

class ConfigSpec extends AnyFunSuite {
    test("default MMIO region order matches IonSoC slave connection order") {
        assert(Config.MMIORegions.map(_.name) == Seq("debug", "rom", "sram", "uart", "clint", "plic"))
    }

    test("reserved device regions include optional MMIO ranges") {
        assert(Config.deviceRegions.map(_.name) == Seq("debug", "rom", "uart", "clint", "plic"))
    }

    test("parameterized MMIO regions follow device feature switches") {
        assert(Config.mmioRegionsFor(SoCFeatures(uart = false, clint = true)).map(_.name) == Seq("debug", "rom", "sram", "clint", "plic"))
        assert(Config.mmioRegionsFor(SoCFeatures(uart = true, clint = false)).map(_.name) == Seq("debug", "rom", "sram", "uart", "plic"))
        assert(Config.mmioRegionsFor(SoCFeatures(uart = false, clint = false)).map(_.name) == Seq("debug", "rom", "sram", "plic"))
        assert(
            Config.mmioRegionsFor(SoCFeatures(uart = false, clint = false, interruptController = InterruptControllerKind.None)).map(_.name) ==
                Seq("debug", "rom", "sram")
        )
    }

    test("named SoC profiles describe MCU and OS-capable configurations") {
        assert(Config.mmioRegionsFor(SoCProfiles.MinimalMCU).map(_.name) == Seq("debug", "rom", "sram", "uart", "clint"))
        assert(Config.mmioRegionsFor(SoCProfiles.BareMetalMCU).map(_.name) == Seq("debug", "rom", "sram", "uart", "clint", "plic"))
        assert(!SoCProfiles.BareMetalMCU.mmu)
        assert(SoCProfiles.BareMetalMCU.iCache)
        assert(SoCProfiles.BareMetalMCU.dCache)
        assert(Config.mmioRegionsFor(SoCProfiles.LinuxCapablePLIC).map(_.name).contains("plic"))
        assert(SoCProfiles.LinuxCapablePLIC.mmu)
        assert(SoCProfiles.LinuxCapablePLIC.iCache)
        assert(SoCProfiles.LinuxCapablePLIC.dCache)
        assert(SoCProfiles.LinuxCapablePLIC.sramBase == MemoryBases.FirmwareSramBase)
        assert(SoCProfiles.LinuxCapablePLIC.sramSizeBytes == MemorySizes.FirmwareSramSize)
        assert(SoCProfiles.LinuxCapablePLIC.uart)
        assert(SoCProfiles.LinuxCapablePLIC.clint)
        assert(SoCProfiles.LinuxCapablePLIC.interruptController == InterruptControllerKind.PLIC)
        assert(SoCProfiles.LinuxBootPLIC.sramBase == MemoryBases.FirmwareSramBase)
        assert(SoCProfiles.LinuxBootPLIC.sramSizeBytes == MemorySizes.LinuxBootSramSize)
        assert(SoCProfiles.LinuxBootPLIC.mmu)
        assert(SoCProfiles.LinuxBootPLIC.iCache)
        assert(SoCProfiles.LinuxBootPLIC.dCache)
        assert(!Config.mmioRegionsFor(SoCProfiles.ModernAIA).map(_.name).contains("plic"))
        assert(SoCProfiles.ModernAIA.mmu)
    }

    test("Linux-capable device tree is generated from the SoC profile contract") {
        val dts = DeviceTree.linuxCapableDts()

        assert(dts.contains("""riscv,isa = "rv64imac_zicsr_zifencei_zba_zbb_zbs";"""))
        assert(dts.contains("""mmu-type = "riscv,sv39";"""))
        assert(dts.contains("memory@40000000"))
        assert(dts.contains("reg = <0x00000000 0x40000000 0x00000000 0x01000000>;"))
        assert(dts.contains("uart@10010000"))
        assert(dts.contains("""compatible = "openion,ionsoc-uart", "ns16550a";"""))
        assert(dts.contains("clint@2000000"))
        assert(dts.contains("interrupt-controller@c000000"))
        assert(dts.contains("riscv,ndev = <31>;"))
    }

    test("Linux boot profile exposes a larger DTB-visible memory map") {
        val dts = DeviceTree.linuxBootDts()

        assert(dts.contains("memory@40000000"))
        assert(dts.contains("reg = <0x00000000 0x40000000 0x00000000 0x08000000>;"))
        assert(dts.contains("""mmu-type = "riscv,sv39";"""))
        assert(dts.contains("""bootargs = "console=ttyS0,115200 earlycon=uart8250,mmio,0x10010000";"""))
        assert(dts.contains("""compatible = "openion,ionsoc-uart", "ns16550a";"""))
        assert(dts.contains("reg-shift = <0>;"))
        assert(dts.contains("reg-io-width = <1>;"))
        assert(dts.contains("interrupt-controller@c000000"))
    }

    test("Linux boot device tree can append extra bootargs") {
        val dts = DeviceTree.linuxBootDts("mem=32M")

        assert(dts.contains("""bootargs = "console=ttyS0,115200 earlycon=uart8250,mmio,0x10010000 mem=32M";"""))
    }

    test("Linux boot device tree describes an external initramfs") {
        val dts = DeviceTree.linuxBootDts("", Some(InitrdRange(BigInt("47000000", 16), BigInt("47012000", 16))))

        assert(dts.contains("rdinit=/init"))
        assert(dts.contains("linux,initrd-start = <0x00000000 0x47000000>;"))
        assert(dts.contains("linux,initrd-end = <0x00000000 0x47012000>;"))
    }

    test("ISA profiles keep the MCU baseline at RV64IMAC plus privileged support") {
        assert(ISAProfiles.RV64IMAC.contains(soc.isa.Extension.RV64I))
        assert(ISAProfiles.RV64IMAC.contains(soc.isa.Extension.RV64M))
        assert(ISAProfiles.RV64IMAC.contains(soc.isa.Extension.RV64A))
        assert(ISAProfiles.RV64IMAC.contains(soc.isa.Extension.C))
        assert(ISAProfiles.RV64IMAC.contains(soc.isa.Extension.Zicsr))
        assert(ISAProfiles.RV64IMAC.contains(soc.isa.Extension.Zifencei))
        assert(ISAProfiles.RV64IMAC.contains(soc.isa.Extension.S))
        assert(!ISAProfiles.RV64IMAC.contains(soc.isa.Extension.Zba))
        assert(ISAProfiles.RV64IMACB.contains(soc.isa.Extension.Zba))
        assert(ISAProfiles.RV64IMACB.contains(soc.isa.Extension.Zbb))
        assert(ISAProfiles.RV64IMACB.contains(soc.isa.Extension.Zbs))
    }
}
