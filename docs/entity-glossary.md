# Entity Glossary

## Organizational Hierarchy

| Term | Meaning |
|---|---|
| `company` | Top-level tenant/organization (`company.yaml`). Lists one or more `facility` files. |
| `facility` | A site/plant belonging to a company (`facility.yaml`). Lists one or more `allocation` (building) files. `id` is meant to match the same facility id in `Topology-as-Code` - convention, not a schema-enforced link. |
| `allocation` | A building's stock-search configuration (`allocation.yaml`). Imports its own `structure/` and `strategies/`. `id` is meant to match the same building id in `Topology-as-Code`. |

A company can have multiple facilities, and each facility can have
multiple buildings - **Company → Facility → Building**, the same shape
`Topology-as-Code` uses. `tools/validate.py` accepts a path at any of the
three levels and cascades validation downward automatically.

## Structure

| Term | Meaning |
|---|---|
| `fields` | Per-building restriction of which zone types (`storage_type`/`activity_area`), which `elements/selection_strategies.yaml` ids this building's `search_rule`s may use, and which `elements/placement_strategies.yaml` ids its `putaway_rule`s may use (`structure/fields.yaml`). |

## Process Rules

| Term | Meaning |
|---|---|
| `search_rule` | The customizable core of this repo (`strategies/search_rules.yaml`): for a given `applies_to` scope (a `category` or `item_id`, both referencing `MasterData-as-Code`), an ordered `steps` sequence of zones to search. Exactly one `search_rule` per building should omit `applies_to` entirely - that's the default/fallback rule used when nothing more specific matches; `tools/validate.py` flags it if more than one building-level rule tries to be the default. |
| `step` | One entry in a `search_rule.steps` list: a `zone` (a `Topology-as-Code` `storage_type` or `activity_area` id), a `selection_strategy` (references `elements/selection_strategies.yaml`), and optional `constraints` (`exclude_quality_hold`, `min_remaining_shelf_life_days`). Steps are tried in order - step 2 is a fallback only consulted if step 1 doesn't yield enough matching quantity. |
| `selection_strategy` | How to choose among multiple matching candidates found within one step's zone (`elements/selection_strategies.yaml`) - e.g. `FEFO` (earliest expiry first), `FIFO`, `LIFO`, `NEAREST_TO_TARGET`, `LOWEST_QUANTITY_FIRST`. |
| `putaway_rule` | Inbound counterpart of `search_rule` (`strategies/putaway_rules.yaml`): for a given `applies_to` scope, an ordered `steps` sequence of zones in which to look for a free place for an incoming load unit. Same default rule (at most one without `applies_to`) and same precedence as `search_rule`. Modeled after myWMS `StorageStrategy` / `StorageStrategyArea`. |
| putaway `step` | One entry in a `putaway_rule.steps` list: a `zone`, a `placement_strategy` (references `elements/placement_strategies.yaml`) and optional `constraints`: `load_unit_types` (step applies only to these Topology-as-Code load unit types), `allow_mixed_items`, `allow_mixed_lots`, `max_fill_percent`. Because steps filter by load unit type, the step order also ranks which zone each load unit type prefers (OpenWMS `TypePlacingRule.privilege_level`). `tools/validate.py` flags a step whose zone, load unit types and other constraints an earlier step of the same rule already covers - it could never be reached. Repeating a zone with different constraints (e.g. `HBR` up to 80 %, then `BLK`, then `HBR` up to 95 %) is allowed. |
| `placement_strategy` | How to choose one free place within one putaway step's zone (`elements/placement_strategies.yaml`) - e.g. `NEXT_EMPTY`, `ADD_TO_EXISTING`, `NEAREST_TO_SOURCE`, `NEAREST_TO_OUTFEED`, `SPREAD_ACROSS_AISLES`, `LOWEST_LEVEL_FIRST`, `DELEGATE_TO_CONTROLLER` (the WMS picks only the zone, the zone's controller picks the place). |

## Applies-To Precedence

When multiple `search_rule`s could match the same item, the most
specific one wins: an `applies_to.item_id` rule beats an
`applies_to.category` rule for that item, which beats the building's
default (`applies_to` omitted) rule. This repo does not model what
happens if two rules with the *same* specificity both match (e.g. two
different `item_id` rules naming the same id) - `tools/validate.py`
does not currently check for that duplicate-scope case.

`putaway_rule`s follow the same precedence, with the same open
duplicate-scope case.

## What This Repo Is Not

It does not track live on-hand quantities, reservations, which specific
storage_point/batch actually got picked for a given demand, or which
free place a putaway actually booked - that's runtime allocation state
in the WMS, not modeled here or anywhere else in this repo family (see
`Warehouse-as-Code`'s Domain Map). This repo only defines the **search
and putaway strategies**: which zones to look in, in what order, and how
to pick among matches or free places once live inventory is searched -
the "how", not the "what's actually there right now".
Analogous to Terraform: the code describes the search policy, not any
single search's live result.
