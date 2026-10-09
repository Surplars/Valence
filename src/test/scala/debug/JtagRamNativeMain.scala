package debug

import _root_.circt.stage.ChiselStage
import java.nio.charset.StandardCharsets
import java.nio.file.{Files, Paths}
import java.security.MessageDigest
import soc.ip.debug.JtagRamLoader

/** Source-bound endpoint fixture for native independent-clock reset/drain tests.
  * Export only; no simulator, FPGA implementation or hardware invocation.
  */
object JtagRamNativeMain extends App {
    require(args.length == 1, "usage: debug.JtagRamNativeMain fresh-output-directory")
    val out = Paths.get(args(0)).toAbsolutePath
    require(!Files.exists(out), "refusing existing native fixture output")
    val sources = Seq("build.mill", ".mill-version", "src/main/scala/ip/debug/JtagRamLoader.scala",
        "src/main/scala/ip/debug/JtagDebugReservation.scala", "src/main/scala/ip/bus/RegisterPort.scala",
        "src/test/scala/debug/JtagRamNativeMain.scala")
    def sha(path: java.nio.file.Path): String = MessageDigest.getInstance("SHA-256")
        .digest(Files.readAllBytes(path)).map(b => f"${b & 0xff}%02x").mkString
    def bindings = sources.map(p => p -> sha(Paths.get(p))).toMap
    val before = bindings
    ChiselStage.emitSystemVerilogFile(new JtagRamLoader(BigInt("80200000", 16),
        BigInt("80201000", 16), timeoutCycles = 64), Array("--target-dir", out.toString),
        Array("--disable-all-randomization", "--strip-debug-info"))
    require(before == bindings, "source changed during native fixture export")
    val hashes = before.toSeq.sortBy(_._1).map { case (p, h) => s"\"$p\":\"$h\"" }.mkString(",")
    val text = s"""{"schema":"valence-native-loader-v1","status":"RTL_EXPORTED_NOT_SIMULATED",
        |"timeout_cycles":64,"ram_base":"0x80200000","ram_end":"0x80201000",
        |"source_sha256":{$hashes},"rtl_sha256":"${sha(out.resolve("JtagRamLoader.sv"))}"}
        |""".stripMargin
    Files.write(out.resolve("native-loader.json"), text.getBytes(StandardCharsets.UTF_8))
}
