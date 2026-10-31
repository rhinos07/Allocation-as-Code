import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from precedence import select_rule, specificity  # noqa: E402
from validate import (  # noqa: E402
    check_owner_zones,
    check_rule_scopes,
    make_validator,
)


SCOPE_VALIDATOR = make_validator("applies-to.schema.json")
PUTAWAY_VALIDATOR = make_validator("putaway-rule.schema.json")
ZONES_VALIDATOR = make_validator("owner-zones.schema.json")
ITEM = {"id": "ALPHA_001", "category": "cosmetics", "owner": "owner_alpha"}


def rule(rule_id, applies_to=None, zone="HBR"):
    entry = {"id": rule_id, "steps": [{
        "zone": {"type": "storage_type", "id": zone}, "placement_strategy": "NEXT_EMPTY",
    }]}
    if applies_to is not None:
        entry["applies_to"] = applies_to
    return entry


def write(tmp, name, data):
    path = Path(tmp) / name
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


class AppliesToSchemaTest(unittest.TestCase):
    def test_allowed_combinations(self):
        for scope in ({"item_id": "I"}, {"owner": "o"}, {"category": "c"}, {"owner": "o", "category": "c"}):
            with self.subTest(scope=scope):
                self.assertEqual(list(SCOPE_VALIDATOR.iter_errors(scope)), [])

    def test_item_id_stands_alone(self):
        for scope in ({"item_id": "I", "owner": "o"}, {"item_id": "I", "category": "c"}):
            with self.subTest(scope=scope):
                self.assertTrue(list(SCOPE_VALIDATOR.iter_errors(scope)))

    def test_empty_and_unknown_keys_are_rejected(self):
        self.assertTrue(list(SCOPE_VALIDATOR.iter_errors({})))
        self.assertTrue(list(SCOPE_VALIDATOR.iter_errors({"channel": "web"})))

    def test_allow_mixed_owners_is_a_putaway_constraint(self):
        entry = rule("P")
        entry["steps"][0]["constraints"] = {"allow_mixed_owners": False}
        self.assertEqual(list(PUTAWAY_VALIDATOR.iter_errors(entry)), [])


class PrecedenceTest(unittest.TestCase):
    RULES = [
        rule("DEFAULT"),
        rule("CATEGORY", {"category": "cosmetics"}),
        rule("OWNER", {"owner": "owner_alpha"}),
        rule("OWNER_CATEGORY", {"owner": "owner_alpha", "category": "cosmetics"}),
        rule("ITEM", {"item_id": "ALPHA_001"}),
    ]

    def test_order_of_specificity(self):
        ranks = [specificity(r.get("applies_to")) for r in self.RULES]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(len(set(ranks)), 5)

    def test_each_level_wins_over_the_ones_below(self):
        for keep in range(len(self.RULES), 0, -1):
            rules = self.RULES[:keep]
            with self.subTest(most_specific=rules[-1]["id"]):
                self.assertEqual(select_rule(rules, ITEM)["id"], rules[-1]["id"])

    def test_other_owner_rule_does_not_match(self):
        rules = [rule("DEFAULT"), rule("BETA", {"owner": "owner_beta"})]
        self.assertEqual(select_rule(rules, ITEM)["id"], "DEFAULT")

    def test_no_match_without_default(self):
        self.assertIsNone(select_rule([rule("BETA", {"owner": "owner_beta"})], ITEM))


class RuleScopesTest(unittest.TestCase):
    def test_distinct_scopes_pass(self):
        self.assertEqual(check_rule_scopes(Path("x"), PrecedenceTest.RULES, "putaway_rule"), [])

    def test_same_scope_twice_fails(self):
        rules = [rule("A", {"owner": "o", "category": "c"}), rule("B", {"category": "c", "owner": "o"})]
        errors = check_rule_scopes(Path("x"), rules, "search_rule")
        self.assertTrue(any("same applies_to scope" in e for e in errors))

    def test_two_defaults_fail(self):
        errors = check_rule_scopes(Path("x"), [rule("A"), rule("B")], "search_rule")
        self.assertTrue(any("ambiguous default" in e for e in errors))


class OwnerZonesTest(unittest.TestCase):
    ZONES = {"owner_zones": [{"zone": {"type": "storage_type", "id": "CAGE_A"}, "owners": ["owner_alpha"]}]}

    def check(self, rules):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(tmp, "putaway_rules.yaml", {"putaway_rules": rules})
            return check_owner_zones(path, self.ZONES)

    def test_schema(self):
        self.assertEqual(list(ZONES_VALIDATOR.iter_errors(self.ZONES)), [])
        self.assertTrue(list(ZONES_VALIDATOR.iter_errors({"owner_zones": [{"zone": {"type": "storage_type", "id": "Z"}, "owners": []}]})))

    def test_owner_rule_into_own_zone_passes(self):
        self.assertEqual(self.check([rule("A", {"owner": "owner_alpha"}, zone="CAGE_A")]), [])

    def test_other_owner_into_reserved_zone_fails(self):
        errors = self.check([rule("B", {"owner": "owner_beta"}, zone="CAGE_A")])
        self.assertTrue(any("not 'owner_beta'" in e for e in errors))

    def test_rule_without_owner_into_reserved_zone_fails(self):
        for scope in (None, {"category": "cosmetics"}):
            with self.subTest(scope=scope):
                errors = self.check([rule("X", scope, zone="CAGE_A")])
                self.assertTrue(any("has no applies_to.owner" in e for e in errors))

    def test_open_zone_is_free_for_all(self):
        self.assertEqual(self.check([rule("X", None, zone="HBR")]), [])

    def test_item_rule_is_left_to_cross_repo_check(self):
        self.assertEqual(self.check([rule("I", {"item_id": "BETA_001"}, zone="CAGE_A")]), [])


if __name__ == "__main__":
    unittest.main()
