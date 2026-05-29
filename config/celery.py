import os
import sys
from pathlib import Path

# --- apps/ on sys.path (ISSUE-011) ------------------------------------------
# This block is duplicated verbatim in config/settings/__init__.py. It cannot
# be extracted to a shared helper because config/__init__.py imports celery
# (this module), so any `from config._x import …` here would re-enter
# config/__init__.py → circular import. Keep both copies identical; if you
# change this block, change the sibling at config/settings/__init__.py too.
_apps_dir = str(Path(__file__).resolve().parent.parent / "apps")
if _apps_dir not in sys.path:
    sys.path.insert(0, _apps_dir)
# ----------------------------------------------------------------------------

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery(os.getenv("CELERY_APP_NAME", "app"))
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
