import json
import unittest

from collect_network_route import INTERNAL_SCOPES, SCOPES, STAGES, result_flags, stage_results


class NetworkRouteEvidenceTests(unittest.TestCase):
    def test_stages_require_native_matching_and_all_four(self):
        rows = [{"stage": stage, "cpu_setup_wns_ns": -0.1,
                 "cpu_clock_group_hold_whs_ns": -0.2} for stage in STAGES]
        text = "\n".join(json.dumps(row) for row in rows)
        log = "\n".join("I1_NETWORK_PHYSICAL_STAGE stage=" + stage +
                        " CPU_WNS=-0.100 CPU_CLOCK_GROUP_WHS=-0.200" for stage in STAGES)
        self.assertEqual(stage_results(text, log), rows)
        with self.assertRaises(ValueError):
            stage_results(text, log.replace("CPU_WNS=-0.100", "CPU_WNS=0.100", 1))
        with self.assertRaises(ValueError):
            stage_results(text.splitlines()[0], log)

    def values(self):
        values = {k + suffix: 0.1 for k, suffix in (
            ("setup", "_wns_ns"), ("hold", "_whs_ns"), ("pulse", "_wpws_ns"))}
        values.update({name + "_failing_endpoints": 0 for name in ("setup", "hold", "pulse")})
        return values

    def test_cpu_pass_does_not_hide_global_or_uart_failure(self):
        paths = {scope: {"slack_ns": 0.1} for scope in SCOPES + INTERNAL_SCOPES}
        paths["hold_global"]["slack_ns"] = -1.0
        paths["hold_uart_raw_to_gated"]["slack_ns"] = -0.01
        values = self.values()
        values["hold_whs_ns"] = -1.0
        values["hold_failing_endpoints"] = 1
        flags = result_flags(paths, values, {"routed_without_errors": True, "nets with explicit gaps": 0})
        self.assertTrue(flags["cpu_clock_group_setup_met"])
        self.assertTrue(flags["cpu_internal_hold_met"])
        self.assertFalse(flags["all_timed_paths_met"])
        for key in ("physical_qualified", "board_qualified", "cdc_signed_off", "bit_generated"):
            self.assertFalse(flags[key])

    def test_external_gap_never_silently_waived(self):
        paths = {scope: {"slack_ns": 0.1} for scope in SCOPES + INTERNAL_SCOPES}
        flags = result_flags(paths, self.values(),
                             {"routed_without_errors": True, "nets with explicit gaps": 3})
        self.assertTrue(flags["all_timed_paths_met"])
        self.assertFalse(flags["route_has_no_errors_or_gaps"])
        self.assertFalse(flags["physical_qualified"])

    def test_zero_slack_is_distinct_from_remaining_endpoint_failures(self):
        paths = {scope: {"slack_ns": 0.0} for scope in SCOPES + INTERNAL_SCOPES}
        values = self.values()
        values["setup_failing_endpoints"] = 1
        flags = result_flags(paths, values, {"routed_without_errors": True, "nets with explicit gaps": 0})
        self.assertTrue(flags["cpu_clock_group_setup_met"])
        self.assertFalse(flags["all_timed_paths_met"])

    def test_external_clock_group_failure_does_not_claim_core_failure(self):
        paths = {scope: {"slack_ns": 0.1} for scope in SCOPES + INTERNAL_SCOPES}
        paths["setup_cpu"]["slack_ns"] = -2.0
        flags = result_flags(paths, self.values(),
                             {"routed_without_errors": True, "nets with explicit gaps": 0})
        self.assertFalse(flags["cpu_clock_group_setup_met"])
        self.assertTrue(flags["cpu_internal_setup_met"])
        self.assertTrue(flags["core_internal_setup_and_hold_met"])
        self.assertFalse(flags["board_qualified"])


if __name__ == "__main__":
    unittest.main()
