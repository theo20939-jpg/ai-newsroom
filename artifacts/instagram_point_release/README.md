# KAGE Instagram — point-release false positive (2026-09-29)

Offline only: 0 provider calls, 0 image calls, no database, no natural canary. Base `a4e9dd4`.

## What was wrong

In the final natural canary's pool, two routine iOS 27.0.1 point releases were daily-eligible as STRONG `device_launch`:

- "Apple Releases iOS 27.0.1 With Face ID Bug Fix" (MacRumors). Lead: "the first update for iOS 27 … can be downloaded over the air".
- "Apple Notes keeps getting better, here's what's new in iOS 27" (9to5Mac). Its event hook was the other copy: "Apple releases iOS 27.0.1
  for iPhone, here's what's new". Lead: "a new iPhone software update with key bug fixes for issues introduced in iOS 27".

The device-launch pattern is a release verb followed by a device word within 80 characters. It read "**releases** iOS 27.0.1 for
**iPhone**" and "**released** **iPad**OS 27.0.1" as device launches, although the released thing was software and all it changed was fixes.

## What changed (`services/instagram_viral_story_gate.py`, selection only)

1. **The released object.** A device launch counts only when the matched span does not name software: an `…OS` platform name
   (case-sensitive), a dotted point version, update / firmware / patch / build.
2. **Routine maintenance.** A story whose own headline names a software release, whose text reports maintenance (fix, bug, patch,
   security, vulnerability, stability, performance, minor, maintenance, and the Russian equivalents), and which contains no release-level
   change and no flagship model gets NO launch family. Its other reasons to care (for example a real failure) are kept.
3. **Meaningful software releases compete.** A new `software_launch` family covers a release with a release-level change: a redesign or
   overhaul, the biggest / a major update, new AI features or capabilities, dozens of new features. The sentence must also name a software
   object (an `…OS` name, an app / software / OS / browser, or a versioned product name).

No vendor, platform, feature or version is named in any rule.

## Files

- `before/*.json`, `after/*.json`: `scripts/_instagram_point_release_replay.py` on the 11 saved pools. BEFORE is the `a4e9dd4` code
  (a `git archive` snapshot); AFTER is this commit.
- `compare.json`: `scripts/_instagram_point_release_compare.py`.
