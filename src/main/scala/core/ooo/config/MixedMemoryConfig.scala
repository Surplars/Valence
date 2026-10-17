package soc.core.ooo

/** Keyed overrides compose with the existing positional geometries. No capacity grows implicitly. */
case class MixedMemoryConfig(ddrWriteSlots: Option[Int] = None, cacheWritebacks: Option[Int] = None,
    overlapWritebackRefill: Boolean = false, unorderedDdrResponses: Boolean = false, dataNextLinePrefetch: Boolean = false) {
    def specified: Boolean = ddrWriteSlots.nonEmpty || cacheWritebacks.nonEmpty || overlapWritebackRefill || unorderedDdrResponses || dataNextLinePrefetch
    def ddr(base: DdrBridgeConfig): DdrBridgeConfig =
        base.copy(maxOutstandingWrites = ddrWriteSlots.getOrElse(base.maxOutstandingWrites),
            unorderedResponses = unorderedDdrResponses || base.unorderedResponses)
    def cache(base: CoherentCacheConcurrency, sourceBits: Int = 3): CoherentCacheConcurrency = {
        val result = base.copy(writebackEntries = cacheWritebacks.getOrElse(base.writebackEntries),
            overlapWritebackRefill = overlapWritebackRefill || base.overlapWritebackRefill,
            nextLinePrefetch = dataNextLinePrefetch || base.nextLinePrefetch)
        require(result.sourceBits <= sourceBits, "Acquire and Release owners exceed the configured TL source width")
        result
    }
}

object MixedMemoryConfig {
    def parseArgs(args: Array[String]): (Array[String], MixedMemoryConfig) = {
        val numeric = Set("--ddr-write-slots", "--cache-writebacks")
        val flag = "--overlap-writeback-refill"
        val prefetch = "--data-next-line-prefetch"
        require(args.count(_ == prefetch) <= 1, s"duplicate memory flag: $prefetch")
        require(!args.exists(_.startsWith(prefetch + "=")), s"$prefetch takes no value")
        val unordered = "--unordered-ddr-responses"
        require(args.count(_ == unordered) <= 1, s"duplicate mixed-memory flag: $unordered")
        require(!args.exists(_.startsWith(unordered + "=")), s"$unordered takes no value")
        numeric.foreach { key =>
            val entries = args.filter(arg => arg == key || arg.startsWith(key + "="))
            require(entries.length <= 1, s"duplicate mixed-memory option: $key")
            entries.foreach(arg => require(arg.startsWith(key + "=") && arg.drop(key.length + 1).matches("[0-9]+"),
                s"expected $key=N"))
        }
        require(args.count(_ == flag) <= 1, s"duplicate mixed-memory flag: $flag")
        require(!args.exists(_.startsWith(flag + "=")), s"$flag takes no value")
        def value(key: String): Option[Int] = args.find(_.startsWith(key + "=")).map(_.drop(key.length + 1).toInt)
        val writes = value("--ddr-write-slots")
        val writebacks = value("--cache-writebacks")
        require(writes.forall(v => v >= 0 && v <= 8), "DDR write slots must be in 0..8 and fit the positional total pool")
        require(writebacks.forall(Set(1, 2, 4).contains), "cache writebacks must be 1, 2 or 4")
        (args.filterNot(arg => arg == flag || arg == unordered || arg == prefetch || numeric.exists(key => arg.startsWith(key + "="))),
            MixedMemoryConfig(writes, writebacks, args.contains(flag), args.contains(unordered), args.contains(prefetch)))
    }
}
