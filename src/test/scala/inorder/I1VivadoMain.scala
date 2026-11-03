package inorder

import _root_.circt.stage.ChiselStage
import soc.core.inorder._

object I1PerformanceCachedRtlMain extends App {
    ChiselStage.emitSystemVerilogFile(new I1PerformanceCachedCore(FiveStageArguments.config(args)),
        Array("--target-dir", args.head),
        Array("--split-verilog", "--lower-memories", "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}

object I1FetchQueueMain extends App {
    ChiselStage.emitCHIRRTLFile(new I1FetchQueue(FiveStageArguments.config(args)),
        Array("--target-dir", args.head))
}

/** Raw production cache with independently chosen window geometry for alias/boundary checks. */
object I1CacheTagMain extends App {
    def number(name: String, default: BigInt): BigInt = args.find(_.startsWith(name + "="))
        .map(_.stripPrefix(name + "=")).map(value => BigInt(value.stripPrefix("0x"), 16)).getOrElse(default)
    val ordinary = FiveStageArguments.config(args.filterNot(a => a.startsWith("--cache-base=") ||
        a.startsWith("--cache-window=") || a == "--flow-hits"))
    val p = ordinary.copy(cacheableBase = number("--cache-base", ordinary.cacheableBase),
        cacheableBytes = number("--cache-window", ordinary.cacheableBytes))
    ChiselStage.emitCHIRRTLFile(new FiveStageWordCache(p, p.dataCacheBytes, args.contains("--flow-hits")),
        Array("--target-dir", args.head))
}
