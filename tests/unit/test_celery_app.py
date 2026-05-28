from newsforge.celery import TASK_MODULES, app

EXPECTED_TASKS = {
    "tasks.articles.process_article",
    "tasks.digest.daily_digest",
    "tasks.fetcher.fetch_feed",
    "tasks.notifications.deliver",
    "tasks.notifications.fanout_instant",
    "tasks.scheduler.cleanup_old_articles",
    "tasks.scheduler.enqueue_due_feeds",
    "tasks.scheduler.refresh_robots_cache",
    "tasks.tags.apply_tag_rules",
}


def test_worker_registers_every_task():
    app.loader.import_default_modules()
    assert EXPECTED_TASKS.issubset(app.tasks)


def test_beat_schedule_points_at_registered_tasks():
    app.loader.import_default_modules()
    scheduled = {entry["task"] for entry in app.conf.beat_schedule.values()}
    assert scheduled.issubset(app.tasks)


def test_every_task_module_is_listed():
    assert {name.rsplit(".", 1)[0] for name in EXPECTED_TASKS} == set(TASK_MODULES)
