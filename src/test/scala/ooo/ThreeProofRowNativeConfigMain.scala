package ooo

import java.nio.file.{Files, Paths}

/** Pure configuration check. Does not construct Chisel hardware or invoke an emitter. */
object ThreeProofRowNativeConfigMain extends App {
    require(args.length == 1, "qualified CPU reference directory required")
    val reference = Paths.get(args(0)).toAbsolutePath
    def read(name: String): ujson.Value = ujson.read(Files.readString(reference.resolve(name)))
    def json(value: Any): ujson.Value = ujson.read(PostedBoardConfiguration.json(value))
    val config = ThreeProofRowNativeProfile.config
    val core = config.coreParams
    require(config == ThreeProofRowCandidateProfile.candidate, "explicit native and qualified candidate differ")
    require(config.productArity == 95 && core.productArity == 178)
    ProfileAbi77.requireLive(config)
    ProfileAbi77.requireLive(core)
    PlacedTimingProfileBridge.requireShape(config)
    val order = Map("core" -> core.productElementNames.toSeq, "profile" -> config.productElementNames.toSeq)
    require(json(order) == read("actual-product-field-order.json"), "complete product field order differs")
    require(json(core) == read("actual-core-parameters.json"), "complete core values differ")
    require(json(PostedBoardConfiguration.document(config)) == read("profile.json"),
        "complete profile/cache/storage/DDR/network/derived values differ")
    val fabric = read("actual-fabric.json")
    val rows = read("actual-three-proof-row-cpu.json")
    require(fabric("cpu") == json(core) && rows("core") == json(core))
    require(fabric("cache") == json(config.cache) && rows("cache") == json(config.cache))
    require(fabric("ddr") == json(config.ddr))
    require(rows("proofRows").num == 3 && rows("earlyLoadCredits").num == 2 && rows("lsuOwners").num == 4)
    require(config.cpuHz == 100000000 && config.aonHz == 50000000 && config.uartHz == 50000000 &&
        config.ddrUiHz == 250000000)
    require(!ThreeProofRowNativeProfile.debug.enabled && !ThreeProofRowNativeProfile.debug.externalDmi &&
        ThreeProofRowNativeProfile.bscanChain == 2)
    var historicalRejects = 0
    def reject(body: => Unit): Unit = {
        var rejected = false
        try { body } catch { case _: IllegalArgumentException => rejected = true }
        require(rejected, "enabled query must not be projected into a historical profile")
        historicalRejects += 1
    }
    reject { ProfileAbi77.requireHistorical(config) }
    reject { ProfileAbi77.retained(core) }
    ThreeProofRowCandidateConfigMain.main(Array.empty[String])
    require(historicalRejects == 2)
    println("PASS_THREE_ROW_PORTABLE_CONFIG core=178 profile=95 rows=3 credits=2 historicalRejects=2 no_elaboration=true")
}
