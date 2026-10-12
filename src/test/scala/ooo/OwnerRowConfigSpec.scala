package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import soc.bus.tilelink.TLParams
import soc.core.ooo._

/** Source-candidate constructor gates; these do not qualify behavior or physical timing. */
class OwnerRowConfigSpec extends AnyFunSuite {
    private val ownerFlag = "--shared-canonical-store-owner-match"
    private val rowFlag = "--local-payload-write-row"
    private val baseOptions = Seq(
        "--selected", "--data-translation-entries=16", "--registered-pmp-regions",
        "--experimental-trispeed-ethernet", "--experimental-jtag-bscan=2", "--dma-line-transfers",
        "--dma-line-entries=4", "--prefetch-candidate-cycles=16", "--virtual-ram-load-precheck",
        "--lsu-entries=4", "--physical-load-ingress-flow", "--ddr-write-collection-flow",
        "--line-transfer-dispatch-flow", "--line-read-channel", "--dtlb-write-read-reuse",
        "--translation-hit-flow", "--independent-demand-admission", "--split-prefetch-tracking",
        "--read-prefetch-dirty-retry", "--read-prefetch-demand-adoption", "--load-order-older-retire",
        "--fetch-previous-packet", "--prepared-store-lookahead", "--store-next-line-prefetch",
        "--store-prefetch-mru-insertion", "--posted-store-merge", "--posted-prefetch-coexistence",
        "--posted-prefetch-head-offer", "--canonical-virtual-store-overlap", "--published-pmp-changes",
        "--frozen-store-proof-transport", "--pending-virtual-store-proof", "--pending-virtual-store-proof-slots=2",
        "--bound-head-store-overlap", "--read-prefetch-store-hold", "--pending-ready-store-bypass",
        "--durable-read-prefetch-candidate", "--read-prefetch-behind-store", "--pending-store-early-load-credits=2",
        "--tagged-store-returns", "--internal-line-grant", "--concurrent-read-store-prefetch",
        "--memory-schedule-overlap", "--registered-pending-store-query", "--aligned-fetch-permission-stage",
        "--registered-canonical-store-event", "--shared-lane1-owner-match", "--direct-rank1-memory-source-ids",
        "--direct-registered-execution-operands", "--local-payload-write-enable")
    private val off = FpgaNextConfig.fromOptions(baseOptions.toSet, defaultSelected = false)
    private val on = FpgaNextConfig.fromOptions((baseOptions ++ Seq(ownerFlag, rowFlag)).toSet,
        defaultSelected = false)

    private val projectRoot = Iterator.iterate(Paths.get("").toAbsolutePath)(_.getParent)
        .takeWhile(_ != null).find(path => Files.isRegularFile(path.resolve("build.mill")))
        .getOrElse(throw new IllegalStateException("repository build.mill was not found above the test directory"))

    private def manifestOptions(name: String): Seq[String] = {
        val text = Files.readString(projectRoot.resolve(Paths.get("fpga", "next", name)))
        val list = "(?s)\"native_options\"\\s*:\\s*\\[(.*?)\\]".r.findFirstMatchIn(text).get.group(1)
        "\"([^\"]*)\"".r.findAllMatchIn(list).map(_.group(1)).toSeq
    }

    private def unique[T](instance: AnyRef, kind: Class[T]): T = {
        val fields = scala.collection.mutable.ArrayBuffer.empty[java.lang.reflect.Field]
        var declaring: Class[_] = instance.getClass
        while (declaring != null) {
            fields ++= declaring.getDeclaredFields.filter(field =>
                !java.lang.reflect.Modifier.isStatic(field.getModifiers) && field.getType == kind)
            declaring = declaring.getSuperclass
        }
        require(fields.size == 1, "actual constructor field absent or ambiguous: " + kind.getName)
        fields.head.setAccessible(true)
        kind.cast(fields.head.get(instance))
    }

    test("new fields append to every product and remain off in all generic presets") {
        assert(OooParams().productArity == 158 && !OooParams().sharedCanonicalStoreOwnerMatch)
        assert(OooParams().productElementName(157) == "sharedCanonicalStoreOwnerMatch")
        for (ddr <- Seq(DdrBridgeConfig.Legacy, DdrBridgeConfig.ReadOverlap4)) {
            assert(ddr.productArity == 9 && !ddr.localPayloadWriteRow)
            assert(ddr.productElementName(8) == "localPayloadWriteRow")
        }
        for (base <- Seq(FpgaNextConfig.Reference, FpgaNextConfig.Candidate, FpgaNextConfig.Selected, off)) {
            assert(base.productArity == 70 && base.coreParams.productArity == 158 &&
                base.ddr.productArity == 9 && base.cache.productArity == 22)
            assert(base.productElementName(68) == "sharedCanonicalStoreOwnerMatch" &&
                base.productElementName(69) == "localPayloadWriteRow")
            assert(!base.sharedCanonicalStoreOwnerMatch && !base.coreParams.sharedCanonicalStoreOwnerMatch &&
                !base.localPayloadWriteRow && !base.ddr.localPayloadWriteRow)
        }
    }

    test("each independent ON and the combined ON roll back to the exact fifty-option profile") {
        assert(baseOptions.size == 50 && baseOptions.distinct.size == 50)
        for (owner <- Seq(false, true); row <- Seq(false, true)) {
            val options = baseOptions ++ (if (owner) Seq(ownerFlag) else Seq.empty) ++
                (if (row) Seq(rowFlag) else Seq.empty)
            FpgaNextProfileOptions.validate(options)
            val selected = FpgaNextConfig.fromOptions(options.toSet, defaultSelected = false)
            assert(selected.sharedCanonicalStoreOwnerMatch == owner &&
                selected.coreParams.sharedCanonicalStoreOwnerMatch == owner)
            assert(selected.localPayloadWriteRow == row && selected.ddr.localPayloadWriteRow == row)
            assert(selected.copy(sharedCanonicalStoreOwnerMatch = false, localPayloadWriteRow = false) == off)
            assert(selected.coreParams.copy(sharedCanonicalStoreOwnerMatch = false) == off.coreParams)
            assert(selected.ddr.copy(localPayloadWriteRow = false) == off.ddr)
            assert(selected.cache == off.cache && selected.storage == off.storage && selected.network == off.network)
            assert(selected.issueWidth == 2 && selected.coreParams.robEntries == 16 &&
                selected.coreParams.physicalRegs == 48 && selected.coreParams.memoryEntries == 4 &&
                selected.ddr.maxOutstanding == 4 && selected.ddr.maxOutstandingWrites == 2 &&
                selected.ddr.maxBurstBeats == 16)
        }
        assert(manifestOptions("timing-batch-zero-cycle-cleanup-profile.json") == baseOptions)
        assert(manifestOptions("timing-batch-owner-row-profile.json") == baseOptions ++ Seq(ownerFlag, rowFlag))
        val candidate = Files.readString(projectRoot.resolve(Paths.get("fpga", "next", "timing-batch-owner-row-profile.json")))
        assert(candidate.contains("\"native_option_count\": 52"))
        assert(candidate.contains("\"status\": \"SOURCE_CANDIDATE_UNQUALIFIED\""))
        assert(!candidate.contains("receipt_sha256") && !candidate.contains("inclusive_cycles"))
    }

    test("both Boolean CLI options reject duplicate valued and misspelled forms") {
        for (flag <- Seq(ownerFlag, rowFlag)) {
            FpgaNextProfileOptions.validate(baseOptions :+ flag)
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(baseOptions ++ Seq(flag, flag)) }
            for (value <- Seq("", "true", "false", "0", "1")) {
                intercept[IllegalArgumentException] {
                    FpgaNextProfileOptions.validate(baseOptions :+ (flag + "=" + value))
                }
                intercept[IllegalArgumentException] {
                    FpgaNextConfig.fromOptions(baseOptions.toSet + (flag + "=" + value), false)
                }
            }
            intercept[IllegalArgumentException] { FpgaNextProfileOptions.validate(baseOptions :+ (flag + "s")) }
        }
    }

    test("canonical owner and local payload row reject every missing prerequisite") {
        intercept[IllegalArgumentException] { OooParams(sharedCanonicalStoreOwnerMatch = true) }
        intercept[IllegalArgumentException] { FpgaNextConfig(sharedCanonicalStoreOwnerMatch = true) }
        val canonical = FpgaNextConfig.Selected.copy(virtualRamLoadPrecheck = true,
            canonicalVirtualStoreOverlap = true, sharedCanonicalStoreOwnerMatch = true)
        assert(canonical.coreParams.sharedCanonicalStoreOwnerMatch)
        intercept[IllegalArgumentException] { canonical.copy(canonicalVirtualStoreOverlap = false) }
        intercept[IllegalArgumentException] { canonical.coreParams.copy(canonicalVirtualStoreOverlap = false) }
        for ((line, local) <- Seq((false, false), (false, true), (true, false))) {
            intercept[IllegalArgumentException] {
                off.copy(localPayloadWriteRow = true, lineReadChannel = line, localPayloadWriteEnable = local)
            }
            intercept[IllegalArgumentException] {
                off.ddr.copy(localPayloadWriteRow = true, lineReadChannel = line, localPayloadWriteEnable = local)
            }
            intercept[IllegalArgumentException] {
                ChiselStage.emitCHIRRTL(new TileLinkAxi4BurstBridge(
                    tlParams = TLParams(addrWidth = 64, sourceBits = 5), axiAddressWidth = 32, axiIdWidth = 4,
                    axiAddressBase = BigInt("80200000", 16), axiWindowBytes = BigInt(1) << 31,
                    lineReadChannel = line, localPayloadWriteEnable = local, localPayloadWriteRow = true))
            }
        }
    }

    test("generic local-row bridge preserves all legal eight through 256 beat geometries") {
        for (beats <- Seq(8, 16, 32, 64, 128, 256)) {
            val tl = TLParams(addrWidth = 64, dataWidth = 64, sourceBits = 5,
                sizeBits = if (beats <= 16) 3 else 4)
            val config = on.ddr.copy(maxBurstBeats = beats)
            config.validateTileLink(tl)
            if (beats <= 16) config.validateSoc()
            else intercept[IllegalArgumentException] { config.validateSoc() }
            var inspected = false
            ChiselStage.emitCHIRRTL {
                val bridge = new TileLinkAxi4Bridge(tlParams = tl, axiAddressWidth = 32, axiIdWidth = 4,
                    maxBurstBeats = beats, axiAddressBase = BigInt("80200000", 16),
                    axiWindowBytes = BigInt(1) << 31, maxOutstanding = 4, maxOutstandingWrites = 2,
                    unorderedResponses = true, writeCollectionFlow = true, lineReadChannel = true,
                    localPayloadWriteEnable = true, localPayloadWriteRow = true)
                val manager = bridge.outstandingInstance.get
                assert(bridge.localPayloadWriteRow && manager.localPayloadWriteRow && manager.slots.size == 4)
                assert(manager.maxBurstBeats == beats && manager.tlParams == tl)
                manager.slots.foreach { slot =>
                    assert(slot.localPayloadWriteRow && slot.localPayloadWriteEnable && slot.lineReadChannel)
                    assert(slot.maxBurstBeats == beats && slot.tlParams == tl && slot.payloadBanks.size == 8)
                    assert(slot.io.lineData.get.getWidth == 512 && slot.io.lineMode.nonEmpty)
                }
                inspected = true
                bridge
            }
            assert(inspected)
        }
    }

    test("actual native and GSIM constructors preserve the complete combined optional profile") {
        var native = Map.empty[String, Any]
        ChiselStage.emitCHIRRTL {
            val board = on.managedBoard(jtagRamDownload = true)
            native = OwnerRowActualAudit.capture(board.platform, on)
            board
        }
        var gsim = Map.empty[String, Any]
        ChiselStage.emitCHIRRTL {
            val top = FpgaNextBoardGsim.build(on, verifyConfiguration = true)
            val board = unique(top, classOf[MatchingManagedBoard])
            val p = board.platform.core.core.core.p
            assert(p == on.coreParams && p.directRank1MemorySourceIds && p.directRegisteredExecutionOperands &&
                p.sharedCanonicalStoreOwnerMatch && p.registeredIssueExecute && p.canonicalVirtualStoreOverlap)
            gsim = OwnerRowActualAudit.capture(board.platform, on)
            top
        }
        assert(native.nonEmpty && gsim == native)
        assert(native.keySet == Set("schema", "sharedCanonicalStoreOwnerMatch", "canonicalVirtualStoreOverlap",
            "wrapper", "manager", "slotCount", "slots"))
        val expectedFlags: Map[String, Any] = Map("localPayloadWriteRow" -> true,
            "localPayloadWriteEnable" -> true, "lineReadChannel" -> true)
        assert(native("schema") == "actual-owner-row-v1" && native("sharedCanonicalStoreOwnerMatch") == true &&
            native("canonicalVirtualStoreOverlap") == true && native("slotCount") == 4)
        assert(native("wrapper") == expectedFlags && native("manager") == expectedFlags &&
            native("slots") == Seq.fill(4)(expectedFlags))
    }
}
