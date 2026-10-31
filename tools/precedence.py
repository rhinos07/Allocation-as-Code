"""
Reference implementation of the applies_to precedence shared by
search_rule and putaway_rule. A runtime selecting the rule for an item
must give the same answer; tests/test_owner_scopes.py pins it.

Precedence, most specific first:

    item_id  >  owner + category  >  owner  >  category  >  default

Ties cannot occur once tools/validate.py has accepted the file: an item
has exactly one id, owner and category, so two different scopes of the
same rank never both match, and identical scopes are rejected.
"""

SPECIFICITY = {
    ("item_id",): 5,
    ("category", "owner"): 4,
    ("owner",): 3,
    ("category",): 2,
    (): 1,
}


def scope_key(applies_to: dict | None) -> tuple[tuple[str, str], ...]:
    """Normalised, hashable form of an applies_to scope; () = default rule."""
    return tuple(sorted((applies_to or {}).items()))


def specificity(applies_to: dict | None) -> int:
    """Rank of a scope; 0 for a combination the schema does not allow."""
    return SPECIFICITY.get(tuple(sorted((applies_to or {}).keys())), 0)


def matches(applies_to: dict | None, item: dict) -> bool:
    """Whether a rule scope matches an item given as
    {"id": ..., "category": ..., "owner": ...}."""
    fields = {"item_id": item.get("id"), "category": item.get("category"), "owner": item.get("owner")}
    return all(fields.get(key) == value for key, value in (applies_to or {}).items())


def select_rule(rules: list[dict], item: dict) -> dict | None:
    """The most specific matching rule for an item, or None."""
    candidates = [rule for rule in rules if matches(rule.get("applies_to"), item)]
    if not candidates:
        return None
    return max(candidates, key=lambda rule: specificity(rule.get("applies_to")))
