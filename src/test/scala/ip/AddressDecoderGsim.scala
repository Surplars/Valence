package ip

import _root_.circt.stage.ChiselStage
import soc.ip.tilelink.TwoBankAddressDecoder

object AddressDecoderGsimMain extends App {
    val width = args(1).toInt
    val (base, first, second) = args(2) match {
        case "ddr" => (BigInt("80000000", 16), BigInt(2 * 1024 * 1024), BigInt(512 * 1024 * 1024))
        case "ddr2g" => (BigInt("80000000", 16), BigInt(2 * 1024 * 1024), BigInt(1) << 31)
        case "high" => (BigInt("f000000000001000", 16), BigInt(1024), BigInt(2048))
        case "small" => (BigInt("80010000", 16), BigInt(2048), BigInt(2048))
    }
    ChiselStage.emitCHIRRTLFile(new TwoBankAddressDecoder(width, base, first, second),
        Array("--target-dir", args.head))
}
