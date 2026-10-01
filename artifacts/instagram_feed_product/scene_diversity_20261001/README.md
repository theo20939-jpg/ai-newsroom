# Generated scene diversity - offline proof (0 provider calls, 0 image calls)

Full compiled prompts: `scene_diversity_report.json`. Re-run: `python scripts/_instagram_scene_diversity_proof.py`.

## Old Sonnet set (29 Sep, saved) - what a viewer saw
1. two blank blocks, a small worn one being replaced by a taller one
2. three blocks small -> large on pale paper
3. a collage of stacked blocks, one oversized block rising above
4. two blocks on a dark tabletop, one behind the other
5. one block between a smaller and a larger block

Five pictures of beige blocks. Cause: every slide's prompt carried the Director's carousel-wide
"OVERALL IDEA: the Claude line as a physical hierarchy of blocks" and "Visual genre: unbranded geometric model blocks",
and the five briefs re-described the same object.

## New behaviour
* the carousel-wide object metaphor is no longer written into each slide's prompt; the slide gets its own beat, a story-neutral shared look
  (matte editorial still life, graphite + warm paper, one violet accent, soft window light) and a list of what the other pictures already show;
* a physical concept present in >= 60% (and >= 3) of the briefs is kept once as a connective motif (first carrier); later carriers are
  re-briefed from their OWN grounded copy and told not to reuse the neighbours' object.

## Saved 29 Sep set under the new behaviour
Detected dominant concept: `block` (5/5). Slide 1 keeps its block brief (connective motif); slides 2-5 are re-briefed from their own copy
("Claude is not one model", "a higher tier above Opus", "Opus first, then Sonnet", "Sonnet 5.5 - the middle update") and told not to
repeat blocks. The deterministic re-brief names no object itself - the image model chooses one per beat; that choice is NOT proven here
(it needs a paid generation, which was out of scope).

## Saved current Sonnet set (30 Sep controlled run, current evidence) under the new behaviour
No dominant concept (the Director already wrote six different scenes): stopwatch against token discs / a model tile sliding into a slot /
anonymous hands arranging blank documents / hands adjusting a blank wireframe against aligned presentation frames / a balance with two
model plates and token stacks / a protective shell around a blank code panel with a fallback shell. Briefs untouched; only the prompt
wrapper changes.

## Other genres - SYNTHETIC fixtures (they exercise the rules; they are not model output)
| story | monotone set -> dominant concept | handling | diverse set |
|---|---|---|---|
| gadget launch | `disc`, `metal` | first slide kept, 3 re-briefed | untouched (glass slab / sunlight beam / row of candles / empty shelf) |
| viral / meme | `keyboard` | first slide kept, 3 re-briefed | untouched (toaster bow / glass speech-bubble / wall of enamel hearts / lone toaster on stage) |
| serious incident | `glass`, `wall` | first slide kept, 3 re-briefed | untouched (archive box / propped service door / envelopes beside a locked case / second lock) |
