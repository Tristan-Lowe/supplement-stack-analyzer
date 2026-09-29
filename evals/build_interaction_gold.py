"""Build evals/interaction_gold.jsonl from quotes in independent public sources.

Sources are deliberately ones the pipeline never reads: NCCIH herb pages and FDA
consumer updates. The pipeline reads openFDA drug labels (and, planned, NIH ODS
fact sheets), so a gold set built from those would measure extraction fidelity,
not whether the product catches what matters.

Every row's quote must appear verbatim in the cached source text under
evals/cache/, or the build fails. `member_note` marks rows where the source names
a class ("blood thinner medications") and the row picks one member (warfarin) —
a class-to-member extrapolation, flagged so a reviewer can see it.

    python -m evals.build_interaction_gold
"""

from __future__ import annotations

import json
from pathlib import Path

CACHE = Path("evals/cache")
OUT = Path("evals/interaction_gold.jsonl")

NCCIH = "https://www.nccih.nih.gov/health/"
FDA_GRAPEFRUIT = (
    "https://www.fda.gov/consumers/consumer-updates/grapefruit-juice-and-some-drugs-dont-mix"
)
FDA_MIXING = (
    "https://www.fda.gov/consumers/consumer-updates/"
    "mixing-medications-and-dietary-supplements-can-endanger-your-health"
)

SJW_LIST = "St. John’s wort can weaken the effects of many medicines"

# (a, b, cache file, source url, quote, member_note)
ROWS: list[tuple[str, str, str, str, str, str]] = [
    # --- St. John's wort (NCCIH) ---
    ("St. John's Wort", "amitriptyline", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some antidepressants, including amitriptyline and bupropion", ""),
    ("St. John's Wort", "bupropion", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some antidepressants, including amitriptyline and bupropion", ""),
    ("St. John's Wort", "cyclosporine", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Cyclosporine, which prevents the body from rejecting transplanted organs", ""),
    ("St. John's Wort", "phenytoin", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some drugs used to prevent seizures, including phenytoin and carbamazepine", ""),
    ("St. John's Wort", "carbamazepine", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some drugs used to prevent seizures, including phenytoin and carbamazepine", ""),
    ("St. John's Wort", "digoxin", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some heart medications, including digoxin and ivabradine", ""),
    ("St. John's Wort", "ivabradine", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some heart medications, including digoxin and ivabradine", ""),
    ("St. John's Wort", "indinavir", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some HIV drugs, including indinavir and nevirapine", ""),
    ("St. John's Wort", "nevirapine", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some HIV drugs, including indinavir and nevirapine", ""),
    ("St. John's Wort", "irinotecan", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some cancer medications, including irinotecan, imatinib, and docetaxel", ""),
    ("St. John's Wort", "imatinib", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some cancer medications, including irinotecan, imatinib, and docetaxel", ""),
    ("St. John's Wort", "docetaxel", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Some cancer medications, including irinotecan, imatinib, and docetaxel", ""),
    ("St. John's Wort", "warfarin", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Warfarin, an anticoagulant (blood thinner)", ""),
    ("St. John's Wort", "simvastatin", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "Certain statins, including simvastatin", ""),
    ("St. John's Wort", "sertraline", "nccih-st-johns-wort", NCCIH + "st-johns-wort",
     "taking St. John’s wort with certain antidepressants or other drugs that affect "
     "serotonin", "source says 'certain antidepressants'; sertraline chosen as an SSRI"),
    ("St. John's Wort", "levonorgestrel", "fda-mixing", FDA_MIXING,
     "birth control pills are less effective when taken with St. John’s wort",
     "source says 'birth control pills'; levonorgestrel chosen as a common pill ingredient"),
    # --- bleeding cluster (FDA) ---
    ("Ginkgo biloba", "warfarin", "nccih-ginkgo", NCCIH + "ginkgo",
     "Ginkgo may increase the risk of bleeding in people who are taking anticoagulant "
     "drugs, such as warfarin.", ""),
    ("Ginkgo biloba", "aspirin", "fda-mixing", FDA_MIXING,
     "warfarin (a prescription blood thinner), ginkgo biloba (an herbal supplement), "
     "aspirin, and vitamin E (a supplement) can each thin the blood", ""),
    ("Vitamin E", "warfarin", "fda-mixing", FDA_MIXING,
     "warfarin (a prescription blood thinner), ginkgo biloba (an herbal supplement), "
     "aspirin, and vitamin E (a supplement) can each thin the blood", ""),
    ("Garlic", "warfarin", "nccih-garlic", NCCIH + "garlic",
     "if you take medicines, such as anticoagulants or aspirin, that may also affect bleeding",
     "source says 'anticoagulants'; warfarin chosen"),
    ("Garlic", "aspirin", "nccih-garlic", NCCIH + "garlic",
     "if you take medicines, such as anticoagulants or aspirin, that may also affect bleeding",
     ""),
    ("Melatonin", "warfarin", "nccih-melatonin-what-you-need-to-know",
     NCCIH + "melatonin-what-you-need-to-know",
     "those taking blood thinner medications need to be under medical supervision when "
     "taking melatonin supplements", "source says 'blood thinner medications'; warfarin chosen"),
    ("CoQ10", "warfarin", "nccih-coenzyme-q10", NCCIH + "coenzyme-q10",
     "CoQ10 may interact with the anticoagulant (blood thinner) warfarin", ""),
    ("CoQ10", "insulin", "nccih-coenzyme-q10", NCCIH + "coenzyme-q10",
     "the diabetes drug insulin", ""),
    ("Chamomile", "warfarin", "nccih-chamomile", NCCIH + "chamomile",
     "Interactions between chamomile and some drugs metabolized by the liver and warfarin "
     "(a blood thinner) have been reported", ""),
    # --- other herbs (NCCIH) ---
    ("Goldenseal", "metformin", "nccih-goldenseal", NCCIH + "goldenseal",
     "levels of metformin", ""),
    ("Green tea extract", "nadolol", "nccih-green-tea", NCCIH + "green-tea",
     "reduce blood levels and, therefore, the effectiveness of the drug nadolol", ""),
    ("Green tea extract", "atorvastatin", "nccih-green-tea", NCCIH + "green-tea",
     "Green tea extract can reduce blood levels of the cholesterol-lowering drug atorvastatin.",
     ""),
    ("Green tea extract", "raloxifene", "nccih-green-tea", NCCIH + "green-tea",
     "an interaction between green tea and the drug raloxifene", ""),
    ("Ashwagandha", "levothyroxine", "nccih-ashwagandha", NCCIH + "ashwagandha",
     "and thyroid hormone medications", "source says 'thyroid hormone medications'"),
    ("Ashwagandha", "metformin", "nccih-ashwagandha", NCCIH + "ashwagandha",
     "including those for diabetes and high blood pressure",
     "source says 'medications for diabetes'"),
    ("Ashwagandha", "tacrolimus", "nccih-ashwagandha", NCCIH + "ashwagandha",
     "medicines that decrease the immune system response (immunosuppressants)",
     "source says 'immunosuppressants'"),
    ("Licorice root", "prednisone", "nccih-licorice-root", NCCIH + "licorice-root",
     "Interactions between licorice and corticosteroids have been reported.",
     "source says 'corticosteroids'"),
    ("Kava", "alprazolam", "nccih-kava", NCCIH + "kava",
     "Kava should not be used together with other substances that have sedative effects, "
     "such as benzodiazepines or alcohol.", "source says 'benzodiazepines'"),
    ("Aloe vera", "digoxin", "nccih-aloe-vera", NCCIH + "aloe-vera",
     "cardiac glycosides, such as digoxin", ""),
    ("Soy", "phenelzine", "nccih-soy", NCCIH + "soy",
     "monoamine oxidase inhibitors (a group of antidepressant drugs)",
     "source says 'MAO inhibitors'"),
    # --- grapefruit (FDA) ---
    ("Grapefruit juice", "simvastatin", "fda-grapefruit", FDA_GRAPEFRUIT,
     "Zocor (simvastatin)", ""),
    ("Grapefruit juice", "atorvastatin", "fda-grapefruit", FDA_GRAPEFRUIT,
     "Lipitor (atorvastatin)", ""),
    ("Grapefruit juice", "nifedipine", "fda-grapefruit", FDA_GRAPEFRUIT,
     "Procardia and Adalat CC (both nifedipine)", ""),
    ("Grapefruit juice", "cyclosporine", "fda-grapefruit", FDA_GRAPEFRUIT,
     "Neoral and Sandimmune capsule or oral solution (both cyclosporine)", ""),
    ("Grapefruit juice", "buspirone", "fda-grapefruit", FDA_GRAPEFRUIT,
     "BuSpar (buspirone)", ""),
    ("Grapefruit juice", "budesonide", "fda-grapefruit", FDA_GRAPEFRUIT,
     "Entocort EC and Uceris tablet (both budesonide)", ""),
    ("Grapefruit juice", "amiodarone", "fda-grapefruit", FDA_GRAPEFRUIT,
     "Pacerone and Cordarone tablet (both amiodarone)", ""),
    ("Grapefruit juice", "fexofenadine", "fda-grapefruit", FDA_GRAPEFRUIT,
     "Grapefruit juice can cause less fexofenadine to enter the blood", ""),
]


def main() -> int:
    missing = []
    rows = []
    for a, b, cache, url, quote, note in ROWS:
        text = (CACHE / f"{cache}.txt").read_text(encoding="utf-8")
        if quote not in text:
            missing.append(f"{a} + {b}: {quote[:60]!r}")
            continue
        rows.append(
            {"a": a, "b": b, "significant": True, "source_url": url, "quote": quote,
             "member_note": note}
        )
    if missing:
        print("Quote not found in source; nothing written:")
        for m in missing:
            print("  ", m)
        return 1
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"Wrote {len(rows)} verified rows to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
