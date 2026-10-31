import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from validate import (  # noqa: E402
    check_putaway_rule_refs,
    collect_element_ids,
    make_validator,
    validate_company_file,
)


RULE_VALIDATOR = make_validator("putaway-rule.schema.json")
FIELDS = {
    "fields": {
        "allowed_zone_types": ["storage_type"],
        "allowed_selection_strategies": ["FIFO"],
        "allowed_placement_strategies": ["NEXT_EMPTY", "ADD_TO_EXISTING"],
    }
}


def step(zone_id="HBR", strategy="NEXT_EMPTY", **constraints):
    entry = {"zone": {"type": "storage_type", "id": zone_id}, "placement_strategy": strategy}
    if constraints:
        entry["constraints"] = constraints
    return entry


def check(rules):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "putaway_rules.yaml"
        path.write_text(yaml.safe_dump({"putaway_rules": rules}), encoding="utf-8")
        return check_putaway_rule_refs(path, FIELDS, collect_element_ids())


class PutawayRuleSchemaTest(unittest.TestCase):
    def test_minimal_rule_is_valid(self):
        rule = {"id": "P1", "steps": [step()]}
        self.assertEqual(list(RULE_VALIDATOR.iter_errors(rule)), [])

    def test_max_fill_percent_is_bounded(self):
        rule = {"id": "P1", "steps": [step(max_fill_percent=101)]}
        self.assertTrue(list(RULE_VALIDATOR.iter_errors(rule)))

    def test_unknown_constraint_is_rejected(self):
        rule = {"id": "P1", "steps": [step(mix_owners=True)]}
        self.assertTrue(list(RULE_VALIDATOR.iter_errors(rule)))

    def test_empty_applies_to_is_rejected(self):
        rule = {"id": "P1", "applies_to": {}, "steps": [step()]}
        self.assertTrue(list(RULE_VALIDATOR.iter_errors(rule)))


class PutawayRuleRefsTest(unittest.TestCase):
    def test_valid_rules_pass(self):
        rules = [
            {"id": "DEFAULT", "steps": [step(), step("BLK", "ADD_TO_EXISTING")]},
            {"id": "ITEM", "applies_to": {"item_id": "I1"}, "steps": [step()]},
        ]
        self.assertEqual(check(rules), [])

    def test_two_defaults_are_ambiguous(self):
        errors = check([{"id": "A", "steps": [step()]}, {"id": "B", "steps": [step()]}])
        self.assertTrue(any("ambiguous default" in e for e in errors))

    def test_unknown_placement_strategy(self):
        errors = check([{"id": "A", "steps": [step(strategy="TELEPORT")]}])
        self.assertTrue(any("not found in elements/placement_strategies.yaml" in e for e in errors))

    def test_strategy_not_allowed_in_building(self):
        errors = check([{"id": "A", "steps": [step(strategy="LOWEST_LEVEL_FIRST")]}])
        self.assertTrue(any("allowed_placement_strategies" in e for e in errors))

    def test_zone_type_not_allowed_in_building(self):
        rule = {"id": "A", "steps": [{
            "zone": {"type": "activity_area", "id": "PICK_ZONE_A"},
            "placement_strategy": "NEXT_EMPTY",
        }]}
        errors = check([rule])
        self.assertTrue(any("allowed_zone_types" in e for e in errors))

    def test_repeated_zone_without_filter_is_unreachable(self):
        errors = check([{"id": "A", "steps": [step(), step(strategy="ADD_TO_EXISTING")]}])
        self.assertTrue(any("unreachable" in e for e in errors))

    def test_repeated_zone_for_subset_of_types_is_unreachable(self):
        rules = [{"id": "A", "steps": [
            step(load_unit_types=["pallet_euro", "pallet_industrial"]),
            step(load_unit_types=["pallet_euro"]),
        ]}]
        self.assertTrue(any("unreachable" in e for e in check(rules)))

    def test_repeated_zone_for_other_types_is_reachable(self):
        rules = [{"id": "A", "steps": [
            step(load_unit_types=["pallet_euro"]),
            step(strategy="ADD_TO_EXISTING", load_unit_types=["mesh_box"]),
        ]}]
        self.assertEqual(check(rules), [])

    def test_repeated_zone_with_other_constraints_is_reachable(self):
        rules = [{"id": "A", "steps": [
            step(max_fill_percent=80),
            step("BLK", "ADD_TO_EXISTING"),
            step(max_fill_percent=95),
        ]}]
        self.assertEqual(check(rules), [])

    def test_unfiltered_step_after_filtered_step_is_reachable(self):
        rules = [{"id": "A", "steps": [
            step(load_unit_types=["pallet_euro"]),
            step(strategy="ADD_TO_EXISTING"),
        ]}]
        self.assertEqual(check(rules), [])


class ExampleCustomerTest(unittest.TestCase):
    def test_example_customer_validates(self):
        company = REPO_ROOT / "customers" / "example_customer" / "company.yaml"
        self.assertEqual(validate_company_file(company, collect_element_ids()), [])


if __name__ == "__main__":
    unittest.main()
