"""Tests for strategies/area_assignments.yaml - item-level stock targets
for a zone without fixed places."""

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from validate import check_area_assignments, make_validator  # noqa: E402

VALIDATOR = make_validator("area-assignment.schema.json")
FIELDS = {"fields": {"allowed_zone_types": ["storage_type", "activity_area"]}}


def entry(item="I1", zone_id="PICK", **extra):
    data = {"item_id": item, "zone": {"type": "activity_area", "id": zone_id},
            "min_qty": 10, "max_qty": 40}
    data.update(extra)
    return data


def check(entries, fields=FIELDS):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "area_assignments.yaml"
        path.write_text(yaml.safe_dump({"area_assignments": entries}), encoding="utf-8")
        return check_area_assignments(path, fields)


class AreaAssignmentTest(unittest.TestCase):
    def test_schema_accepts_entry(self):
        self.assertEqual(list(VALIDATOR.iter_errors(entry(planned_qty=20, uom="each"))), [])

    def test_schema_rejects_unknown_zone_type(self):
        bad = entry()
        bad["zone"]["type"] = "door"
        self.assertTrue(list(VALIDATOR.iter_errors(bad)))

    def test_valid_entries_pass(self):
        self.assertEqual(check([entry(), entry(item="I2"), entry(zone_id="OTHER")]), [])

    def test_min_above_max_is_rejected(self):
        self.assertTrue(any("exceeds max_qty" in e for e in check([entry(min_qty=50)])))

    def test_planned_outside_range_is_rejected(self):
        self.assertTrue(any("planned_qty" in e for e in check([entry(planned_qty=45)])))

    def test_duplicate_item_zone_is_rejected(self):
        self.assertTrue(any("already has" in e for e in check([entry(), entry(max_qty=50)])))

    def test_zone_type_must_be_allowed(self):
        fields = {"fields": {"allowed_zone_types": ["storage_type"]}}
        self.assertTrue(any("allowed_zone_types" in e for e in check([entry()], fields)))


if __name__ == "__main__":
    unittest.main()
