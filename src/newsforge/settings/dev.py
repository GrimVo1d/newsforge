from .base import *  # noqa: F403
from .base import DEV_SECRET_KEY, env

DEBUG = True
ALLOWED_HOSTS = ["*"]
SECRET_KEY = env("SECRET_KEY", default=DEV_SECRET_KEY)
