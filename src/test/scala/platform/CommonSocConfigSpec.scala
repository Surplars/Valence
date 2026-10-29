package platform

import java.nio.file.{Files, Paths}
import org.scalatest.funsuite.AnyFunSuite
import soc.platform._

class CommonSocConfigSpec extends AnyFunSuite {
    private def text(owners: Int = 2, jtag: Boolean = true): String =
        s"""{"schema":1,"cpu":{"kind":"a1","clockProfile":"production","lsuOwners":$owners},"peripherals":{"jtagDownload":$jtag}}"""

    test("all four checked-in files equal legacy selection and preserve unrelated configuration") {
        for (owners <- Seq(2, 4); jtag <- Seq(true, false)) {
            val mode = if (jtag) "on" else "off"
            val path = Paths.get(s"config/common-soc/a1-lsu$owners-jtag-$mode.json")
            val file = CommonSocConfigFile.select(s"--soc-config=$path", Seq("--programmable"))
            val cli = CommonSocConfigFile.select("a1", Seq(s"--a1-lsu-owners=$owners", s"--jtag-download=$mode"))
            assert(file == cli && file == CommonSocConfigFile.parse(text(owners, jtag)))
            val actual = file.cpuConfig(file.profile.boundary)
            assert(actual == CommonCpuProfile.A1.fpga.copy(lsuEntries = owners))
            assert(file.peripherals.mmioRegions == CommonPeripheralConfig(jtag).mmioRegions)
            assert(CommonCpuMicroarchitectureIdentity.build(file.profile, file.a1Experimental,
                file.profile.boundary, cpuSpec = file.cpuSpec) ==
                CommonCpuMicroarchitectureIdentity.build(cli.profile, cli.a1Experimental,
                    cli.profile.boundary, cpuSpec = cli.cpuSpec))
        }
    }

    test("legacy omitted selectors preserve public profiles and absent explicit CPU identity") {
        for (kind <- Seq("i1", "a1")) {
            val config = CommonSocConfigFile.select(kind, Seq.empty)
            assert(config == CommonSocConfig(CommonCpuProfile.named(kind)))
            assert(config.cpuSpec.isEmpty && config.peripherals.jtagDownload)
            assert(config.cpuConfig(config.profile.boundary) == config.profile.fpga)
        }
        for (selection <- CommonA1ExperimentalSelection.all) {
            val config = CommonSocConfigFile.select("a1", Seq(s"--experimental-a1-profile=${selection.name}"))
            assert(config.cpuConfig(config.profile.boundary) == selection.rebuild.config)
        }
        assert(CommonSocConfigFile.select("i1", Seq("--clock-profile=boot50-dynamic")).profile ==
            CommonCpuProfile.I1Boot50Dynamic)
    }

    test("file schema rejects unsupported capacity profiles fields and types") {
        val bad = Seq(text(3), text().replace("\"a1\"", "\"i1\""),
            text().replace("production", "boot50-static"), text().replace("\"schema\":1", "\"schema\":2"),
            text().replace("\"schema\":1", "\"schema\":\"1\""), text().replace("\"lsuOwners\":2", "\"lsuOwners\":2.5"),
            text().replace("\"lsuOwners\":2", "\"lsuOwners\":\"2\""),
            text().replace("\"jtagDownload\":true", "\"jtagDownload\":\"on\""),
            text().replace("\"lsuOwners\":2", "\"lsuOwners\":null"),
            text().replace("\"lsuOwners\":2", "\"lsuOwners\":2,\"robEntries\":32"),
            text().replace(",\"lsuOwners\":2", ""), text().replace("\"schema\":1", "\"schema\":1,\"experimental\":true"),
            "[]", "null", "{", text() + " false")
        bad.foreach(value => intercept[Exception] { CommonSocConfigFile.parse(value) })
    }

    test("duplicate keys including escaped keys are rejected rather than last-wins") {
        for (value <- Seq(text().replace("\"schema\":1", "\"schema\":2,\"schema\":1"),
            text().replace("\"lsuOwners\":2", "\"lsuOwners\":4,\"lsuOwners\":2"),
            text().replace("\"jtagDownload\":true", "\"jtagDownload\":false,\"jtagDownload\":true"),
            text().replace("\"schema\":1", "\"sch\\u0065ma\":2,\"schema\":1"))) {
            intercept[IllegalArgumentException] { CommonSocConfigFile.parse(value) }
        }
    }

    test("file and legacy selectors never merge and duplicate CLI options reject") {
        val file = "--soc-config=config/common-soc/a1-lsu2-jtag-on.json"
        for (option <- Seq("--clock-profile=production", "--experimental-a1-profile=anything",
            "--a1-lsu-owners=2", "--jtag-download=on", file)) {
            intercept[IllegalArgumentException] { CommonSocConfigFile.select(file, Seq(option)) }
        }
        intercept[IllegalArgumentException] { CommonSocConfigFile.select("a1", Seq(file)) }
        intercept[IllegalArgumentException] {
            CommonSocConfigFile.select("a1", Seq("--jtag-download=on", "--jtag-download=off"))
        }
    }

    test("typed descriptor retains unsupported CPU experiment and runtime guards") {
        intercept[IllegalArgumentException] {
            CommonSocConfig(CommonCpuProfile.I1, Some(CommonA1CpuSpec(4))).cpuConfig(CommonCpuProfile.I1.boundary)
        }
        intercept[IllegalArgumentException] {
            CommonSocConfig(CommonCpuProfile.A1, Some(CommonA1CpuSpec(4)),
                a1Experimental = Some(CommonA1ExperimentalSelection.all.head)).cpuConfig(CommonCpuProfile.A1.boundary)
        }
        intercept[IllegalArgumentException] {
            CommonSocConfig(CommonCpuProfile.A1, Some(CommonA1CpuSpec(4)))
                .cpuConfig(CommonCpuProfile.A1.boundary, experimentalRuntime = true)
        }
    }

    private def expanded(rob: Int, prf: Int, owners: Int = 4): String =
        text(owners).replace("\"schema\":1", "\"schema\":2").replace(
            s"\"lsuOwners\":$owners", s"\"lsuOwners\":$owners,\"robEntries\":$rob,\"physicalRegs\":$prf")

    test("schema 2 resolves all twelve legal tuples and canonicalizes baseline CPU identity") {
        val identities = for (rob <- Seq(16, 32, 64); prf <- Seq(48, 64); owners <- Seq(2, 4)) yield {
            val file = CommonSocConfigFile.parse(expanded(rob, prf, owners))
            assert(file.cpuSpec.contains(CommonA1CpuSpec(owners, rob, prf)))
            val identity = CommonCpuMicroarchitectureIdentity.build(file.profile, None,
                file.profile.boundary, cpuSpec = file.cpuSpec)
            assert(identity("effectiveCore")("robEntries").str == rob.toString)
            assert(identity("effectiveCore")("physicalRegs").str == prf.toString)
            if (rob == 16 && prf == 48) {
                val v1 = CommonSocConfigFile.parse(text(owners))
                assert(file == v1)
                assert(identity == CommonCpuMicroarchitectureIdentity.build(v1.profile, None,
                    v1.profile.boundary, cpuSpec = v1.cpuSpec))
            } else {
                assert(identity("requestedCpuSpec")("robEntries").str == rob.toString)
                assert(identity("requestedCpuSpec")("physicalRegs").str == prf.toString)
            }
            identity("identitySha256").str
        }
        assert(identities.distinct.size == 12)
    }

    test("schema 2 rejects fractional invalid missing duplicate and unknown capacity fields") {
        val valid = expanded(32, 64)
        for (value <- Seq("null", "true", "\"32\"", "32.5", "0", "128", "1e100")) {
            intercept[IllegalArgumentException] {
                CommonSocConfigFile.parse(valid.replace("\"robEntries\":32", s"\"robEntries\":$value"))
            }
        }
        for (value <- Seq("null", "false", "\"64\"", "64.5", "32", "128")) {
            intercept[IllegalArgumentException] {
                CommonSocConfigFile.parse(valid.replace("\"physicalRegs\":64", s"\"physicalRegs\":$value"))
            }
        }
        for (value <- Seq(valid.replace(",\"robEntries\":32", ""),
            valid.replace("\"physicalRegs\":64", "\"physicalRegs\":64,\"physicalRegs\":48"),
            valid.replace("\"physicalRegs\":64", "\"physicalRegs\":64,\"issueWidth\":4"))) {
            intercept[IllegalArgumentException] { CommonSocConfigFile.parse(value) }
        }
    }

    test("checked-in schema 2 examples resolve their explicit capacities") {
        for (rob <- Seq(16, 32)) {
            val path = Paths.get(s"config/common-soc/a1-rob$rob-prf64-lsu4-jtag-on.json")
            assert(CommonSocConfigFile.parse(Files.readString(path)) == CommonSocConfigFile.parse(expanded(rob, 64)))
        }
    }

}
