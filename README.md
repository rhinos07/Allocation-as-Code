# Allocation-as-Code

Allocation-as-Code: declarative, version-controlled description of **how
a matching stock search is configured for a given item/order demand** -
which zones to search, in what order, and how to select among matches -
and of its inbound counterpart, **where an incoming load unit is put
away** - as YAML, validated via CI. Fills a domain `Warehouse-as-Code`'s
Domain Map lists as "Not modeled": stock search / allocation strategy.

## Related Projects

Part of a family of sibling "-as-Code" repos sharing the same declarative
pattern (JSON Schema validation, `structure/` vs. `strategies/`,
`elements/` catalogs):

| Repo | Covers |
|---|---|
| [`Topology-as-Code`](https://github.com/rhinos07/Topology-as-Code) | Physical warehouse structure, material-flow communication, movement/replenishment rules |
| [`OrderOrchestration-as-Code`](https://github.com/rhinos07/OrderOrchestration-as-Code) | How incoming orders are split, and which downstream workflow each split triggers |
| [`MasterData-as-Code`](https://github.com/rhinos07/MasterData-as-Code) | Item/article master data, packaging/UOM hierarchy, sourcing & lifecycle rules |
| **Allocation-as-Code** (this repo) | How a matching stock search is configured (search-zone sequence, selection strategy, constraints) and where incoming stock is put away (putaway-zone sequence, placement strategy, constraints) |

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
| `elements/` | Reusable catalogs (selection strategies, placement strategies) | very rarely | Architect |
| `customers/<customer>/company.yaml` | Tenant/organization identity | very rarely (onboarding/offboarding) | Admin |
| `customers/<customer>/facilities/<facility>/facility.yaml` | Site/plant identity | rarely | Admin/Technician |
| `.../buildings/<building>/structure/` | Allowed zone types / selection and placement strategies for this building | rarely | Technician, strict review |
| `.../buildings/<building>/strategies/search_rules.yaml` | The actual search sequence per item/category - **the customizable part** | frequently | Logistics Planner, lenient review |
| `.../buildings/<building>/strategies/putaway_rules.yaml` | The actual putaway sequence per item/category - inbound counterpart of `search_rules.yaml` | frequently | Logistics Planner, lenient review |

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
│   ├── selection-strategy.schema.json
│   ├── putaway-rule.schema.json
│   ├── placement-strategy.schema.json
│   ├── applies-to.schema.json    # Shared rule scope: item / owner / category
│   ├── owner-zones.schema.json   # Zones reserved for stock owners
│   └── fixed-bin-assignment.schema.json # Item -> fixed place with min/max
├── elements/
│   ├── selection_strategies.yaml # Catalog: FIFO, FEFO, LIFO, NEAREST_TO_TARGET, LOWEST_QUANTITY_FIRST
│   └── placement_strategies.yaml # Catalog: NEXT_EMPTY, ADD_TO_EXISTING, FIXED_BIN_FIRST, ...
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
│                       │   ├── fields.yaml         # Allowed zone types / selection and placement strategies
│                       │   └── owner_zones.yaml    # Optional: zones reserved for stock owners
│                       └── strategies/
│                           ├── search_rules.yaml   # Ordered search sequence per item/category
│                           ├── putaway_rules.yaml  # Ordered putaway sequence per item/category
│                           ├── fixed_bin_assignments.yaml # Optional: item -> fixed place, min/max
│                           └── area_assignments.yaml  # Optional: item -> zone, min/max/planned
├── tools/
│   ├── validate.py           # Validation script (schema + cross-file consistency checks)
│   └── precedence.py         # Reference implementation of applies_to precedence
├── tests/
│   ├── test_putaway_rules.py # Unit tests for the putaway validation rules
│   ├── test_owner_scopes.py  # Unit tests for owner scopes, precedence and owner zones
│   └── test_fixed_bins.py    # Unit tests for fixed bin assignments
├── docs/
│   └── entity-glossary.md
└── .github/workflows/validate.yaml   # CI pipeline (dynamic per-customer matrix)
```

## Schema Versioning

Every `allocation.yaml` declares the schema generation it conforms to:

```yaml
api_version: "allocation-as-code/v1"
```

It sits on the building because that is this repo's self-contained,
independently loadable scope - the same role `warehouse.yaml` plays in
`Topology-as-Code`. `company.yaml` and `facility.yaml` index the level
below them rather than being datasets of their own, so they carry no
version.

An incompatible change raises the version rather than silently
reinterpreting existing data. See
[`Warehouse-as-Code` ADR-0001](https://github.com/rhinos07/Warehouse-as-Code/blob/main/docs/adr/0001-layered-specification-model.md),
measure 2.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Validates a company.yaml, facility.yaml, or allocation.yaml - cascades
# down to every facility/building it references
python tools/validate.py customers/example_customer/company.yaml

# Unit tests for the validation rules
python -m unittest discover -s tests -v
```

## Examples

- `customers/example_customer/facilities/facility_pa11/buildings/hall_3/`
  - re-uses `Topology-as-Code`'s real `hall_3` zone ids
    (`PICK_ZONE_A`, `AUTOSTORE_A`, `HBR`) so the example stays checkable
    against real topology, not invented ids.
  - `SEARCH_DEFAULT` - the building's fallback rule (no `applies_to`):
    search `PICK_ZONE_A`, then `AUTOSTORE_A`, then `HBR`, all `FIFO`.
    Sequenced pickface first, then the automated cell, bulk rack last.
    `AUTOSTORE_A` matters beyond ordering: it is this building's only
    zone resolving to `Topology-as-Code`'s `autostore` technology, so
    without it a search-driven allocation could never produce the
    AutoStore/manual split `OrderOrchestration-as-Code`'s `b2c_standard`
    scenario describes (`HBR` resolves to `shuttle`, a technology no
    example `split_rule` claims - found by `WMS-POC` actually running
    this rule against real technology data, see its README Finding #9).
  - `SEARCH_ITEM_003_FEFO` - a more specific rule for `ITEM_003` (the
    same item id used in `OrderOrchestration-as-Code`'s `WMS-POC`
    inbound scenario): `FEFO` with a 30-day minimum remaining shelf
    life and quality-hold stock excluded, same two zones.
  - `PUTAWAY_DEFAULT` - the building's fallback putaway rule: cartons
    first top up their item's fixed places in `FIX` (`FIXED_BIN_FIRST`),
    AutoStore bins go to `AUTOSTORE_A` (the grid controller picks the place),
    pallets to `HBR` spread across aisles up to 90 % fill, with `BLK` as
    the pallet and mesh-box fallback. Steps filter by
    `load_unit_types`, so the step order also ranks which zone each load
    unit type prefers.
  - `PUTAWAY_ITEM_003_LOT_PURE` - lot-pure places for the FEFO item
    `ITEM_003`, so the FEFO search finds one lot per place. Open:
    `ITEM_003` cannot be routed to `COLD_ZONE_B` by item property, because
    `MasterData-as-Code` has no storage-condition attribute yet.
  - `fixed_bin_assignments.yaml` - `ITEM_001` on two fixed places in
    `FIX` (sequence 1 and 2, max 24 per pick), `ITEM_002` on one. These
    item-level min/max win over `Topology-as-Code`'s area-level
    `REPL_PICKFACE_A` for the same places.

## Core Concepts (Quick Reference)

- **search_rule** — the ordered search sequence for a given
  `applies_to` scope (`item_id`, `owner` + `category`, `owner`,
  `category`, or omitted for the building's default - most specific
  wins). See `docs/entity-glossary.md`.
- **stock owners** — in multi-owner warehouses, rules can be scoped per
  owner, putaway can forbid mixing owners on one place
  (`allow_mixed_owners`), and `structure/owner_zones.yaml` reserves zones
  for given owners.
- **step** — one zone + `selection_strategy` + optional `constraints`
  within a `search_rule`, tried in order.
- **selection_strategy** — how to pick among multiple matches within one
  step's zone (`FIFO`/`FEFO`/`LIFO`/`NEAREST_TO_TARGET`/`LOWEST_QUANTITY_FIRST`).
- **putaway_rule** — the inbound counterpart of `search_rule`: the
  ordered zone sequence in which to look for a free place, per
  `applies_to` scope, same precedence rules.
- **placement_strategy** — how to choose one free place within one
  putaway step's zone (`NEXT_EMPTY`/`ADD_TO_EXISTING`/`NEAREST_TO_SOURCE`/
  `NEAREST_TO_OUTFEED`/`SPREAD_ACROSS_AISLES`/`LOWEST_LEVEL_FIRST`/
  `DELEGATE_TO_CONTROLLER`/`FIXED_BIN_FIRST`).
- **fixed_bin_assignment** — an item fixed to one storage place (pick
  face) with item-level `min_qty`/`max_qty`/`max_pick_qty` and a
  `sequence` among several places of the same item. A place is fixed to
  at most one item. Item-level values win over an area-level
  `Topology-as-Code` `replenishment_strategy`.
- **area_assignment** — item-level stock targets (`min_qty`/`max_qty`,
  optional `planned_qty`) for one zone **without** fixed places, e.g. a
  dynamic pick zone. Typically written by a script from a slotting or
  ABC analysis; this repo stores the result, it does not compute it.
  Wins over an area-level `replenishment_strategy` for the same zone;
  inside the zone, a `fixed_bin_assignment` governs the item's fixed
  places.

Full glossary: [`docs/entity-glossary.md`](docs/entity-glossary.md)

## Next Steps for This Repo

- [ ] Build out `MasterData-as-Code` far enough that `applies_to.category`/
      `applies_to.item_id` can be cross-checked against real ids (same
      category of gap every sibling repo already has against each other).
- [ ] Cross-check `search_rule.steps[].zone.id` against an actual
      `Topology-as-Code` `storage_type`/`activity_area` id - not done,
      same category of gap `OrderOrchestration-as-Code` has for `target.id`.
- [x] ~~Decide whether `applies_to` needs a tie-break rule for two rules
      of equal specificity~~ - with the precedence item_id > owner +
      category > owner > category > default, identical scopes are the only
      possible tie, and `tools/validate.py` rejects them (see
      `docs/entity-glossary.md` "Applies-To Precedence").
- [ ] Cross-check `applies_to.owner` / `.category` / `.item_id` against
      `MasterData-as-Code`, and putaway rules scoped by `item_id` against
      `owner_zones` via the item's owner - cross-repo, not done here.
- [ ] Cross-check `putaway_rule.steps[].constraints.load_unit_types`
      against `Topology-as-Code` `load_unit_type` ids and the zone's
      `allowed_load_unit_types`, and `allow_mixed_items: true` against the
      zone's `homogeneity_required` - not done, same cross-repo gap as
      zone ids.
- [ ] Route items to zones by storage condition (e.g. temperature) once
      `MasterData-as-Code` has such an attribute.
- [x] ~~Add a `FIXED_BIN_FIRST` placement strategy once fixed
      item-to-place assignments are modeled~~ - done with
      `strategies/fixed_bin_assignments.yaml`.
- [ ] Cross-check `fixed_bin_assignments` against `Topology-as-Code`
      (storage_point exists, its storage_type allows the item's load unit)
      and `MasterData-as-Code` (item and uom exist; the place's zone is
      not reserved for another owner) - cross-repo, not done here.
- [ ] Consider whether `search_rule` needs an explicit `order_type`/
      `channel` scope (mirroring `OrderOrchestration-as-Code`) in
      addition to item/category - not yet needed by any real scenario.

### Out of Scope (By Design)

- **Runtime state**: actual live on-hand quantities, reservations, which
  storage_point/batch a search actually resolved to, which free place a
  putaway actually booked - that's the WMS runtime database, not here.
- **Item/article master data**: that's `MasterData-as-Code`.
- **Warehouse structure**: zone/storage_type definitions themselves -
  that's `Topology-as-Code`. This repo only references zone ids by
  string, the same way `OrderOrchestration-as-Code` references `target`
  ids.
- **Order splitting**: deciding how many fulfillable units an order
  becomes - that's `OrderOrchestration-as-Code`.
