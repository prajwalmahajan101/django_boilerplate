import os
import sys
from pathlib import Path

# --- apps/ on sys.path (Decision Record: kept duplicated by design) ---------
# This block is duplicated verbatim in config/settings/__init__.py.
#
# Why duplicated: config/__init__.py imports this celery module, so any
# `from config._something import _apps_dir` here would re-enter
# config/__init__.py and trip a circular import at boot. There is no
# shared-helper path that avoids re-entering config/__init__.py.
#
# Why safe: the drift guard at config/settings/__init__.py:22-29 recomputes
# what *this* file would resolve to (via parents[2]) and refuses to start
# if the two siblings disagree — so the only realistic failure mode of the
# duplication (someone edits one copy without the other) is caught at boot,
# not at runtime. If you change this block, change the sibling and re-run
# `DJANGO_ENV=test python manage.py runserver` to confirm the guard passes.
_apps_dir = str(Path(__file__).resolve().parent.parent / "apps")
if _apps_dir not in sys.path:
    sys.path.insert(0, _apps_dir)
# ----------------------------------------------------------------------------

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery(os.getenv("CELERY_APP_NAME", "app"))
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
