SELECT
  a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
  similarity(a.title, %(query)s)::float AS rank,
  '' AS highlight
FROM articles_article a
JOIN feeds_feed f ON f.id = a.feed_id AND NOT f.is_deleted
WHERE NOT a.is_deleted
  AND a.title %% %(query)s
  AND (%(from)s::timestamptz IS NULL OR a.published_at >= %(from)s)
  AND (%(to)s::timestamptz   IS NULL OR a.published_at <  %(to)s)
  AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
ORDER BY rank DESC, a.id DESC
LIMIT %(limit)s OFFSET %(offset)s;
