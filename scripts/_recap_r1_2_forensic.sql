-- NINJA PULSE RECAP Phase R1.2 - production forensic SQL (READ ONLY).
--
-- Every statement below is a SELECT (optionally preceded by a read-only CTE). No INSERT, UPDATE,
-- DELETE, MERGE, CREATE, ALTER, DROP, TRUNCATE, COPY, or SELECT INTO appears anywhere in this
-- file. Intended invocation (read-only, against the live production database):
--
--   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f - < scripts/_recap_r1_2_forensic.sql
--
-- Table names/columns below are taken directly from database/models/story.py,
-- database/models/story_link.py, database/models/news_event.py (Phase R1/R1.1 forensic reads) -
-- nothing here is guessed.
--
-- Mandatory confirmed-membership filter (Phase R1 forensic finding): NewsEventStoryLink also
-- carries observability-only rows for rejected matches ("related_story", "uncertain_match") that
-- are NOT real Story membership - every query below that joins news_event_story_links restricts
-- match_type to exactly {new_story, story_update, supporting_source, semantic_duplicate}.

\echo '=== A. total Story count ==='
SELECT COUNT(*) AS total_stories FROM stories;

\echo '=== B. Story.event_count distribution ==='
SELECT event_count, COUNT(*) AS n
FROM stories
GROUP BY event_count
ORDER BY event_count;

\echo '=== C. Story counts at each event_count floor ==='
SELECT
  COUNT(*) FILTER (WHERE event_count >= 2) AS ge_2,
  COUNT(*) FILTER (WHERE event_count >= 3) AS ge_3,
  COUNT(*) FILTER (WHERE event_count >= 4) AS ge_4,
  COUNT(*) FILTER (WHERE event_count >= 5) AS ge_5,
  COUNT(*) FILTER (WHERE event_count >= 8) AS ge_8
FROM stories;

\echo '=== D. recent Stories with the highest event_count (top 30) ==='
SELECT id, title, event_count, updated_at
FROM stories
ORDER BY event_count DESC, updated_at DESC
LIMIT 30;

\echo '=== E. Stories with 2+ distinct source domains (approximate; confirmed membership only) ==='
-- Approximate, read-only domain extraction for forensic purposes only - the authoritative
-- computation is services/recap_event.py::_normalize_domain(), used by the Python calibration
-- script. This SQL approximation strips scheme, path, and a leading "www." the same way, but is
-- not guaranteed byte-identical for exotic URLs (e.g. non-standard ports, IDNs).
WITH confirmed_links AS (
    SELECT l.story_id, e.url
    FROM news_event_story_links l
    JOIN news_events e ON e.id = l.news_event_id
    WHERE l.match_type IN ('new_story', 'story_update', 'supporting_source', 'semantic_duplicate')
      AND e.url IS NOT NULL
),
domains AS (
    SELECT
        story_id,
        lower(regexp_replace(regexp_replace(regexp_replace(url, '^https?://', ''), '/.*$', ''), '^www\.', '')) AS domain
    FROM confirmed_links
)
SELECT story_id, COUNT(DISTINCT domain) AS distinct_domains
FROM domains
GROUP BY story_id
HAVING COUNT(DISTINCT domain) >= 2
ORDER BY distinct_domains DESC
LIMIT 30;

\echo '=== F. NewsEventStoryLink match_type distribution (all types, including rejected/observability-only) ==='
SELECT match_type, COUNT(*) AS n
FROM news_event_story_links
GROUP BY match_type
ORDER BY n DESC;
