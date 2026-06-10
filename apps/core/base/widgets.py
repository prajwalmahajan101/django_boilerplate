"""Reusable admin widgets for the core library (Unfold-compatible)."""

from __future__ import annotations

import json

from django.forms import Textarea
from django.utils.html import escape, escapejs
from django.utils.safestring import mark_safe


class JsonEditorWidget(Textarea):
    """JSON editor widget with syntax highlighting and validation.

    Renders a styled textarea with a live JSON validator status bar
    and a format button. Uses a monospace font and Unfold-compatible
    theme colors. No external dependencies required.

    Usage in admin::

        from core.base.widgets import JsonEditorWidget

        class MyAdmin(BaseModelAdmin):
            formfield_overrides = {
                models.JSONField: {"widget": JsonEditorWidget},
            }
    """

    def __init__(self, attrs=None):
        default_attrs = {
            "rows": 18,
            "spellcheck": "false",
            "autocomplete": "off",
            "autocorrect": "off",
            "autocapitalize": "off",
        }
        if attrs:
            default_attrs.update(attrs)
        super().__init__(attrs=default_attrs)

    def render(self, name, value, attrs=None, renderer=None):
        # Pretty-print JSON for readability
        if value and isinstance(value, dict | list):
            value = json.dumps(value, indent=2, ensure_ascii=False)
        elif value and isinstance(value, str):
            try:
                parsed = json.loads(value)
                value = json.dumps(parsed, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass

        widget_id = attrs.get("id", f"id_{name}") if attrs else f"id_{name}"

        # Build textarea attrs with styling
        final_attrs = self.build_attrs(
            attrs or {},
            {
                "name": name,
                "id": widget_id,
                "class": (
                    "vLargeTextField border border-base-200 bg-white font-medium "
                    "rounded-default shadow-xs text-font-default-light text-sm "
                    "focus:outline-2 focus:-outline-offset-2 focus:outline-primary-600 "
                    "dark:bg-base-900 dark:border-base-700 dark:text-font-default-dark "
                    "dark:scheme-dark px-3 py-2.5 w-full max-w-4xl "
                    "font-mono leading-relaxed resize-y tab-size-2"
                ),
                "style": (
                    "font-family: ui-monospace, SFMono-Regular, 'SF Mono', Menlo, "
                    "Consolas, 'Liberation Mono', monospace; "
                    "tab-size: 2; white-space: pre;"
                ),
            },
        )

        # Build attrs string
        attrs_str = " ".join(f'{k}="{v}"' for k, v in final_attrs.items() if v is not None)
        escaped_value = escape(value or "")
        escaped_id = escape(widget_id)
        escaped_id_js = escapejs(widget_id)

        html = f"""
        <div class="flex flex-col gap-1.5 max-w-4xl" id="{escaped_id}_wrapper">
            <div class="flex items-center justify-end">
                <button type="button" id="{escaped_id}_format"
                    class="font-medium inline-flex items-center gap-1 rounded-default
                           justify-center whitespace-nowrap cursor-pointer px-2 py-1 text-xs
                           border border-base-200 shadow-xs text-important
                           bg-white dark:bg-base-900 dark:border-base-700
                           hover:bg-base-100 dark:hover:bg-base-800">
                    <span class="material-symbols-outlined" style="font-size: 14px;">format_align_left</span>
                    Format
                </button>
            </div>
            <textarea {attrs_str}>{escaped_value}</textarea>
            <div class="flex items-center justify-end">
                <div id="{escaped_id}_status" class="text-xs flex items-center gap-1"></div>
            </div>
        </div>
        <script>
        (function() {{
            const ta = document.getElementById("{escaped_id_js}");
            const statusEl = document.getElementById("{escaped_id_js}_status");
            const formatBtn = document.getElementById("{escaped_id_js}_format");

            function validate() {{
                const val = ta.value.trim();
                if (!val) {{
                    statusEl.innerHTML = '';
                    return;
                }}
                try {{
                    JSON.parse(val);
                    statusEl.innerHTML =
                        '<span class="text-green-600 dark:text-green-400 flex items-center gap-1">' +
                        '<span class="material-symbols-outlined" style="font-size:14px">check_circle</span>' +
                        ' Valid JSON</span>';
                }} catch (e) {{
                    statusEl.innerHTML =
                        '<span class="text-red-600 dark:text-red-400 flex items-center gap-1">' +
                        '<span class="material-symbols-outlined" style="font-size:14px">error</span> ' +
                        e.message.replace(/</g, '&lt;') + '</span>';
                }}
            }}

            formatBtn.addEventListener("click", function() {{
                const val = ta.value.trim();
                if (!val) return;
                try {{
                    const parsed = JSON.parse(val);
                    ta.value = JSON.stringify(parsed, null, 2);
                    validate();
                }} catch (e) {{
                    validate();
                }}
            }});

            ta.addEventListener("keydown", function(e) {{
                if (e.key === "Tab") {{
                    e.preventDefault();
                    const start = this.selectionStart;
                    const end = this.selectionEnd;
                    this.value = this.value.substring(0, start) + "  " + this.value.substring(end);
                    this.selectionStart = this.selectionEnd = start + 2;
                    validate();
                }}
            }});

            ta.addEventListener("input", validate);
            validate();
        }})();
        </script>
        """
        return mark_safe(html)
