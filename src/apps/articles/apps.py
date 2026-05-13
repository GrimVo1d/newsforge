from django.apps import AppConfig


class ArticlesConfig(AppConfig):
    name = "apps.articles"
    label = "articles"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from apps.articles import receivers  # noqa: F401
