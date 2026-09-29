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


def test_bare_trailing_dose_is_split_off_without_a_unit():
    [item] = parse_stack_text("NAC 600")
    assert (item.raw, item.amount, item.unit) == ("NAC", 600.0, None)


def test_small_trailing_numbers_stay_part_of_the_name():
    assert parse_stack_text("omega 3")[0].raw == "omega 3"
    assert parse_stack_text("vitamin b 12")[0].raw == "vitamin b 12"
    assert parse_stack_text("ashwagandha KSM-66")[0].raw == "ashwagandha KSM-66"
