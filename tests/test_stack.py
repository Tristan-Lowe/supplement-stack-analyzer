from ssa.stack import StackItem, parse_stack_text


def test_parses_name_dose_and_unit():
    items = parse_stack_text("Magnesium Glycinate 400mg")
    assert items == [StackItem(raw="Magnesium Glycinate", amount=400.0, unit="mg")]


def test_parses_multiple_lines():
    items = parse_stack_text("Vitamin D3 5000iu\nZinc 30 mg\nCreatine 5g")
    assert [i.raw for i in items] == ["Vitamin D3", "Zinc", "Creatine"]
    assert [i.unit for i in items] == ["iu", "mg", "g"]


def test_parses_comma_separated():
    items = parse_stack_text("Zinc 30mg, Copper 2mg")
    assert len(items) == 2
    assert items[1].raw == "Copper"


def test_item_without_dose_has_none_amount():
    items = parse_stack_text("Ashwagandha")
    assert items == [StackItem(raw="Ashwagandha", amount=None, unit=None)]


def test_blank_lines_are_ignored():
    items = parse_stack_text("Zinc 30mg\n\n   \nCopper 2mg")
    assert len(items) == 2


def test_mcg_and_iu_units_are_recognized():
    items = parse_stack_text("Vitamin B12 1000mcg\nVitamin D 2000 IU")
    assert items[0].unit == "mcg"
    assert items[1].unit == "iu"
