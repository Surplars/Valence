package ooo

import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import soc.core.ooo._
import java.nio.file.{Files, Path}
import java.nio.charset.StandardCharsets

class FpgaRomTop(words: Int) extends Module {
    private val p = OooParams()
    val io        = IO(new Bundle {
        val memory       = new DataPort
        val commitEnable = Input(Bool())
        val commit       = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val exception    = Output(Valid(new HeadException(p)))
    })
    val core = Module(new FpgaIntegerCore(p))
    val rom  = Module(new InstructionRom(words, BigInt("80000000", 16), Seq("rom_even.hex", "rom_odd.hex")))
    rom.io.fetch <> core.io.fetch
    io.memory <> core.io.memory
    core.io.commitEnable := io.commitEnable
    io.commit            := core.io.commit
    io.exception         := core.io.exception
}

class FpgaPlatformTop(words: Int) extends Module {
    private val p =
        OooParams(speculativeRamBase = BigInt("80010000", 16), speculativeRamBytes = 4096, bufferedRamStores = true)
    val io = IO(new Bundle {
        val commitEnable = Input(Bool())
        val commit       = Output(Vec(p.commitWidth, Valid(new CommitRecord(p))))
        val exception    = Output(Valid(new HeadException(p)))
        val memoryBusy   = Output(Bool())
        val fetchWait    = Output(Bool())
    })
    val core = Module(new FpgaIntegerCore(p))
    val rom  = Module(new InstructionRom(words, BigInt("80000000", 16), Seq("rom_even.hex", "rom_odd.hex")))
    val ram  = Module(new SynchronousDataRam(initFile = "ram_zero.hex"))
    rom.io.fetch <> core.io.fetch
    ram.io.port <> core.io.memory
    core.io.commitEnable := io.commitEnable
    io.commit            := core.io.commit
    io.exception         := core.io.exception
    io.memoryBusy        := core.io.memoryBusy || ram.io.busy
    io.fetchWait         := core.io.fetchWait
}

/** Export an IP-level timing experiment, not a board bitstream or complete SoC. */
object FpgaRomMain extends App {
    require(args.length >= 2, "usage: FpgaRomMain output-directory RV64I-binary [ROM-words]")
    val output = Path.of(args(0)).toAbsolutePath
    val bytes  = Files.readAllBytes(Path.of(args(1)))
    val words  = args.lift(2).map(_.toInt).getOrElse(4096)
    val mode   = args.lift(3).getOrElse("external")
    require(Set("external", "platform").contains(mode))
    require(words >= 4 && (words & (words - 1)) == 0)
    require(bytes.nonEmpty && bytes.length % 4 == 0 && bytes.length.toLong <= words.toLong * 4)
    Files.createDirectories(output)
    if (mode == "platform") {
        Files.write(output.resolve("ram_zero.hex"), ("0000000000000000\n" * 512).getBytes(StandardCharsets.US_ASCII))
    }
    for ((name, bank) <- Seq("rom_even.hex", "rom_odd.hex").zipWithIndex) {
        val data = (bank until words by 2)
            .map { index =>
                val value = (0 until 4)
                    .map { b =>
                        val offset = index.toLong * 4 + b
                        if (offset < bytes.length) (bytes(offset.toInt).toLong & 255L) << (8 * b) else 0L
                    }
                    .reduce(_ | _)
                f"$value%08x"
            }
            .mkString("", "\n", "\n")
        Files.write(output.resolve(name), data.getBytes(StandardCharsets.US_ASCII))
    }
    ChiselStage.emitSystemVerilogFile(
        if (mode == "platform") new FpgaPlatformTop(words) else new FpgaRomTop(words),
        Array("--target-dir", output.toString),
        Array("-disable-all-randomization", "-strip-debug-info", "-default-layer-specialization=disable")
    )
}
