WITH q AS (
  SELECT websearch_to_tsquery(%(cfg)s::regconfig, unaccent(%(query)s)) AS tsq
)
SELECT
  a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
  ts_rank_cd(a.tsv, q.tsq, 32) AS rank,
  ts_headline(
    %(cfg)s::regconfig,
    coalesce(a.summary, ''),
    q.tsq,
    'MaxFragments=2, MinWords=5, MaxWords=20, StartSel=<b>, StopSel=</b>'
  ) AS highlight
FROM articles_article a, q
WHERE NOT a.is_deleted
  AND a.tsv @@ q.tsq
  AND (%(from)s::timestamptz IS NULL OR a.published_at >= %(from)s)
  AND (%(to)s::timestamptz   IS NULL OR a.published_at <  %(to)s)
  AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
ORDER BY rank DESC, a.published_at DESC NULLS LAST
LIMIT %(limit)s OFFSET %(offset)s;
