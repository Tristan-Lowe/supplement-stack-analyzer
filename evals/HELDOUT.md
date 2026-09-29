# Held-out resolution checks on real DSLD labels

The gold set (`resolution_gold.jsonl`) and the curated synonyms were written by the
same person, so a perfect gold score partly measures self-consistency. These runs use
ingredient names written by manufacturers on real NIH DSLD labels. Every resolved
row was checked by hand.

## v1 — 2026-09-29, before the identity-token guard

Queries: magnesium glycinate, fish oil, vitamin d3, ashwagandha, turmeric curcumin,
st john's wort, ginkgo biloba, coq10, zinc, melatonin, iron, calcium magnesium zinc,
creatine, vitamin b complex, prenatal multivitamin, garlic, green tea extract, milk
thistle, saw palmetto, vitamin k2.

| | |
|---|---|
| Unique ingredient names | 101 |
| Resolved | 49 |
| **Resolved to the wrong entity** | **3** |

The three wrong answers, none of which the hand-written gold set caught:

- `Vitamin B1` -> Vitamin K (fuzzy against "vitamin k1", score 90)
- `Vitamin B2` -> Vitamin K (fuzzy against "vitamin k2")
- `Vitamin B3` -> Vitamin D3 (fuzzy against "vitamin d3")

The digit guard compared numbers only. Fixed by treating every token that carries a
digit or is one or two letters long as identity. v1 was then used to add registry
entries (B1, B2, B5, piperine, and others), so it is no longer held out. Raw output:
`dsld_heldout_v1_before.json`.

## v2 — 2026-09-29, after all fixes, fresh queries

Queries: magnesium citrate, omega 3, vitamin c, elderberry, probiotic, collagen,
biotin, vitamin b12, echinacea, valerian root, kava, rhodiola, berberine, mens
multivitamin, glucosamine chondroitin, sleep support, cranberry, 5-htp, l-theanine,
potassium.

| | |
|---|---|
| Unique ingredient names | 105 |
| Resolved | 50 |
| **Resolved to the wrong entity** | **0** |
| Unresolved but the substance is in the registry | ~8 |
| Unresolved and not in the registry, or not a compound | ~47 |

Missed although the registry has the substance: `Aged Garlic extract powder`,
`Chondroitin Sulfate Sodium`, `Coenzyme Q-10`, `Echinacea angustifolia extract`,
`R-Alpha Lipoic Acid`, `organic Turmeric`, `Glucosamine Sulfate 2KCl`,
`Siberian Rhodiola root`. Left unfixed so this run stays a measurement.

Not in the registry: elderberry, lutein, lycopene, boron, MSM, hyaluronic acid,
collagen, probiotic strains, inulin, tribulus, mullein, vanadium, silicon, and
nutrition-facts rows (calories, total fat, sugars).

Raw output: `dsld_heldout_v2.json`.

## Reading these numbers

- **Precision on real labels: 50/50.** A wrong resolution is a false claim about what
  someone takes. That is the number to protect.
- **Recall on in-registry names: about 50/58 (86%).** The misses are Unknown, which the
  product shows the user, not silent drops.
- **Coverage is the bigger gap.** Roughly half of real label rows name something the
  registry does not hold yet.
