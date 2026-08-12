# Phase 23.1M — Human-Style Naturalness Review Rubric

Deterministic scoring guide for human review of Copywriting V8.3 output. Score each delivered
post 1–5 on each axis below. No new LLM judge was built — per the phase brief's own explicit
"do not build another LLM judge unless an existing approved Quality mechanism can perform this
without architectural change" instruction, and because the primary evidence for this phase is the
golden comparison (`docs/phase23_1m_russian_editorial_naturalness_report.md` §6-9) plus this
rubric applied by a human reviewer, not an automated score.

## 1. Naturalness
Would a native Russian editor write this? 5 = reads exactly like an original Russian tech-news
sentence. 1 = reads like a raw machine translation.

## 2. Clarity
Can the sentence be understood on first read, without re-reading? 5 = instantly clear. 1 = the
reader has to stop and mentally reconstruct the meaning.

## 3. Precision
Does the wording preserve the source meaning exactly (actor, action, certainty, numbers,
attribution)? 5 = no drift at all. 1 = the claim has measurably changed.

## 4. Concision
Is every sentence/clause necessary? 5 = nothing could be removed without losing information.
1 = padded with filler.

## 5. Telegram readability
Does it read like a Telegram tech-news post, not a press release? 5 = feels native to the
channel. 1 = feels like a corporate PR excerpt.

A post is considered publishable when every axis scores 4 or 5. Any axis scoring 1-2 should be
treated as a concrete defect to name, not just a low number.
