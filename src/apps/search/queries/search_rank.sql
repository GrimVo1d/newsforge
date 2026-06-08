WITH q AS (
  SELECT websearch_to_tsquery(%(cfg)s::regconfig, unaccent(%(query)s)) AS tsq
),
hits AS (
  SELECT
    a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
    ts_rank_cd(a.tsv, q.tsq, 32) AS rank
  FROM articles_article a
  JOIN feeds_feed f ON f.id = a.feed_id AND NOT f.is_deleted
  CROSS JOIN q
  WHERE NOT a.is_deleted
    AND a.tsv @@ q.tsq
    AND (%(from)s::timestamptz IS NULL OR a.published_at >= %(from)s)
    AND (%(to)s::timestamptz   IS NULL OR a.published_at <  %(to)s)
    AND (cardinality(%(feeds)s::bigint[]) = 0 OR a.feed_id = ANY(%(feeds)s))
  ORDER BY rank DESC, a.published_at DESC NULLS LAST, a.id DESC
  LIMIT %(limit)s OFFSET %(offset)s
)
-- ts_headline is expensive: run it only for the page, over a bounded prefix of the summary.
SELECT
  h.id, h.title, h.summary, h.url, h.feed_id, h.published_at, h.language, h.rank,
  ts_headline(
    %(cfg)s::regconfig,
    -- plain text in, so the result holds no markup except the <b> marks
    left(replace(regexp_replace(coalesce(h.summary, ''), '<[^>]*>', ' ', 'g'), '<', '&lt;'), 2000),
    q.tsq,
    'MaxFragments=2, MinWords=5, MaxWords=20, StartSel=<b>, StopSel=</b>'
  ) AS highlight
FROM hits h, q
ORDER BY h.rank DESC, h.published_at DESC NULLS LAST, h.id DESC;
