"""Offline, synthetic source-inventory regression; no host or exchange calls."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collector_review.deployment import offline_source_inventory as inv


class OfflineSourceInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "collector_review"
        (self.root / "deployment").mkdir(parents=True)
        for index in range(10):
            (self.root / ("fixture_%02d.py" % index)).write_bytes(
                ("# synthetic source %02d\n" % index).encode()
            )
        (self.root / "deployment" / "testnet-collector-offline-review.service.example").write_text(
            "[Unit]\nDescription=synthetic offline fixture\n",
            encoding="utf-8",
        )
        self.patch_root = patch.object(inv, "_ROOT", self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)

    def test_inventory_is_deterministic_and_denies_authority(self):
        a, b = inv.inventory(), inv.inventory()
        self.assertEqual(a, b)
        self.assertEqual(a["artifact"], inv._MARKER)
        self.assertFalse(a["testnet_network_authorized"])
        self.assertFalse(a["trading_authorized"])
        self.assertEqual(len(a["files"]), 11)
        self.assertEqual(
            a["files"][0]["sha256"],
            hashlib.sha256((self.root / a["files"][0]["path"]).read_bytes()).hexdigest(),
        )

    def test_emit_verify_and_tamper_hold(self):
        report = Path(self.tmp.name) / "manifest.json"
        self.assertEqual(inv.run(["--emit", str(report)]), 0)
        self.assertEqual(inv.run(["--verify", str(report)]), 0)
        doc = json.loads(report.read_text())
        doc["files"][0]["sha256"] = "0" * 64
        report.write_text(json.dumps(doc))
        self.assertEqual(inv.run(["--verify", str(report)]), 1)
        self.assertFalse(doc["trading_authorized"])

    def test_changed_source_byte_is_detected(self):
        report = Path(self.tmp.name) / "manifest.json"
        self.assertEqual(inv.run(["--emit", str(report)]), 0)
        (self.root / "fixture_01.py").write_bytes(b"# altered\n")
        self.assertEqual(inv.run(["--verify", str(report)]), 1)

    def test_missing_unit_or_symlink_or_large_file_holds(self):
        unit = self.root / "deployment" / "testnet-collector-offline-review.service.example"
        unit.unlink()
        with self.assertRaises(ValueError):
            inv.inventory()
        unit.write_text("[Unit]\n")
        (self.root / "deployment" / "shortcut.py").symlink_to(self.root / "fixture_01.py")
        with self.assertRaises(ValueError):
            inv.inventory()
        (self.root / "deployment" / "shortcut.py").unlink()
        (self.root / "fixture_01.py").write_bytes(b"Z" * (inv._MAX_FILE_BYTES + 1))
        with self.assertRaises(ValueError):
            inv.inventory()

    def test_irrelevant_files_are_excluded(self):
        (self.root / "credentials.txt").write_text("do not include")
        (self.root / "cache.pyc").write_bytes(b"bad")
        paths = [item["path"] for item in inv.inventory()["files"]]
        self.assertNotIn("credentials.txt", paths)
        self.assertNotIn("cache.pyc", paths)


if __name__ == "__main__":
    unittest.main()
