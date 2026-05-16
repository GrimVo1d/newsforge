SELECT
  a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
  similarity(a.title, %(query)s)::float AS rank,
  '' AS highlight
FROM articles_article a
WHERE NOT a.is_deleted
  AND a.title %% %(query)s
ORDER BY rank DESC
LIMIT %(limit)s OFFSET %(offset)s;
