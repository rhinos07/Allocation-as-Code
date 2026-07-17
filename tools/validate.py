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

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schemas"
ELEMENTS_DIR = REPO_ROOT / "elements"

ELEMENT_CATALOGS = {
    "selection_strategies.yaml": ("selection-strategy.schema.json", "selection_strategies"),
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


def check_search_rule_refs(path: Path, fields_data: dict | None, element_ids: dict[str, set[str]]) -> list[str]:
    """Checks search_rules.yaml's steps[].zone.type and .selection_strategy
    against structure/fields.yaml's allow-lists and
    elements/selection_strategies.yaml ids. Also checks that at most one
    search_rule per building omits applies_to (the default/fallback rule)."""
    errors: list[str] = []
    data = load_yaml(path)
    if not data:
        return errors

    allowed_zone_types = set((fields_data or {}).get("fields", {}).get("allowed_zone_types", []))
    allowed_strategies = set((fields_data or {}).get("fields", {}).get("allowed_selection_strategies", []))
    strategy_ids = element_ids.get("selection_strategies", set())

    default_rule_ids = []
    for rule in data.get("search_rules", []):
        rule_id = rule.get("id", "?")
        if not rule.get("applies_to"):
            default_rule_ids.append(rule_id)

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

    if len(default_rule_ids) > 1:
        errors.append(
            f"{path}: multiple search_rules omit applies_to (ambiguous default): {default_rule_ids}"
        )

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
        else:
            data = load_yaml(imported)
            if data is None:
                all_errors.append(f"{imported}: File is empty or invalid.")

    fields_data = load_yaml(imports["fields.yaml"]) if "fields.yaml" in imports else {}
    if "search_rules.yaml" in imports:
        all_errors += check_search_rule_refs(imports["search_rules.yaml"], fields_data, element_ids)

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
