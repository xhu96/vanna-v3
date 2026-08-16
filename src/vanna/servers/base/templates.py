"""Static, same-origin HTML templates for Vanna servers."""

from __future__ import annotations

import html
import re
from typing import Dict, Optional
from urllib.parse import unquote, urlsplit

BUNDLED_UI_CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'none'",
        "base-uri 'none'",
        "connect-src 'self'",
        "font-src 'self'",
        "form-action 'none'",
        "frame-ancestors 'none'",
        "frame-src 'self' about:",
        "img-src 'self' data:",
        "manifest-src 'none'",
        "media-src 'none'",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'unsafe-inline'",
        "worker-src 'none'",
    ]
)

BUNDLED_UI_SECURITY_HEADERS: Dict[str, str] = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": BUNDLED_UI_CONTENT_SECURITY_POLICY,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "microphone=(), payment=(), usb=()"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}

_UNSAFE_PATH_CHARACTERS = re.compile(r"[\\<>\"'`\x00-\x20\x7f]")


def bundled_ui_security_headers() -> Dict[str, str]:
    """Return a fresh response-header mapping for the bundled UI."""

    return dict(BUNDLED_UI_SECURITY_HEADERS)


def _same_origin_path(
    value: str,
    label: str,
    *,
    allow_empty: bool = False,
    allow_query: bool = False,
) -> str:
    """Validate one absolute-path reference without browser-normalization tricks."""

    if not isinstance(value, str) or len(value) > 2048 or value != value.strip():
        raise ValueError(f"{label} must be a bounded same-origin absolute path")
    if not value:
        if allow_empty:
            return value
        raise ValueError(f"{label} must be a bounded same-origin absolute path")

    decoded = unquote(value)
    parsed = urlsplit(value)
    decoded_parsed = urlsplit(decoded)
    if (
        _UNSAFE_PATH_CHARACTERS.search(decoded)
        or parsed.scheme
        or parsed.netloc
        or parsed.fragment
        or (parsed.query and not allow_query)
        or decoded_parsed.scheme
        or decoded_parsed.netloc
        or (decoded_parsed.query and not allow_query)
        or not parsed.path.startswith("/")
        or parsed.path.startswith("//")
        or not decoded_parsed.path.startswith("/")
        or decoded_parsed.path.startswith("//")
    ):
        raise ValueError(f"{label} must be a bounded same-origin absolute path")

    if any(segment in {".", ".."} for segment in decoded_parsed.path.split("/")):
        raise ValueError(f"{label} cannot contain dot path segments")
    return value


def _component_path(
    *,
    static_path: str,
    component_script_path: Optional[str],
    cdn_url: Optional[str],
) -> str:
    """Resolve the self-hosted component path, accepting a safe legacy alias."""

    candidate = component_script_path
    if candidate is None and cdn_url is not None:
        candidate = cdn_url
    if candidate is None:
        static_root = _same_origin_path(static_path, "static_path").rstrip("/")
        candidate = f"{static_root}/vanna-components.js"
    return _same_origin_path(candidate, "component_script_path", allow_query=True)


def get_vanna_component_script(
    dev_mode: bool = False,
    static_path: str = "/static",
    cdn_url: Optional[str] = None,
    component_script_path: Optional[str] = None,
) -> str:
    """Return the sole executable tag, restricted to a same-origin module."""

    del dev_mode
    source = _component_path(
        static_path=static_path,
        component_script_path=component_script_path,
        cdn_url=cdn_url,
    )
    return (
        '<script type="module" referrerpolicy="no-referrer" '
        f'src="{html.escape(source, quote=True)}"></script>'
    )


def get_index_html(
    dev_mode: bool = False,
    static_path: str = "/static",
    cdn_url: Optional[str] = None,
    api_base_url: str = "",
    api_v2_prefix: str = "/api/vanna/v2",
    component_script_path: Optional[str] = None,
) -> str:
    """Generate the inert V2-default bundled UI shell.

    ``cdn_url`` remains as a migration alias, but only same-origin absolute paths
    are accepted. Core V3 never loads a remote component or emits executable
    artifact helpers.
    """

    base = _same_origin_path(api_base_url, "api_base_url", allow_empty=True)
    prefix = _same_origin_path(api_v2_prefix, "api_v2_prefix")
    endpoint_root = f"{base}{prefix}"
    component_script = get_vanna_component_script(
        dev_mode=dev_mode,
        static_path=static_path,
        cdn_url=cdn_url,
        component_script_path=component_script_path,
    )

    escaped_base = html.escape(base, quote=True)
    escaped_sse = html.escape(f"{endpoint_root}/chat_sse", quote=True)
    escaped_ws = html.escape(f"{endpoint_root}/chat_websocket", quote=True)
    escaped_poll = html.escape(f"{endpoint_root}/chat_poll", quote=True)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>Vanna Agents</title>
  <style>
    :root {{
      --ink: #062f3e;
      --paper: #f4efe2;
      --panel: #fffdf7;
      --line: #9eb9b4;
      --signal: #d84a1b;
      --teal: #087f78;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% 8%, rgba(8, 127, 120, .17), transparent 28rem),
        linear-gradient(rgba(6, 47, 62, .055) 1px, transparent 1px),
        linear-gradient(90deg, rgba(6, 47, 62, .055) 1px, transparent 1px),
        var(--paper);
      background-size: auto, 32px 32px, 32px 32px, auto;
      font-family: "Avenir Next", "Trebuchet MS", sans-serif;
    }}
    main {{ width: min(1180px, calc(100% - 2rem)); margin: 0 auto; padding: 2rem 0; }}
    header {{
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 1rem;
      align-items: end;
      margin-bottom: 1rem;
      border-bottom: 3px solid var(--ink);
      padding-bottom: .8rem;
    }}
    h1 {{ margin: 0; font: 700 clamp(2rem, 5vw, 4.8rem)/.9 Georgia, serif; letter-spacing: -.045em; }}
    .eyebrow {{ margin: 0 0 .35rem; color: var(--signal); font: 700 .76rem/1.2 ui-monospace, monospace; letter-spacing: .16em; text-transform: uppercase; }}
    .protocol {{ border: 1px solid var(--ink); padding: .45rem .65rem; background: var(--panel); font: 700 .75rem/1 ui-monospace, monospace; }}
    .shell {{ min-height: 640px; overflow: hidden; border: 1px solid var(--ink); border-radius: 18px; background: var(--panel); box-shadow: 9px 9px 0 rgba(6, 47, 62, .16); }}
    vanna-chat {{ display: block; width: 100%; height: 640px; }}
    .note {{ margin: 1.2rem 0 0; color: #395d67; font-size: .85rem; }}
    code {{ color: var(--teal); font: 700 .82rem/1.4 ui-monospace, monospace; }}
    @media (max-width: 640px) {{
      main {{ width: min(100% - 1rem, 1180px); padding-top: 1rem; }}
      header {{ grid-template-columns: 1fr; align-items: start; }}
      .protocol {{ justify-self: start; }}
      .shell, vanna-chat {{ min-height: 72vh; height: 72vh; }}
    }}
  </style>
  {component_script}
</head>
<body>
  <main>
    <header>
      <div>
        <p class="eyebrow">Data-first agent interface</p>
        <h1>Vanna</h1>
      </div>
      <div class="protocol">V2 transport default</div>
    </header>
    <section class="shell" aria-label="Vanna chat">
      <vanna-chat
        api-version="v2"
        protocol="v2"
        api-base="{escaped_base}"
        sse-endpoint="{escaped_sse}"
        ws-endpoint="{escaped_ws}"
        poll-endpoint="{escaped_poll}">
      </vanna-chat>
      <noscript>This interface requires the self-hosted Vanna web component.</noscript>
    </section>
    <p class="note">Authentication is enforced by server middleware. Client integrations may use the namespaced API directly without this route.</p>
  </main>
</body>
</html>"""


# Backward compatibility for applications importing the static default template.
INDEX_HTML = get_index_html()
