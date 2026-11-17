from fitplate.domain import extract_items, fresh_draft, update_draft, validate_draft


def test_missing_portions_are_not_invented():
    items = extract_items("Lunch was chicken breast, rice and broccoli")
    assert len(items) == 3
    assert all(item["quantity"] is None for item in items)


def test_portions_and_preparation():
    items = extract_items("150 g cooked chicken breast, 120 g rice and 80 g broccoli")
    assert [item["quantity"] for item in items] == [150, 120, 80]
    assert items[0]["preparation"] == "Cooked"


def test_follow_up_preserves_foods_and_identity():
    draft, _ = update_draft(fresh_draft(), "Chicken breast, rice and broccoli")
    updated, _ = update_draft(draft, "150 g chicken breast")
    assert updated["id"] == draft["id"]
    assert len(updated["items"]) == 3
    assert updated["items"][0]["quantity"] == 150
    assert draft["items"][0]["quantity"] is None


def test_invalid_portion_cannot_be_confirmed():
    draft, _ = update_draft(fresh_draft(), "0 g rice")
    assert "positive portion" in validate_draft(draft)


def test_count_portion_unit():
    item = extract_items("2 eggs")[0]
    assert (item["quantity"], item["unit"]) == (2, "piece")

