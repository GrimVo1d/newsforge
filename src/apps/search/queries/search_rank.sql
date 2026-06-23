WITH q AS (
  SELECT CASE
    WHEN %(cfg)s::regconfig IS NOT NULL
      THEN websearch_to_tsquery(%(cfg)s::regconfig, unaccent(%(query)s))
    -- No lang given: OR the query as parsed by every supported config (queries.SUPPORTED_LANGS),
    -- so each article matches the parse that fits how it was indexed. One constant tsquery
    -- keeps the GIN index usable.
    ELSE websearch_to_tsquery('english', unaccent(%(query)s))
      || websearch_to_tsquery('russian', unaccent(%(query)s))
      || websearch_to_tsquery('simple', unaccent(%(query)s))
  END AS tsq
),
hits AS (
  SELECT
    a.id, a.title, a.summary, a.url, a.feed_id, a.published_at, a.language,
    -- 1|32: divide by 1 + log(length), then scale into [0, 1)
    ts_rank_cd(a.tsv, q.tsq, 33) AS rank
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
    coalesce(%(cfg)s::regconfig, h.language::regconfig),
    -- Stripped of tags, then unaccented like the index (or "café" would not be marked for
    -- "cafe"). unaccent turns "«" into "<<" and "‹", "＜" into "<": those become "‹" / "›"
    -- again ("«" / "»" when doubled), so no text is mistaken for a tag, and the mark
    -- characters are dropped. The result is HTML-escaped in Python (render_highlight) anyway.
    replace(replace(
      translate(
        unaccent(regexp_replace(left(coalesce(h.summary, ''), 2000), '<[^>]*>', ' ', 'g')),
        '<>' || %(marks)s, '‹›'
      ),
      '‹‹', '«'), '››', '»'),
    q.tsq,
    %(headline_options)s
  ) AS highlight
FROM hits h, q
ORDER BY h.rank DESC, h.published_at DESC NULLS LAST, h.id DESC;
