import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from validate import (  # noqa: E402
    check_fixed_bin_assignments,
    check_fixed_bin_strategy_needs_assignments,
    make_validator,
)


VALIDATOR = make_validator("fixed-bin-assignment.schema.json")


def assignment(item="I1", point="FIX.01", **extra):
    entry = {"item_id": item, "storage_point": point, "min_qty": 5, "max_qty": 20}
    entry.update(extra)
    return entry


def check(entries):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixed_bin_assignments.yaml"
        path.write_text(yaml.safe_dump({"fixed_bin_assignments": entries}), encoding="utf-8")
        return check_fixed_bin_assignments(path)


class SchemaTest(unittest.TestCase):
    def test_minimal_and_full_entries_are_valid(self):
        for entry in (assignment(), assignment(sequence=2, uom="each", max_pick_qty=10)):
            with self.subTest(entry=entry):
                self.assertEqual(list(VALIDATOR.iter_errors(entry)), [])

    def test_required_fields(self):
        self.assertTrue(list(VALIDATOR.iter_errors({"item_id": "I1", "storage_point": "P"})))

    def test_max_qty_must_be_positive(self):
        self.assertTrue(list(VALIDATOR.iter_errors(assignment(max_qty=0))))


class AssignmentChecksTest(unittest.TestCase):
    def test_valid_assignments_pass(self):
        entries = [assignment(), assignment(point="FIX.02", sequence=2), assignment("I2", "FIX.03")]
        self.assertEqual(check(entries), [])

    def test_min_above_max_fails(self):
        self.assertTrue(any("min_qty (30) exceeds max_qty" in e for e in check([assignment(min_qty=30)])))

    def test_max_pick_above_max_fails(self):
        self.assertTrue(any("max_pick_qty" in e for e in check([assignment(max_pick_qty=25)])))

    def test_place_fixed_to_two_items_fails(self):
        errors = check([assignment("I1"), assignment("I2")])
        self.assertTrue(any("already fixed to item 'I1'" in e for e in errors))

    def test_same_item_same_place_twice_fails(self):
        errors = check([assignment(), assignment(sequence=2)])
        self.assertTrue(any("duplicate assignment" in e for e in errors))

    def test_sequence_unique_per_item(self):
        errors = check([assignment(point="FIX.01"), assignment(point="FIX.02")])
        self.assertTrue(any("sequence 1 already used" in e for e in errors))


class FixedBinStrategyTest(unittest.TestCase):
    def test_fixed_bin_first_needs_assignment_file(self):
        rules = {"putaway_rules": [{"id": "P", "steps": [{
            "zone": {"type": "storage_type", "id": "FIX"}, "placement_strategy": "FIXED_BIN_FIRST",
        }]}]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "putaway_rules.yaml"
            path.write_text(yaml.safe_dump(rules), encoding="utf-8")
            errors = check_fixed_bin_strategy_needs_assignments(path)
        self.assertTrue(any("does not import strategies/fixed_bin_assignments.yaml" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
