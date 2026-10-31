#!/usr/bin/env python3
"""
Validates a company.yaml, facility.yaml, or allocation.yaml (and everything
it references, cascading down the Company -> Facility -> Building
hierarchy) against the JSON schemas in schemas/ and runs cross-file
consistency checks.

Usage:
    python tools/validate.py customers/example_customer/company.yaml
    python tools/validate.py customers/example_customer/facilities/facility_pa11/facility.yaml
    python tools/validate.py customers/example_customer/facilities/facility_pa11/buildings/hall_3/allocation.yaml

Any of the three levels can be passed directly; validation cascades
downward from whichever level you start at.
"""

import sys
import json
from pathlib import Path

import yaml
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

sys.path.insert(0, str(Path(__file__).resolve().parent))
from precedence import scope_key  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"
ELEMENTS_DIR = REPO_ROOT / "elements"

ELEMENT_CATALOGS = {
    "selection_strategies.yaml": ("selection-strategy.schema.json", "selection_strategies"),
    "placement_strategies.yaml": ("placement-strategy.schema.json", "placement_strategies"),
}


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def _build_schema_registry() -> Registry:
    """Pre-load all local schemas into a referencing.Registry, keyed by
    their $id, so cross-file $ref resolves correctly."""
    resources = []
    for schema_file in SCHEMA_DIR.glob("*.json"):
        schema_data = json.loads(schema_file.read_text(encoding="utf-8"))
        uri = schema_data.get("$id") or f"{SCHEMA_DIR.as_uri()}/{schema_file.name}"
        resources.append((uri, Resource.from_contents(schema_data, default_specification=DRAFT7)))
    return Registry().with_resources(resources)


SCHEMA_REGISTRY: Registry = _build_schema_registry()


def make_validator(schema_name: str) -> Draft7Validator:
    schema = load_schema(schema_name)
    return Draft7Validator(schema, registry=SCHEMA_REGISTRY)


def collect_imports(allocation_file: Path) -> list[Path]:
    data = load_yaml(allocation_file)
    imports = data.get("allocation", {}).get("imports", [])
    base_dir = allocation_file.parent
    return [base_dir / rel for rel in imports]


def collect_relative_refs(path: Path, root_key: str, list_key: str) -> list[Path]:
    data = load_yaml(path)
    refs = data.get(root_key, {}).get(list_key, [])
    base_dir = path.parent
    return [base_dir / rel for rel in refs]


def validate_file(path: Path, schema_name: str) -> list[str]:
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]

    validator = make_validator(schema_name)
    for err in validator.iter_errors(data):
        loc = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{path}: [{loc}] {err.message}")
    return errors


def validate_list_items(path: Path, schema_name: str, list_key: str) -> list[str]:
    """Validates each item in data[list_key] against schema_name (item-level
    schema, not a wrapper). Used for search_rules.yaml."""
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]

    validator = make_validator(schema_name)
    for item in data.get(list_key, []):
        for err in validator.iter_errors(item):
            errors.append(f"{path}: {list_key} '{item.get('id', '?')}': {err.message}")
    return errors


def collect_element_ids() -> dict[str, set[str]]:
    """Loads all element catalogs and returns a mapping of list_key -> set
    of known IDs. Missing catalog files are silently skipped."""
    ids: dict[str, set[str]] = {}
    for filename, (_schema_name, list_key) in ELEMENT_CATALOGS.items():
        catalog_file = ELEMENTS_DIR / filename
        if catalog_file.exists():
            data = load_yaml(catalog_file)
            if data:
                ids[list_key] = {
                    item.get("id") for item in data.get(list_key, []) if item.get("id")
                }
    return ids


def validate_element_catalog(path: Path, schema_name: str, list_key: str) -> list[str]:
    errors = []
    data = load_yaml(path)
    if data is None:
        return [f"{path}: File is empty or invalid."]
    validator = make_validator(schema_name)
    for item in data.get(list_key, []):
        for err in validator.iter_errors(item):
            errors.append(f"{path}: {list_key} '{item.get('id', '?')}': {err.message}")
    return errors


def check_rule_scopes(path: Path, rules: list[dict], kind: str) -> list[str]:
    """Rejects two rules of the same kind with the same applies_to scope.
    With precedence item_id > owner + category > owner > category >
    default (tools/precedence.py) and every item having exactly one id,
    owner and category, identical scopes are the only way two rules can
    tie for the same item. The default rule (no applies_to) is the
    empty scope, so this also covers "at most one default"."""
    errors: list[str] = []
    seen: dict[tuple, str] = {}
    for rule in rules:
        rule_id = rule.get("id", "?")
        key = scope_key(rule.get("applies_to"))
        if key in seen:
            if key:
                scope = ", ".join(f"{k}={v}" for k, v in key)
                errors.append(
                    f"{path}: {kind}s '{seen[key]}' and '{rule_id}' have the same applies_to scope ({scope}) - ambiguous"
                )
            else:
                errors.append(
                    f"{path}: {kind}s '{seen[key]}' and '{rule_id}' both omit applies_to (ambiguous default)"
                )
        else:
            seen[key] = rule_id
    return errors


def check_fixed_bin_strategy_needs_assignments(path: Path) -> list[str]:
    """FIXED_BIN_FIRST without strategies/fixed_bin_assignments.yaml
    in the building would have no fixed places to fill."""
    errors: list[str] = []
    for rule in (load_yaml(path) or {}).get("putaway_rules", []):
        for i, step in enumerate(rule.get("steps", [])):
            if step.get("placement_strategy") == "FIXED_BIN_FIRST":
                errors.append(
                    f"{path}: putaway_rule '{rule.get('id', '?')}' steps[{i}]: FIXED_BIN_FIRST but the building does not import strategies/fixed_bin_assignments.yaml"
                )
    return errors


def check_owner_zones(path: Path, owner_zones_data: dict | None) -> list[str]:
    """Checks putaway_rules.yaml against structure/owner_zones.yaml: a
    step into a reserved zone needs a rule whose applies_to.owner is one
    of the zone's owners. A rule scoped by item_id alone cannot be
    checked here - the item's owner lives in MasterData-as-Code
    (cross-repo, see Warehouse-as-Code backlog C1a)."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data or not owner_zones_data:
        return errors

    reserved: dict[tuple[str, str], set[str]] = {}
    for entry in owner_zones_data.get("owner_zones", []):
        zone = entry.get("zone", {})
        key = (zone.get("type", ""), zone.get("id", ""))
        reserved.setdefault(key, set()).update(entry.get("owners", []))

    for rule in data.get("putaway_rules", []):
        rule_id = rule.get("id", "?")
        applies_to = rule.get("applies_to") or {}
        if "item_id" in applies_to:
            continue
        owner = applies_to.get("owner")
        for i, step in enumerate(rule.get("steps", [])):
            zone = step.get("zone", {})
            owners = reserved.get((zone.get("type", ""), zone.get("id", "")))
            if owners is None:
                continue
            if owner is None:
                errors.append(
                    f"{path}: putaway_rule '{rule_id}' steps[{i}]: zone '{zone.get('id')}' is reserved for owners {sorted(owners)} but the rule has no applies_to.owner"
                )
            elif owner not in owners:
                errors.append(
                    f"{path}: putaway_rule '{rule_id}' steps[{i}]: zone '{zone.get('id')}' is reserved for owners {sorted(owners)}, not '{owner}'"
                )
    return errors


def check_fixed_bin_assignments(path: Path) -> list[str]:
    """Checks strategies/fixed_bin_assignments.yaml: min_qty <= max_qty,
    max_pick_qty <= max_qty, a storage point fixed to at most one item,
    and unique sequence numbers per item. Whether item_id and
    storage_point exist in MasterData-/Topology-as-Code is a cross-repo
    check (Warehouse-as-Code backlog C1a)."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    point_owner: dict[str, str] = {}
    item_sequences: dict[str, dict[int, str]] = {}
    for i, entry in enumerate(data.get("fixed_bin_assignments", [])):
        item_id = entry.get("item_id", "?")
        point = entry.get("storage_point", "?")
        where = f"{path}: fixed_bin_assignments[{i}] ({item_id} @ {point})"

        min_qty, max_qty = entry.get("min_qty"), entry.get("max_qty")
        if isinstance(min_qty, (int, float)) and isinstance(max_qty, (int, float)) and min_qty > max_qty:
            errors.append(f"{where}: min_qty ({min_qty}) exceeds max_qty ({max_qty})")
        max_pick = entry.get("max_pick_qty")
        if isinstance(max_pick, (int, float)) and isinstance(max_qty, (int, float)) and max_pick > max_qty:
            errors.append(f"{where}: max_pick_qty ({max_pick}) exceeds max_qty ({max_qty})")

        if point in point_owner and point_owner[point] != item_id:
            errors.append(f"{where}: storage_point already fixed to item '{point_owner[point]}'")
        elif point in point_owner:
            errors.append(f"{where}: duplicate assignment of the same item to the same storage_point")
        point_owner.setdefault(point, item_id)

        sequence = entry.get("sequence", 1)
        sequences = item_sequences.setdefault(item_id, {})
        if sequence in sequences:
            errors.append(f"{where}: sequence {sequence} already used for this item at '{sequences[sequence]}'")
        sequences.setdefault(sequence, point)
    return errors


def check_search_rule_refs(path: Path, fields_data: dict | None, element_ids: dict[str, set[str]]) -> list[str]:
    """Checks search_rules.yaml's steps[].zone.type and .selection_strategy
    against structure/fields.yaml's allow-lists and
    elements/selection_strategies.yaml ids, and that no two search_rules
    share an applies_to scope (check_rule_scopes)."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    allowed_zone_types = set((fields_data or {}).get("fields", {}).get("allowed_zone_types", []))
    allowed_strategies = set((fields_data or {}).get("fields", {}).get("allowed_selection_strategies", []))
    strategy_ids = element_ids.get("selection_strategies", set())

    errors += check_rule_scopes(path, data.get("search_rules", []), "search_rule")
    for rule in data.get("search_rules", []):
        rule_id = rule.get("id", "?")

        for i, step in enumerate(rule.get("steps", [])):
            zone_type = step.get("zone", {}).get("type")
            if zone_type and allowed_zone_types and zone_type not in allowed_zone_types:
                errors.append(
                    f"{path}: search_rule '{rule_id}' steps[{i}]: zone.type '{zone_type}' not in structure/fields.yaml allowed_zone_types"
                )

            strategy = step.get("selection_strategy")
            if strategy and strategy_ids and strategy not in strategy_ids:
                errors.append(
                    f"{path}: search_rule '{rule_id}' steps[{i}]: selection_strategy '{strategy}' not found in elements/selection_strategies.yaml"
                )
            if strategy and allowed_strategies and strategy not in allowed_strategies:
                errors.append(
                    f"{path}: search_rule '{rule_id}' steps[{i}]: selection_strategy '{strategy}' not in structure/fields.yaml allowed_selection_strategies"
                )

    return errors


def check_putaway_rule_refs(path: Path, fields_data: dict | None, element_ids: dict[str, set[str]]) -> list[str]:
    """Checks putaway_rules.yaml the same way check_search_rule_refs checks
    search_rules.yaml: steps[].zone.type against allowed_zone_types,
    steps[].placement_strategy against elements/placement_strategies.yaml
    and allowed_placement_strategies, and no two rules with the same
    applies_to scope (check_rule_scopes). Also flags a step that repeats
    an earlier step's zone for the same load unit types and the same
    other constraints: every
    placement strategy finds a free place if the zone has one, so the
    later step could never be reached. A repeat with different
    constraints (e.g. a higher max_fill_percent as a late fallback) is
    legitimate and not flagged."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    fields = (fields_data or {}).get("fields", {})
    allowed_zone_types = set(fields.get("allowed_zone_types", []))
    allowed_strategies = set(fields.get("allowed_placement_strategies", []))
    strategy_ids = element_ids.get("placement_strategies", set())

    errors += check_rule_scopes(path, data.get("putaway_rules", []), "putaway_rule")
    for rule in data.get("putaway_rules", []):
        rule_id = rule.get("id", "?")

        seen: list[tuple[tuple[str, str], frozenset[str] | None, dict, int]] = []
        for i, step in enumerate(rule.get("steps", [])):
            zone = step.get("zone", {})
            zone_type = zone.get("type")
            if zone_type and allowed_zone_types and zone_type not in allowed_zone_types:
                errors.append(
                    f"{path}: putaway_rule '{rule_id}' steps[{i}]: zone.type '{zone_type}' not in structure/fields.yaml allowed_zone_types"
                )

            strategy = step.get("placement_strategy")
            if strategy and strategy_ids and strategy not in strategy_ids:
                errors.append(
                    f"{path}: putaway_rule '{rule_id}' steps[{i}]: placement_strategy '{strategy}' not found in elements/placement_strategies.yaml"
                )
            if strategy and allowed_strategies and strategy not in allowed_strategies:
                errors.append(
                    f"{path}: putaway_rule '{rule_id}' steps[{i}]: placement_strategy '{strategy}' not in structure/fields.yaml allowed_placement_strategies"
                )

            # None = no load_unit_types filter = applies to every type.
            constraints = dict(step.get("constraints", {}))
            types = constraints.pop("load_unit_types", None)
            types_set = frozenset(types) if types else None
            zone_key = (zone_type or "", zone.get("id") or "")
            for earlier_key, earlier_types, earlier_rest, earlier_index in seen:
                if earlier_key != zone_key or earlier_rest != constraints:
                    continue
                covered = earlier_types is None or (
                    types_set is not None and types_set <= earlier_types
                )
                if covered:
                    errors.append(
                        f"{path}: putaway_rule '{rule_id}' steps[{i}]: zone '{zone_key[1]}' already covered by steps[{earlier_index}] for the same load unit types and constraints - this step is unreachable"
                    )
                    break
            seen.append((zone_key, types_set, constraints, i))

    return errors


def validate_allocation_file(allocation_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a single building-level allocation.yaml and everything it imports."""
    if not allocation_file.exists():
        return [f"allocation file missing: {allocation_file}"]

    all_errors = validate_file(allocation_file, "allocation.schema.json")

    imports: dict[str, Path] = {}
    for imported in collect_imports(allocation_file):
        if not imported.exists():
            all_errors.append(f"{allocation_file}: imported file missing: {imported}")
            continue

        imports[imported.name] = imported
        name = imported.name
        if name == "fields.yaml":
            all_errors += validate_file(imported, "fields.schema.json")
        elif name == "search_rules.yaml":
            all_errors += validate_list_items(imported, "search-rule.schema.json", "search_rules")
        elif name == "putaway_rules.yaml":
            all_errors += validate_list_items(imported, "putaway-rule.schema.json", "putaway_rules")
        elif name == "owner_zones.yaml":
            all_errors += validate_file(imported, "owner-zones.schema.json")
        elif name == "fixed_bin_assignments.yaml":
            all_errors += validate_list_items(imported, "fixed-bin-assignment.schema.json", "fixed_bin_assignments")
            all_errors += check_fixed_bin_assignments(imported)
        else:
            data = load_yaml(imported)
            if data is None:
                all_errors.append(f"{imported}: File is empty or invalid.")

    fields_data = load_yaml(imports["fields.yaml"]) if "fields.yaml" in imports else {}
    if "search_rules.yaml" in imports:
        all_errors += check_search_rule_refs(imports["search_rules.yaml"], fields_data, element_ids)
    if "putaway_rules.yaml" in imports:
        all_errors += check_putaway_rule_refs(imports["putaway_rules.yaml"], fields_data, element_ids)
        if "owner_zones.yaml" in imports:
            all_errors += check_owner_zones(imports["putaway_rules.yaml"], load_yaml(imports["owner_zones.yaml"]))
        if "fixed_bin_assignments.yaml" not in imports:
            all_errors += check_fixed_bin_strategy_needs_assignments(imports["putaway_rules.yaml"])

    return all_errors


def validate_facility_file(facility_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a facility.yaml and cascades into every building it lists."""
    if not facility_file.exists():
        return [f"facility file missing: {facility_file}"]

    all_errors = validate_file(facility_file, "facility.schema.json")

    for allocation_file in collect_relative_refs(facility_file, "facility", "buildings"):
        all_errors += validate_allocation_file(allocation_file, element_ids)

    return all_errors


def validate_company_file(company_file: Path, element_ids: dict[str, set[str]] = {}) -> list[str]:
    """Validates a company.yaml and cascades into every facility it lists."""
    all_errors = validate_file(company_file, "company.schema.json")

    for facility_file in collect_relative_refs(company_file, "company", "facilities"):
        all_errors += validate_facility_file(facility_file, element_ids)

    return all_errors


def main(argv: list[str]) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if len(argv) != 2:
        print("Usage: python tools/validate.py <path-to-company|facility|allocation.yaml>")
        return 2

    target_file = Path(argv[1]).resolve()
    if not target_file.exists():
        print(f"File not found: {target_file}")
        return 2

    all_errors: list[str] = []

    for filename, (schema_name, list_key) in ELEMENT_CATALOGS.items():
        catalog_file = ELEMENTS_DIR / filename
        if catalog_file.exists():
            all_errors += validate_element_catalog(catalog_file, schema_name, list_key)

    element_ids = collect_element_ids()

    data = load_yaml(target_file)
    if data is None:
        all_errors.append(f"{target_file}: File is empty or invalid.")
    elif "company" in data:
        all_errors += validate_company_file(target_file, element_ids)
    elif "facility" in data:
        all_errors += validate_facility_file(target_file, element_ids)
    elif "allocation" in data:
        all_errors += validate_allocation_file(target_file, element_ids)
    else:
        all_errors.append(
            f"{target_file}: unrecognized root key (expected one of "
            f"'company', 'facility', 'allocation')."
        )

    if all_errors:
        print(f"❌ {len(all_errors)} validation errors found:\n")
        for e in all_errors:
            print(f"  - {e}")
        return 1

    print("✅ Validation successful.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
