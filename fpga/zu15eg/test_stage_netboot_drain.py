"""File-provenance checks only, not RTL or timing proof."""
from pathlib import Path
import tempfile
import unittest

from stage_netboot_drain import check_delivery_sources, sha


class DeliveryProvenance(unittest.TestCase):
    def test_document_change_is_explicitly_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "fpga/firmware/NETBOOT-BOARD-TEST.txt"
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_text("before")
            before = sha(path)
            path.write_text("after")
            self.assertEqual(check_delivery_sources(root, {name: before}),
                             {name: dict(delivery_sha256=before, current_sha256=sha(path))})

    def test_operational_source_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "fpga/firmware/bootrom.c"
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_text("before")
            before = sha(path)
            path.write_text("after")
            with self.assertRaisesRegex(ValueError, "Operational delivery source drift"):
                check_delivery_sources(root, {name: before})

    def test_unchanged_operational_source_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = "build.mill"
            path = root / name
            path.write_text("unchanged")
            self.assertEqual(check_delivery_sources(root, {name: sha(path)}), {})


if __name__ == "__main__":
    unittest.main()
