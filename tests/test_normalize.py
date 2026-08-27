from ssa.normalize import normalize_name, strip_salt_forms


def test_lowercases_and_collapses_whitespace():
    assert normalize_name("  Magnesium   Glycinate ") == "magnesium glycinate"


def test_removes_punctuation_and_hyphens():
    assert normalize_name("Bis-Glycinate, Chelated") == "bis glycinate chelated"


def test_expands_common_abbreviations():
    assert normalize_name("Mag glycinate") == "magnesium glycinate"
    assert normalize_name("Vit D3") == "vitamin d3"


def test_normalizes_unicode_dashes():
    assert normalize_name("Omega–3") == "omega 3"


def test_strip_salt_forms_removes_known_salts():
    assert strip_salt_forms("magnesium bisglycinate") == "magnesium"
    assert strip_salt_forms("magnesium citrate") == "magnesium"
    assert strip_salt_forms("zinc picolinate") == "zinc"


def test_strip_salt_forms_leaves_unknown_words():
    assert strip_salt_forms("ashwagandha root") == "ashwagandha root"
