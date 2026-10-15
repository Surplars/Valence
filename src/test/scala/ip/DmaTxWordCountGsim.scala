package ip

import _root_.circt.stage.ChiselStage
import java.nio.file.{Files, Paths}
import soc.ip.dma.EthernetPacketDma

/** Exact same matrix for the source-pinned baseline and word-count candidate. */
object DmaTxWordCountGsimMain extends App {
    require(args.length == 1)
    val root = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(root), "preserve prior matrix evidence")
    Files.createDirectories(root)
    val geometries = for (frame <- Seq(64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384);
        posted <- Seq(0, 4)) yield (s"m$frame-p$posted", frame, posted, BigInt("80200000", 16))
    val high = Seq(("m2048-p4-high", 2048, 4, BigInt("100200000", 16)))
    for ((name, frame, posted, base) <- geometries ++ high) {
        val out = root.resolve(name)
        ChiselStage.emitCHIRRTLFile(new EthernetPacketDma(ramBase = base, ramBytes = 65536,
            maxFrameBytes = frame, postedRxSlots = 4, memoryCredits = 4, postedTxSlots = posted),
            Array("--target-dir", out.toString))
    }
    println("PASS_TX_WORD_COUNT_MATRIX_EMIT geometries=9 posted_modes=2 high_address=1")
}
