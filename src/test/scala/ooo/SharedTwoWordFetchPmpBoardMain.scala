package ooo

import _root_.circt.stage.ChiselStage
import chisel3.experimental.{BaseModule, IntParam}
import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import soc.core.ooo._
import soc.ip.debug.{BscanRamTransport, JtagDebugReservation}
import soc.ip.ethernet.TriSpeedManagedGmac

/** Independent experimental CHIRRTL export. No frozen manifest is relabeled as
  * candidate evidence. No Verilog, simulator, physical recipe or implementation.
  */
object SharedTwoWordFetchPmpBoardMain extends App {
    require(args.length == 2 && Set("default", "off", "on").contains(args(1)),
        "fresh output directory and explicit default/off/on experiment mode required")
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "fresh output directory required")
    val mode = args(1)
    val enabled = mode == "on"
    val c = ThreeProofRowNativeProfile.config
    require(c.productArity == 95 && c.coreParams.productArity == 178)
    require(c.coreParams.alignedFetchSinglePage && c.coreParams.alignedFetchPmp && c.coreParams.pmpEntries == 16)
    var built: Option[FpgaNextSocTop] = None
    val fir = ChiselStage.emitCHIRRTL {
        val dut = if (mode == "default") ThreeProofRowNativeProfile.construct() else
            new FpgaNextSocTop(config = c, debug = ThreeProofRowNativeProfile.debug,
                bscanChain = ThreeProofRowNativeProfile.bscanChain, sharedTwoWordFetchPmp = enabled)
        built = Some(dut)
        dut
    }
    val dut = built.get
    def children(m: BaseModule): Seq[BaseModule] =
        classOf[BaseModule].getMethod("getIds").invoke(m).asInstanceOf[scala.collection.Iterable[_]]
            .collect { case x: BaseModule => x }.toSeq
    def descendants(m: BaseModule): Seq[BaseModule] = m +: children(m).flatMap(descendants)
    val modules = descendants(dut).distinct
    val helpers = modules.collect { case m: SharedTwoWordFetchPmp => m }
    require(helpers.size == (if (enabled) 2 else 0), "actual board helper count differs")
    require(dut.sharedTwoWordFetchPmp == enabled && dut.board.sharedTwoWordFetchPmp == enabled &&
        dut.board.platform.sharedTwoWordFetchPmp == enabled)
    require(dut.board.platform.frontend.sharedTwoWordFetchPmp == enabled)
    val adapters = modules.collect { case m: InstructionTranslationAdapter => m }
    require(adapters.size == 1 && adapters.head.sharedTwoWordFetchPmp == enabled)
    require(dut.board.platform.core.core.core.p == c.coreParams, "actual complete core product changed")
    val caches = modules.collect { case m: NonBlockingCoherentLineCache => m }
    require(caches.size == 1 && !caches.head.splitCacheableBounds, "cache range candidate must remain disabled")
    val macs = modules.collect { case m: TriSpeedManagedGmac => m }
    val scans = modules.collect { case m: BscanRamTransport => m }
    require(macs.size == 1 && dut.board.triSpeedRawClockHandoff)
    require(scans.size == 1 && scans.head.params ==
        Map("ENABLE" -> IntParam(BigInt(1)), "JTAG_CHAIN" -> IntParam(BigInt(2))))
    require(!modules.exists(_.isInstanceOf[JtagDebugReservation]) && dut.board.platform.jtagLoader.nonEmpty)
    Files.createDirectories(out)
    Files.writeString(out.resolve("FpgaNextSocTop.fir"), fir)
    // Full hardware IR comparison excludes ONLY source-location metadata.
    val hardware = fir.replaceAll(" @\\[[^\\n]*?\\]", "")
    Files.writeString(out.resolve("FpgaNextSocTop.hardware.fir"), hardware)
    def hash(s: String): String = MessageDigest.getInstance("SHA-256")
        .digest(s.getBytes(java.nio.charset.StandardCharsets.UTF_8)).map(b => f"${b & 255}%02x").mkString
    Files.writeString(out.resolve("experiment.json"), ujson.Obj(
        "schema" -> "experimental-shared-two-word-fetch-pmp-board-v1",
        "mode" -> mode, "sharedTwoWordFetchPmp" -> enabled, "actualHelperInstances" -> helpers.size,
        "configurationBasis" -> "explicit ThreeProofRowNativeProfile constructor; not inherited qualification",
        "coreFields" -> c.coreParams.productArity, "profileFields" -> c.productArity,
        "core" -> ujson.read(PostedBoardConfiguration.json(c.coreParams)),
        "profile" -> ujson.read(PostedBoardConfiguration.json(c)),
        "fieldOrder" -> ujson.Obj(
            "core" -> ujson.Arr.from(c.coreParams.productElementNames),
            "profile" -> ujson.Arr.from(c.productElementNames)),
        "actualNativeMacInstances" -> macs.size, "actualBscanInstances" -> scans.size,
        "actualBscanChain" -> 2, "actualRamLoaderPresent" -> true,
        "actualCacheRangeCandidate" -> false, "rawChirrtlSha256" -> hash(fir),
        "hardwareChirrtlSha256" -> hash(hardware), "callerBehaviorQualified" -> false,
        "physicalQualification" -> false).render(indent = 2) + "\n")
    println(s"PASS_EXPERIMENTAL_SHARED_TWO_WORD_BOARD mode=$mode helpers=${helpers.size} core=178 profile=95 CHIRRTL_ONLY")
}
