package platform

import java.nio.file.{Files, Paths}
import soc.platform._
import upickle.core.{ObjVisitor, Visitor}

/** File schema v1 intentionally exposes only the four closed static A1 choices.
  * JSON belongs to the generator, not to synthesizable hardware configuration.
  */
object CommonSocConfigFile {
    // ujson normally overwrites duplicate keys. Reject ambiguity before building
    // its AST, including escaped spellings of the same key and nested objects.
    private object UniqueKeys extends Visitor.Delegate[ujson.Value, ujson.Value](ujson.Value) {
        override def visitObject(length: Int, jsonableKeys: Boolean, index: Int): ObjVisitor[ujson.Value, ujson.Value] = {
            val delegate = ujson.Value.visitObject(length, jsonableKeys, index)
            val keys = scala.collection.mutable.Set.empty[String]
            new ObjVisitor[ujson.Value, ujson.Value] {
                def subVisitor = UniqueKeys
                def visitKey(index: Int): Visitor[_, _] = delegate.visitKey(index)
                def visitKeyValue(value: Any): Unit = {
                    val key = value.asInstanceOf[String]
                    require(keys.add(key), s"duplicate SoC configuration key: $key")
                    delegate.visitKeyValue(value)
                }
                def visitValue(value: ujson.Value, index: Int): Unit = delegate.visitValue(value, index)
                def visitEnd(index: Int): ujson.Value = delegate.visitEnd(index)
            }
        }
    }

    private def fields(value: ujson.Value, expected: Set[String], name: String): Unit = {
        require(value.isInstanceOf[ujson.Obj], s"$name must be an object")
        require(value.obj.keySet.toSet == expected, s"$name requires exactly: ${expected.toSeq.sorted.mkString(", ")}")
    }

    def parse(text: String): CommonSocConfig = {
        val value = ujson.StringParser.transform(text, UniqueKeys)
        fields(value, Set("schema", "cpu", "peripherals"), "SoC configuration")
        require(value("schema") == ujson.Num(1), "SoC configuration schema must be 1")
        val cpu = value("cpu")
        fields(cpu, Set("kind", "clockProfile", "lsuOwners"), "cpu")
        require(cpu("kind") == ujson.Str("a1") && cpu("clockProfile") == ujson.Str("production"),
            "SoC file schema 1 supports only generic A1 production; other profiles retain the legacy CLI")
        val owners = cpu("lsuOwners")
        require(owners == ujson.Num(2) || owners == ujson.Num(4), "cpu.lsuOwners must be the number 2 or 4")
        val peripherals = value("peripherals")
        fields(peripherals, Set("jtagDownload"), "peripherals")
        require(peripherals("jtagDownload").isInstanceOf[ujson.Bool], "peripherals.jtagDownload must be boolean")
        CommonSocConfig(CommonCpuProfile.A1, Some(CommonA1CpuSpec(owners.num.toInt)),
            CommonPeripheralConfig(peripherals("jtagDownload").bool))
    }

    /** A file replaces, never overrides or merges with, legacy selectors. */
    def select(cpuArgument: String, options: Seq[String]): CommonSocConfig =
        select(cpuArgument, options, Files.readString(Paths.get(cpuArgument.stripPrefix("--soc-config="))))

    // The exporter supplies the same text whose original bytes it hashes.
    def select(cpuArgument: String, options: Seq[String], fileText: => String): CommonSocConfig = {
        val selectors = Seq("--clock-profile=", "--experimental-a1-profile=", "--a1-lsu-owners=", "--jtag-download=")
        require(options.map(_.takeWhile(_ != '=')).distinct.size == options.size, "duplicate exporter option")
        val fileMode = cpuArgument.startsWith("--soc-config=")
        require(!options.exists(_.startsWith("--soc-config=")), "--soc-config=FILE must replace the i1|a1 argument")
        if (fileMode) {
            require(!options.exists(option => selectors.exists(option.startsWith)),
                "SoC configuration file cannot be combined with legacy CPU, clock, experiment or peripheral selectors")
            parse(fileText)
        } else {
            def option(prefix: String) = options.find(_.startsWith(prefix)).map(_.stripPrefix(prefix))
            CommonSocConfig(
                CommonCpuProfile.named(cpuArgument, option("--clock-profile=").getOrElse("production")),
                option("--a1-lsu-owners=").map(CommonA1CpuSpec.lsuOption),
                CommonPeripheralConfig.jtagOption(option("--jtag-download=").getOrElse("on")),
                option("--experimental-a1-profile=").map(CommonA1ExperimentalSelection.named))
        }
    }

    def requested(config: CommonSocConfig): ujson.Obj = ujson.Obj(
        "cpu" -> ujson.Obj("kind" -> config.profile.kind, "clockProfile" -> config.profile.clockProfile,
            "lsuOwners" -> config.cpuSpec.map(s => ujson.Num(s.lsuOwners)).getOrElse(ujson.Null),
            "experimentalProfile" -> config.a1Experimental.map(s => ujson.Str(s.name)).getOrElse(ujson.Null)),
        "peripherals" -> ujson.Obj("jtagDownload" -> config.peripherals.jtagDownload))
}
