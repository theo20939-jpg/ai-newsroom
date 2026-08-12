"""Phase 18.10 Stage 8: controlled replay of direct-quote, indirect-speech, and conflicting-quote
scenarios through the real services.quote_verification.verify_quote() and
services.content_quality_gates.evaluate_content_quality_gates() - pure functions, no DB, no LLM,
no Telegram send.
"""
from services.content_quality_gates import evaluate_content_quality_gates
from services.quote_verification import verify_quote

print("=== SCENARIO 1: direct verbatim quote (should verify + render) ===")
source1 = 'The CEO said in an interview, "We are doubling our compute budget next year," confirming the expansion plans.'
quote1 = "We are doubling our compute budget next year"
print(f"  source: {source1}")
print(f"  claimed quote: {quote1!r}")
print(f"  verify_quote() -> {verify_quote(quote1, source1)}\n")

print("=== SCENARIO 2: indirect speech / paraphrase (must NOT verify as a direct quote) ===")
source2 = "The spokesperson said the company was planning to expand its compute budget substantially next year."
quote2 = "We are doubling our compute budget next year"
print(f"  source: {source2}")
print(f"  claimed quote: {quote2!r}")
print(f"  verify_quote() -> {verify_quote(quote2, source2)}  (expected False - paraphrase, not verbatim)\n")

print("=== SCENARIO 3: conflicting/altered quote (numbers changed - must NOT verify) ===")
source3 = 'The spokesperson said, "Revenue grew by fifteen percent this quarter."'
quote3 = "Revenue grew by fifty percent this quarter"
print(f"  source: {source3}")
print(f"  claimed quote: {quote3!r}")
print(f"  verify_quote() -> {verify_quote(quote3, source3)}  (expected False - altered figure)\n")

print("=== SCENARIO 4: end-to-end quality gate check on a draft with an unattributed quote ===")
report = evaluate_content_quality_gates(
    title="Компания объявляет о запуске нового продукта",
    body="Краткое описание запуска.",
    why_it_matters="Это меняет расстановку сил на рынке.",
    quote_text="Мы стали лидерами рынка",
    quote_speaker=None,
    source_title="Company announces new product launch",
)
print(f"  quote with no speaker attribution -> passed={report.passed}, failed_gates={report.failed_gates}\n")

print("=== SCENARIO 5: well-formed draft, all gates pass ===")
report2 = evaluate_content_quality_gates(
    title="Компания объявляет о запуске нового продукта",
    body="Краткое описание того, что произошло и почему это важно для рынка.",
    why_it_matters="Это меняет расстановку сил на рынке среди конкурентов.",
    quote_text="We have become the market leader",
    quote_speaker="CEO компании",
    source_title="Company announces new product launch",
    source_content='In an interview the CEO said, "We have become the market leader," during the call.',
    rendered_html="<blockquote>We have become the market leader</blockquote>",
)
print(f"  fully-attributed, traceable quote -> passed={report2.passed}, failed_gates={report2.failed_gates}")
