"""
HTML templates for Vanna Agents servers.
Ultra-premium dark-mode glassmorphism UI.
"""

from typing import Optional


def get_vanna_component_script(
    dev_mode: bool = False,
    static_path: str = "/static",
    cdn_url: str = "https://img.vanna.ai/vanna-components.js",
    cdn_integrity: str = "",
) -> str:
    """Get the script tag for loading Vanna web components.

    Args:
        dev_mode: Serve the component from a local static path instead of CDN.
        static_path: Base path for local static assets (used when dev_mode=True).
        cdn_url: CDN URL for the web component bundle.
        cdn_integrity: Subresource Integrity (SRI) hash for the CDN bundle, e.g.
            ``"sha384-abc123…"``.  When non-empty, the browser verifies the
            downloaded script matches this hash before executing it.  Strongly
            recommended in production.  Generate with:
            ``openssl dgst -sha384 -binary vanna-components.js | openssl base64 -A``
    """
    if dev_mode:
        return (
            f'<script type="module" src="{static_path}/vanna-components.js"></script>'
        )
    else:
        if cdn_integrity:
            return (
                f'<script type="module" src="{cdn_url}"'
                f' integrity="{cdn_integrity}" crossorigin="anonymous"></script>'
            )
        return f'<script type="module" src="{cdn_url}"></script>'


def get_index_html(
    dev_mode: bool = False,
    static_path: str = "/static",
    cdn_url: str = "https://img.vanna.ai/vanna-components.js",
    api_base_url: str = "",
    api_v2_prefix: str = "/api/vanna/v2",
) -> str:
    """Generate the ultra-premium index HTML."""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vanna Agents</title>
    <meta name="description" content="Data-first AI Agents — Ask your data anything in plain English.">
    <link rel="stylesheet" href="{static_path}/app.css?v=1.0.1">
</head>
<body>

<!-- Animated Background -->
<div class="bg-animated"></div>
<div class="bg-grid"></div>

<!-- Toast Container -->
<div id="toastContainer" class="toast-container"></div>

<!-- ====== LOGIN SCREEN ====== -->
<div id="loginScreen">
    <div class="login-logo">
        <h1>VANNA</h1>
        <div class="glow-line"></div>
        <p class="subtitle">Agents &bull; Data Analytics AI</p>
    </div>

    <div class="role-cards">
        <div class="role-card role-card--admin" data-role="admin">
            <div class="role-icon">
                <svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </div>
            <h3>Admin</h3>
            <p>Full access to settings, tools &amp; analytics</p>
        </div>
        <div class="role-card role-card--developer" data-role="developer">
            <div class="role-icon">
                <svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            </div>
            <h3>Developer</h3>
            <p>API access, SQL tools &amp; LLM config</p>
        </div>
        <div class="role-card role-card--user" data-role="user">
            <div class="role-icon">
                <svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
            <h3>User</h3>
            <p>Ask questions in plain English</p>
        </div>
    </div>

    <p class="login-hint">Select a role to continue &bull; <span>No password required</span></p>
</div>

<!-- ====== DASHBOARD ====== -->
<div id="dashboard">
    <!-- Mobile overlay -->
    <div id="sidebarOverlay" class="sidebar-overlay"></div>

    <!-- Sidebar -->
    <aside class="sidebar">
        <div class="sidebar-header">
            <div class="sidebar-logo-icon">V</div>
            <span class="sidebar-logo">VANNA</span>
        </div>
        <nav class="sidebar-nav">
            <div class="nav-item active" data-view="chat">
                <span class="nav-icon">💬</span>
                <span class="nav-label">Chat</span>
            </div>
            <div class="nav-item" data-view="dashboard">
                <span class="nav-icon">📊</span>
                <span class="nav-label">Dashboard</span>
            </div>
            <div class="nav-item" data-view="history">
                <span class="nav-icon">🕐</span>
                <span class="nav-label">History</span>
            </div>
            <div class="nav-item" data-view="settings">
                <span class="nav-icon">⚙️</span>
                <span class="nav-label">Settings</span>
            </div>
            <div class="nav-item" data-view="api">
                <span class="nav-icon">🔌</span>
                <span class="nav-label">API</span>
            </div>
        </nav>
        <div class="sidebar-footer">
            <button class="sidebar-toggle" id="sidebarToggle">
                <span class="nav-icon">◀</span>
                <span class="nav-label">Collapse</span>
            </button>
        </div>
    </aside>

    <!-- Main Content -->
    <div class="main-content">
        <!-- Top Bar -->
        <header class="topbar">
            <div class="topbar-left">
                <button class="topbar-btn mobile-menu-btn" id="mobileMenuBtn">☰</button>
                <h2 class="topbar-title">Chat</h2>
            </div>
            <div class="topbar-right">
                <div class="status-bar">
                    <span class="status-dot" id="statusDot"></span>
                    <span id="statusText">Ready</span>
                </div>
                <span id="roleBadge" class="role-badge">Admin</span>
                <button class="topbar-btn" id="logoutBtn" title="Logout">⏻</button>
            </div>
        </header>

        <!-- Chat View -->
        <div class="chat-container" style="display:flex">
            <div class="chat-messages" id="chatMessages">
                <div class="welcome-msg">
                    <div class="welcome-icon">✦</div>
                    <h2>Welcome to Vanna Agents</h2>
                    <p>Ask anything about your data in plain English. I'll write the queries, run them, and visualize the results for you.</p>
                    <div class="suggestions">
                        <button class="suggestion-chip">Show me total sales by country</button>
                        <button class="suggestion-chip">Who are the top 5 customers?</button>
                        <button class="suggestion-chip">What genres have the most tracks?</button>
                    </div>
                </div>
            </div>
            <div class="chat-input-bar">
                <div class="input-wrapper">
                    <textarea id="chatInput" class="chat-input" placeholder="Ask a question about your data..." rows="1"></textarea>
                    <button id="sendBtn" class="send-btn" disabled title="Send">
                        <svg width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
                    </button>
                </div>
            </div>
        </div>

        <!-- Settings View -->
        <div class="settings-panel">
            <div class="settings-section">
                <h3>LLM Configuration</h3>
                <div class="settings-field">
                    <label for="llmProvider">Provider</label>
                    <select id="llmProvider" class="settings-input">
                        <option value="openrouter">OpenRouter</option>
                        <option value="openai">OpenAI</option>
                        <option value="anthropic">Anthropic</option>
                    </select>
                </div>
                <div class="settings-field">
                    <label for="llmApiKey">API Key</label>
                    <input type="password" id="llmApiKey" class="settings-input" placeholder="sk-...">
                </div>
                <div class="settings-field">
                    <label for="llmModel">Model (optional)</label>
                    <input type="text" id="llmModel" class="settings-input" placeholder="e.g. gpt-4o">
                </div>
                <button id="saveLlmBtn" class="settings-btn">Save Configurations</button>
            </div>
            <div class="settings-section" id="dbConfigSection">
                <h3>Database Connection</h3>
                <div class="settings-field">
                    <label for="dbType">Type</label>
                    <select id="dbType" class="settings-input">
                        <option value="sqlite">SQLite</option>
                        <option value="postgres">PostgreSQL</option>
                    </select>
                </div>
                <div class="settings-field">
                    <label for="dbUri">Connection URI</label>
                    <input type="text" id="dbUri" class="settings-input" placeholder="Chinook.sqlite">
                </div>
                <button id="saveDbBtn" class="settings-btn">Save DB Config</button>
            </div>
        </div>

        <!-- Coming Soon Views -->
        <!-- Dashboard View -->
        <div class="dashboard-panel" id="dashboardView" style="display: none;">
            <div class="dashboard-header">
                <h2>Analytics</h2>
                <p>Overview of your data exploration platform usage.</p>
                <button id="clearDashboardBtn" class="settings-btn settings-btn--danger" style="margin-left: auto;">Reset Stats</button>
            </div>
            <div class="dashboard-grid" id="dashboardGrid">
                <!-- Populated via JS -->
            </div>
            <div class="dashboard-charts">
                <div class="chart-card">
                    <h3>Recent Activity</h3>
                    <div id="recentActivityList" class="activity-list"></div>
                </div>
            </div>
        </div>

        <!-- History View -->
        <div class="history-panel" id="historyView" style="display: none;">
            <div class="history-header">
                <h2>History</h2>
                <p>Resume previous data exploration sessions.</p>
                <div class="history-actions" style="margin-left: auto;">
                    <button id="clearHistoryBtn" class="settings-btn settings-btn--danger">Clear All History</button>
                </div>
            </div>
            <div class="history-list" id="historyList">
                <!-- Populated via JS -->
            </div>
        </div>
        <div class="coming-soon" id="apiComing">
            <div>
                <div style="font-size:3rem;margin-bottom:1rem">🔌</div>
                <h2>API Endpoints</h2>
                <p style="margin-bottom:1rem">Available API endpoints:</p>
                <div style="text-align:left;font-size:0.85rem;font-family:monospace;background:var(--bg-glass);padding:1rem;border-radius:var(--radius-sm);border:1px solid var(--border-glass)">
                    <div style="margin-bottom:0.5rem"><span style="color:var(--accent-teal);font-weight:600">POST</span> {api_v2_prefix}/chat_sse</div>
                    <div style="margin-bottom:0.5rem"><span style="color:var(--accent-teal);font-weight:600">WS&nbsp;&nbsp;</span> {api_v2_prefix}/chat_websocket</div>
                    <div style="margin-bottom:0.5rem"><span style="color:var(--accent-teal);font-weight:600">POST</span> {api_v2_prefix}/chat_poll</div>
                    <div><span style="color:var(--accent-teal);font-weight:600">GET&nbsp;</span> /health</div>
                </div>
            </div>
        </div>
    </div>
</div>

<script src="{static_path}/app.js?v=1.0.1"></script>
</body>
</html>"""


# Backward compatibility
INDEX_HTML = get_index_html()
