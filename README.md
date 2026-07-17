# Allocation-as-Code

Allocation-as-Code: declarative, version-controlled description of **how
a matching stock search is configured for a given item/order demand** -
which zones to search, in what order, and how to select among matches -
as YAML, validated via CI. Fills a domain `Warehouse-as-Code`'s Domain
Map lists as "Not modeled": stock search / allocation strategy.

## Related Projects

Part of a family of sibling "-as-Code" repos sharing the same declarative
pattern (JSON Schema validation, `structure/` vs. `strategies/`,
`elements/` catalogs):

| Repo | Covers |
|---|---|
| [`Topology-as-Code`](https://github.com/rhinos07/Topology-as-Code) | Physical warehouse structure, material-flow communication, movement/replenishment rules |
| [`OrderOrchestration-as-Code`](https://github.com/rhinos07/OrderOrchestration-as-Code) | How incoming orders are split, and which downstream workflow each split triggers |
| [`MasterData-as-Code`](https://github.com/rhinos07/MasterData-as-Code) | Item/article master data, packaging/UOM hierarchy, sourcing & lifecycle rules |
| **Allocation-as-Code** (this repo) | How a matching stock search is configured: search-zone sequence, selection strategy, constraints |

This repo's `search_rule.steps[].zone` references `Topology-as-Code`
`storage_type`/`activity_area` ids, and `search_rule.applies_to`
references `MasterData-as-Code` `category`/`item_id`s - same
loosely-coupled, string-id cross-repo referencing every sibling repo
already uses (see each repo's own "Open Validation Gaps"). `facility.id`
and `allocation.id` are meant to match the same facility/building ids in
`Topology-as-Code` - convention, not a schema-enforced link.

## Core Principle

| Layer | What | Change Frequency | Who Changes It |
|---|---|---|---|
| `elements/` | Reusable catalog (selection strategies) | very rarely | Architect |
| `customers/<customer>/company.yaml` | Tenant/organization identity | very rarely (onboarding/offboarding) | Admin |
| `customers/<customer>/facilities/<facility>/facility.yaml` | Site/plant identity | rarely | Admin/Technician |
| `.../buildings/<building>/structure/` | Allowed zone types / selection strategies for this building | rarely | Technician, strict review |
| `.../buildings/<building>/strategies/search_rules.yaml` | The actual search sequence per item/category - **the customizable part** | frequently | Logistics Planner, lenient review |

A company can have multiple facilities, and each facility can have
multiple buildings - **Company → Facility → Building**, the same shape
`Topology-as-Code` uses: a stable identity layer, then a `structure/`
vs. `strategies/` split by change frequency and reviewer.
`strategies/search_rules.yaml` is deliberately the frequently-changed,
lenient-review layer - that's what "should also be configurable" means
in practice: logistics planners edit search sequences without touching
`structure/` or schemas.

**What this repo is not**: it does not track live on-hand quantities,
reservations, or which specific storage_point/batch was actually picked
for a demand - that's runtime allocation state in the WMS, not modeled
here (see `docs/entity-glossary.md` "What This Repo Is Not"). It does
not define warehouse structure (`Topology-as-Code`) or item master data
(`MasterData-as-Code`). It does not decide *how* an order is split into
fulfillable units (`OrderOrchestration-as-Code`'s `split_rule`) - this
repo only defines, for a given item, where to look for matching stock
and in what order, once something (the runtime WMS, given an
`OrderOrchestration-as-Code` order position) needs to search.

## Repo Structure

```
allocation-definitions/
├── schemas/                      # JSON Schema for validating all YAML files
│   ├── company.schema.json
│   ├── facility.schema.json
│   ├── allocation.schema.json    # Building-level entry file
│   ├── fields.schema.json        # Allowed zone types / selection strategies
│   ├── search-rule.schema.json
│   └── selection-strategy.schema.json
├── elements/
│   └── selection_strategies.yaml # Catalog: FIFO, FEFO, LIFO, NEAREST_TO_TARGET, LOWEST_QUANTITY_FIRST
├── customers/
│   └── <customer>/                          # = Company
│       ├── company.yaml                     # Top level, lists facilities
│       └── facilities/
│           └── <facility>/                  # = Facility (site/plant)
│               ├── facility.yaml            # Lists buildings
│               └── buildings/
│                   └── <building>/          # = Building
│                       ├── allocation.yaml         # Imports structure/strategies below
│                       ├── structure/
│                       │   └── fields.yaml         # Allowed zone types / selection strategies
│                       └── strategies/
│                           └── search_rules.yaml   # Ordered search sequence per item/category
├── tools/
│   └── validate.py           # Validation script (schema + cross-file consistency checks)
├── docs/
│   └── entity-glossary.md
└── .github/workflows/validate.yaml   # CI pipeline (dynamic per-customer matrix)
```

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Validates a company.yaml, facility.yaml, or allocation.yaml - cascades
# down to every facility/building it references
python tools/validate.py customers/example_customer/company.yaml
```

## Examples

- `customers/example_customer/facilities/facility_pa11/buildings/hall_3/`
  - re-uses `Topology-as-Code`'s real `hall_3` zone ids
    (`PICK_ZONE_A`, `HBR`) so the example stays checkable against real
    topology, not invented ids.
  - `SEARCH_DEFAULT` - the building's fallback rule (no `applies_to`):
    search `PICK_ZONE_A` first, then `HBR`, both `FIFO`.
  - `SEARCH_ITEM_003_FEFO` - a more specific rule for `ITEM_003` (the
    same item id used in `OrderOrchestration-as-Code`'s `WMS-POC`
    inbound scenario): `FEFO` with a 30-day minimum remaining shelf
    life and quality-hold stock excluded, same two zones.

## Core Concepts (Quick Reference)

- **search_rule** — the ordered search sequence for a given
  `applies_to` scope (`category` or `item_id`, or omitted for the
  building's default). See `docs/entity-glossary.md`.
- **step** — one zone + `selection_strategy` + optional `constraints`
  within a `search_rule`, tried in order.
- **selection_strategy** — how to pick among multiple matches within one
  step's zone (`FIFO`/`FEFO`/`LIFO`/`NEAREST_TO_TARGET`/`LOWEST_QUANTITY_FIRST`).

Full glossary: [`docs/entity-glossary.md`](docs/entity-glossary.md)

## Next Steps for This Repo

- [ ] Build out `MasterData-as-Code` far enough that `applies_to.category`/
      `applies_to.item_id` can be cross-checked against real ids (same
      category of gap every sibling repo already has against each other).
- [ ] Cross-check `search_rule.steps[].zone.id` against an actual
      `Topology-as-Code` `storage_type`/`activity_area` id - not done,
      same category of gap `OrderOrchestration-as-Code` has for `target.id`.
- [ ] Decide whether `applies_to` needs a tie-break rule for two rules of
      equal specificity naming the same scope (see `docs/entity-glossary.md`
      "Applies-To Precedence") - not yet a problem with only two example
      rules, deliberately not designed prematurely.
- [ ] Consider whether `search_rule` needs an explicit `order_type`/
      `channel` scope (mirroring `OrderOrchestration-as-Code`) in
      addition to item/category - not yet needed by any real scenario.

### Out of Scope (By Design)

- **Runtime state**: actual live on-hand quantities, reservations, which
  storage_point/batch a search actually resolved to - that's the WMS
  runtime database, not here.
- **Item/article master data**: that's `MasterData-as-Code`.
- **Warehouse structure**: zone/storage_type definitions themselves -
  that's `Topology-as-Code`. This repo only references zone ids by
  string, the same way `OrderOrchestration-as-Code` references `target`
  ids.
- **Order splitting**: deciding how many fulfillable units an order
  becomes - that's `OrderOrchestration-as-Code`.
