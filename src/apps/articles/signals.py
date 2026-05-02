from django.dispatch import Signal

article_created = Signal()  # kwargs: article_id: int, feed_id: int
