package ooo

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Path}
import soc.core.ooo._

/** Native production backend only: exact profile, no simulation/observer wrapper. */
object AddressLocalityNativeMain extends App {
    require(args.nonEmpty, "usage: AddressLocalityNativeMain <fresh-dir> <exact profile options>")
    FpgaNextProfileOptions.validate(args.drop(1).toSeq)
    val config = FpgaNextConfig.fromOptions(args.drop(1).toSet, defaultSelected = false)
    val output = Path.of(args(0)).toAbsolutePath
    require(!Files.exists(output), "native locality output must be fresh")
    Files.createDirectories(output)
    PostedBoardConfiguration.write(config, output.toString)
    var actual: Option[Map[String, Any]] = None
    ChiselStage.emitSystemVerilogFile({
        val backend = new IntegerBackend(config.coreParams,
            canonicalHandoff = config.cache.independentDemandAdmission && config.coreParams.canonicalVirtualStoreOverlap,
            registerCanonicalStoreEvent = config.coreParams.registeredCanonicalStoreEvent)
        actual = Some(MemoryPreparationLocalityActualAudit.captureBackend(backend, config.coreParams))
        backend
    }, Array("--target-dir", output.toString),
        Array("--strip-debug-info", "--disable-all-randomization", "--default-layer-specialization=disable"))
    Files.writeString(output.resolve("actual-memory-preparation-locality.json"),
        PostedBoardConfiguration.json(actual.get) + "\n")
}
