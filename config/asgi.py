"""ASGI config for co-lending-gateway project."""
import os
import sys
from pathlib import Path

# Inline path setup — cannot import config._path_setup because
# it triggers config/__init__.py → circular celery import.
_apps_dir = str(Path(__file__).resolve().parent.parent / "apps")
if _apps_dir not in sys.path:
    sys.path.insert(0, _apps_dir)

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
