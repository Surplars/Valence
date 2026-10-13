package ooo

import _root_.circt.stage.ChiselStage
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo.{TileLinkAxi4BurstBridge, TileLinkAxi4OutstandingBridge}

/** Actual production constructors. The generic combinational projection follows
  * emitted acceptedWindow/hazard nodes verbatim; it does not restate their logic.
  */
object ManagerRangeGeometries {
    case class Geometry(name: String, width: Int, base: BigInt, bytes: BigInt)
    val boardBase = BigInt("80200000", 16)
    val cases = Seq(
        Geometry("top32", 32, BigInt(1) << 31, BigInt(1) << 31),
        Geometry("board64", 64, boardBase, BigInt(1) << 31),
        Geometry("top64", 64, (BigInt(1) << 64) - 4096, 4096),
        Geometry("unaligned64", 64, boardBase, 4095),
        Geometry("unbounded64", 64, 0, 0))
    def makeSlot(g: Geometry, bits: Int, local: Boolean) = new TileLinkAxi4BurstBridge(
        tlParams = TLParams(addrWidth = g.width, dataWidth = 64, sourceBits = 5, sizeBits = bits),
        axiAddressWidth = math.min(g.width, 32), axiIdWidth = 4,
        maxBurstBeats = if (bits == 3) 16 else 256,
        axiAddressBase = g.base, axiWindowBytes = g.bytes,
        writeCollectionFlow = g.bytes > 0, lineReadChannel = g.bytes > 0,
        localPayloadWriteEnable = g.bytes > 0, localPayloadWriteRow = g.bytes > 0,
        localAddressRanges = local)
    def makeManager(width: Int, bits: Int, beats: Int, local: Boolean) = new TileLinkAxi4OutstandingBridge(
        tlParams = TLParams(addrWidth = width, dataWidth = 64, sourceBits = 5, sizeBits = bits),
        axiAddressWidth = math.min(width, 32), axiIdWidth = 4, maxBurstBeats = beats,
        axiCache = 0, axiProt = 0, axiQos = 0,
        axiAddressBase = if (width == 64) boardBase else BigInt(0),
        axiWindowBytes = if (width == 12) BigInt(4096) else BigInt(1) << 31,
        maxOutstanding = 4, maxOutstandingWrites = 2, unorderedResponses = true,
        writeCollectionFlow = true, lineReadChannel = true,
        localPayloadWriteEnable = true, localPayloadWriteRow = true, localAddressRanges = local)
}

class LocalAddressRangesConfigSpec extends AnyFunSuite {
    test("range option defaults off in actual manager and every slot") {
        ChiselStage.emitCHIRRTL {
            val dut = new TileLinkAxi4OutstandingBridge(
                tlParams = TLParams(addrWidth = 64), axiAddressWidth = 32, axiIdWidth = 4,
                maxBurstBeats = 16, axiCache = 0, axiProt = 0, axiQos = 0,
                axiAddressBase = 0, axiWindowBytes = BigInt(1) << 31, maxOutstanding = 4)
            assert(!dut.localAddressRanges && dut.slots.forall(!_.localAddressRanges))
            dut
        }
        ChiselStage.emitCHIRRTL {
            val dut = new TileLinkAxi4BurstBridge()
            assert(!dut.localAddressRanges)
            dut
        }
    }
    test("12-bit addresses are rejected by the existing AXI port contract") {
        for (local <- Seq(false, true)) {
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(ManagerRangeGeometries.makeManager(12, 3, 16, local))
            }
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(ManagerRangeGeometries.makeSlot(
                    ManagerRangeGeometries.Geometry("rejected12", 12, 0, 4096), 3, local))
            }
        }
    }
    test("32 64-bit constructors propagate only the range option") {
        for (width <- Seq(32, 64); local <- Seq(false, true)) {
            ChiselStage.emitCHIRRTL {
                val dut = ManagerRangeGeometries.makeManager(width, 3, 16, local)
                assert(dut.localAddressRanges == local && dut.slots.forall(_.localAddressRanges == local))
                assert(dut.localPayloadWriteEnable && dut.localPayloadWriteRow)
                assert(dut.slots.forall(s => s.localPayloadWriteEnable && s.localPayloadWriteRow))
                dut
            }
        }
    }
}

object ManagerRangeBoundarySourcesMain extends App {
    require(args.length == 1, "usage: ManagerRangeBoundarySourcesMain <target-dir>")
    val root = java.nio.file.Paths.get(args.head)
    val receipts = for (bits <- 3 to 6; g <- ManagerRangeGeometries.cases; local <- Seq(false, true)) yield {
        val relative = s"windows/${g.name}/$bits/${if (local) "on" else "off"}"
        val target = root.resolve(relative)
        java.nio.file.Files.createDirectories(target)
        ChiselStage.emitCHIRRTLFile(ManagerRangeGeometries.makeSlot(g, bits, local),
            Array("--target-dir", target.toString))
        s"""{"name":"${g.name}","addrWidth":${g.width},"sizeBits":$bits,"maxSize":${if (bits == 3) 7 else 11},"base":"${g.base}","bytes":"${g.bytes}","local":$local,"file":"$relative/TileLinkAxi4BurstBridge.fir"}"""
    }
    for (width <- Seq(32, 64); local <- Seq(false, true)) {
        val target = root.resolve(s"hazards/$width/${if (local) "on" else "off"}")
        java.nio.file.Files.createDirectories(target)
        ChiselStage.emitCHIRRTLFile(ManagerRangeGeometries.makeManager(width, 3, 16, local),
            Array("--target-dir", target.toString))
    }
    java.nio.file.Files.writeString(root.resolve("window-geometries.json"), receipts.mkString("[\n", ",\n", "\n]\n"))
}

/** Observer-free manager exports for a native dependency audit, after a grant. */
object ManagerRangeNativeMain extends App {
    require(args.length == 1, "usage: ManagerRangeNativeMain <target-dir>")
    for (beats <- Seq(8, 16, 32, 64, 128, 256); local <- Seq(false, true)) {
        val target = java.nio.file.Paths.get(args.head, beats.toString, if (local) "on" else "off")
        java.nio.file.Files.createDirectories(target)
        ChiselStage.emitCHIRRTLFile(ManagerRangeGeometries.makeManager(64, if (beats <= 16) 3 else 4, beats, local),
            Array("--target-dir", target.toString))
    }
}
