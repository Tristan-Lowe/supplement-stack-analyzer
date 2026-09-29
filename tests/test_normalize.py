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
    assert strip_salt_forms("ashwagandha gummies") == "ashwagandha gummies"


def test_strip_salt_forms_drops_stereochemistry_prefixes():
    assert strip_salt_forms("magnesium l threonate") == "magnesium"
    assert strip_salt_forms("l theanine") == "theanine"
    assert strip_salt_forms("d aspartic acid") == "aspartic acid"
    assert strip_salt_forms("acetyl l carnitine") == "acetyl carnitine"


def test_trailing_letter_is_never_treated_as_a_stereo_prefix():
    """"vitamin d" must not reduce to "vitamin", which the resolver rejects as vague."""
    assert strip_salt_forms("vitamin d") == "vitamin d"
    assert strip_salt_forms("vitamin d3") == "vitamin d3"


def test_abbreviation_does_not_double_the_word_it_follows():
    """"vitamin k2" once normalized to "vitamin vitamin k2", which matches nothing."""
    assert normalize_name("Vitamin K2") == "vitamin k2"
    assert normalize_name("K2") == "vitamin k2"


def test_hcl_and_mono_are_salt_forms():
    assert strip_salt_forms(normalize_name("sertraline HCl")) == "sertraline"
    assert strip_salt_forms(normalize_name("creatine mono")) == "creatine"


def test_preparation_words_strip_but_oil_and_seed_do_not():
    assert strip_salt_forms("valerian root") == "valerian"
    assert strip_salt_forms("ginkgo biloba extract") == "ginkgo biloba"
    assert strip_salt_forms("fish oil") == "fish oil"
    assert strip_salt_forms("grape seed extract") == "grape seed"
