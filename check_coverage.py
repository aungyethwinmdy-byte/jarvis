"""Is the cross-outlet coverage answer finding the right stories?

    py check_coverage.py

WHY THIS EXISTS SEPARATELY FROM check_newsroom.py
    check_newsroom.py §3c tests the pieces with hand-written sentences. Those
    pass, and they always will — they assert that the code does what it was
    written to do. They cannot see whether the DESIGN finds the right stories,
    because that depends on how three real outlets actually word their
    headlines and their comparison notes. Measured 2026-09-27: every §3c test
    passed while the answer

      MISSED    the Bangkok flood, which BBC Burmese and The Irrawaddy both
                carried on 26-27 September, reporting it as uncovered —
                27 of the 30 newest briefed stories came back empty
      ACCEPTED  a Chinese car company's EV battery story as BBC coverage of a
                Bangkok train fire, on the shared words "ကုမ္ပဏီ" and "ထုတ်ပြ" —
                46 cross-outlet pairs cleared the bar that week

    So this asks the two questions the fixtures cannot:

      MISSED   a story two outlets really did both carry, that the answer
               reports as uncovered. A false "nobody else has this" is the
               failure the user would never notice.
      WRONG    a story the answer reports as covered by an outlet that did not
               carry it. The reply then presents one outlet's headline as
               another's coverage of the same event.

    Neither can be decided by the code alone — "same story" is a judgement. So
    this prints the candidates with the analyser's own sentence and a verdict
    column, rather than asserting a pass. Read the output.

WHY IT NEEDS THE LIVE DATABASE
    A fixture is a guess about what Burmese headlines look like. The whole bug
    was that the guess was wrong.
"""
import sys
from collections import Counter

sys.path.insert(0, r"E:\Mark-LIV-main")

from core import newsroom_client as nr


def _head(t: str) -> None:
    print("\n" + "=" * 74)
    print(t)
    print("=" * 74)


def main() -> int:
    ok, reason = nr.available()
    print(f"database: {reason}")
    if not ok:
        print("cannot reach the newsroom database — nothing to check")
        return 2

    print("\noutlets:")
    for s in nr.source_breakdown():
        print(f"  {s['source_name']:16} {s['analyzed']:>4} analysed of {s['total']:>4}")

    reports = nr.recent_reports(hours=72, limit=40)
    items = nr.briefing_items(reports, max_items=40)

    tally: Counter = Counter()
    covered: list = []
    unclear: list = []
    none_found: list = []

    for it in items:
        art = nr.article_by_id(it.get("article_id")) if it.get("article_id") else None
        if not art:
            tally["(no article row)"] += 1
            continue
        verdicts, comparison = nr.report_coverage_verdicts(art)
        if not comparison.strip():
            tally["(no comparison section)"] += 1
        hits = []
        for name, (v, ev) in verdicts.items():
            tally[v] += 1
            if v == nr.COVERED:
                hits.append((name, ev))
            elif v == nr.UNCLEAR:
                unclear.append((art, name, ev))
        if hits:
            covered.append((art, hits))
        else:
            none_found.append(art)

    _head("VERDICT TALLY  (per outlet per story)")
    for k, v in tally.most_common():
        print(f"  {k:26} {v}")

    _head("1. COVERED — the answer will name these outlets. Mark each 'yes' or 'no'")
    if not covered:
        print("  none")
    for art, hits in covered:
        print(f"\n  [{art.get('source')}] {str(art.get('title'))[:58]}")
        for name, ev in hits:
            print(f"    -> {name}")
            print(f"       {str(ev)[:150]}")
            print("       same story?  ____")

    _head("2. MISSED? — reported as no other coverage. Mark each 'agreed' or 'MISSED'")
    if not none_found:
        print("  none")
    for art in none_found:
        print(f"\n  [{art.get('source')}] {str(art.get('title'))[:58]}")
        print("       verdict?     ____")

    if unclear:
        _head("3. UNCLEAR — named without a readable verdict, shown to the user as such")
        for art, name, ev in unclear:
            print(f"\n  [{art.get('source')}] -> {name}")
            print(f"       {str(ev)[:170]}")

    _head("VERDICT")
    print("  A passing check_newsroom.py does NOT mean this works — see the module")
    print("  docstring. Judge lists 1 and 2 above.")
    print("\n  Stories with no cross-source section at all fall back to the old")
    print("  headline matcher, which is unreliable; the tally above shows how many.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
