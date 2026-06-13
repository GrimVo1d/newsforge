from django.db import migrations

# The function pins its search_path, so it works for any session setting (and cannot pick up
# a same-named function from another schema). Very long text is cut before indexing: one
# tsvector is limited to 1 MB.
TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION articles_tsv_update() RETURNS trigger
SET search_path = public, pg_catalog
AS $$
DECLARE cfg regconfig := coalesce(NEW.language, 'simple')::regconfig;
BEGIN
  NEW.tsv :=
    setweight(to_tsvector(cfg, unaccent(left(coalesce(NEW.title,   ''),   1000))), 'A') ||
    setweight(to_tsvector(cfg, unaccent(left(coalesce(NEW.summary, ''), 100000))), 'B') ||
    setweight(to_tsvector(cfg, unaccent(left(coalesce(NEW.body,    ''), 300000))), 'C');
  RETURN NEW;
END $$ LANGUAGE plpgsql;
"""

PREVIOUS_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION articles_tsv_update() RETURNS trigger AS $$
DECLARE cfg regconfig := coalesce(NEW.language, 'simple')::regconfig;
BEGIN
  NEW.tsv :=
    setweight(to_tsvector(cfg, unaccent(coalesce(NEW.title,   ''))), 'A') ||
    setweight(to_tsvector(cfg, unaccent(coalesce(NEW.summary, ''))), 'B') ||
    setweight(to_tsvector(cfg, unaccent(coalesce(NEW.body,    ''))), 'C');
  RETURN NEW;
END $$ LANGUAGE plpgsql;
"""

# content_hash now covers the whole text, not its first 512 characters
# (apps.articles.normalizer.content_hash). Only the hash column changes, so the trigger
# does not fire.
REHASH_SQL = r"""
UPDATE articles_article
SET content_hash = encode(sha256(convert_to(
  canonical_url || E'\n' || btrim(title, E' \t\n\r\x0b\x0c')
  || E'\n' || btrim(coalesce(nullif(body, ''), summary), E' \t\n\r\x0b\x0c'),
  'UTF8')), 'hex');
"""


class Migration(migrations.Migration):
    dependencies = [("articles", "0005_processed_at_and_listing_indexes")]

    operations = [
        migrations.RunSQL(sql=TRIGGER_SQL, reverse_sql=PREVIOUS_TRIGGER_SQL),
        migrations.RunSQL(sql=REHASH_SQL, reverse_sql=migrations.RunSQL.noop),
    ]
