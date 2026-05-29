import os
import sys
from pathlib import Path

# Inline path setup — cannot use config._path_setup here because
# celery.py is imported during config/__init__.py loading.
_apps_dir = str(Path(__file__).resolve().parent.parent / "apps")
if _apps_dir not in sys.path:
    sys.path.insert(0, _apps_dir)

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery(os.getenv("CELERY_APP_NAME", "app"))
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
