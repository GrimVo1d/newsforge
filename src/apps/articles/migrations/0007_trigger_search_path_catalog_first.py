from importlib import import_module

from django.db import migrations

# pg_catalog goes first: with public ahead of it, anyone allowed to create objects in public
# could shadow a built-in (to_tsvector, coalesce, ...) inside the trigger. unaccent lives in
# public and is still found there.
_previous = import_module("apps.articles.migrations.0006_trigger_search_path_and_full_hash")
PREVIOUS_TRIGGER_SQL = _previous.TRIGGER_SQL
TRIGGER_SQL = PREVIOUS_TRIGGER_SQL.replace(
    "SET search_path = public, pg_catalog", "SET search_path = pg_catalog, public"
)
assert TRIGGER_SQL != PREVIOUS_TRIGGER_SQL


class Migration(migrations.Migration):
    dependencies = [("articles", "0006_trigger_search_path_and_full_hash")]

    operations = [migrations.RunSQL(sql=TRIGGER_SQL, reverse_sql=PREVIOUS_TRIGGER_SQL)]
