-- Fuzzy title match for typos: the whole title is similar to q, or one stretch of it is (word
-- similarity), so a misspelled word inside a long title is still found. Both operators are
-- served by articles_title_trgm_idx.
SELECT
  a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
  greatest(similarity(a.title, %(query)s), word_similarity(%(query)s, a.title))::float AS rank,
  '' AS highlight
FROM articles_article a
JOIN feeds_feed f ON f.id = a.feed_id AND NOT f.is_deleted
WHERE NOT a.is_deleted
  AND (a.title %% %(query)s OR a.title %%> %(query)s)
  AND (%(from)s::timestamptz IS NULL OR a.published_at >= %(from)s)
  AND (%(to)s::timestamptz   IS NULL OR a.published_at <  %(to)s)
  AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
ORDER BY
  -- sort=date: newest first, as for full-text hits
  CASE WHEN %(by_date)s THEN a.published_at END DESC NULLS LAST,
  rank DESC, a.published_at DESC NULLS LAST, a.id DESC
LIMIT %(limit)s OFFSET %(offset)s;
