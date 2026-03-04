"""
HTML templates for Vanna Agents servers.
Ultra-premium dark-mode glassmorphism UI.
"""



def get_vanna_component_script(
    dev_mode: bool = False,
    static_path: str = "/static",
    cdn_url: str = "https://img.vanna.ai/vanna-components.js",
    cdn_integrity: str = "",
) -> str:
    """Get the script tag for loading Vanna web components."""
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
    """Generate the ultra-premium index HTML with all modular panels."""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vanna Agents</title>
    <meta name="description" content="Data-first AI Agents — Ask your data anything in plain English.">
    <link rel="stylesheet" href="{static_path}/app.css?v=2.0.0">
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
            <h3>Engineer</h3>
            <p>SQL tools, skills &amp; schema browser</p>
        </div>
        <div class="role-card role-card--user" data-role="user">
            <div class="role-icon">
                <svg width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
            </div>
            <h3>Analyst</h3>
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

            <!-- Main (all roles) -->
            <div class="nav-item active" data-view="chat" data-roles="user,developer,admin">
                <span class="nav-icon">💬</span>
                <span class="nav-label">Chat</span>
            </div>
            <div class="nav-item" data-view="dashboard" data-roles="user,developer,admin">
                <span class="nav-icon">📊</span>
                <span class="nav-label">Dashboard</span>
            </div>
            <div class="nav-item" data-view="history" data-roles="user,developer,admin">
                <span class="nav-icon">🕐</span>
                <span class="nav-label">History</span>
            </div>

            <!-- Developer Tools -->
            <div class="nav-section-label" data-roles="developer,admin">Developer Tools</div>
            <div class="nav-item" data-view="sql" data-roles="developer,admin">
                <span class="nav-icon">⚡</span>
                <span class="nav-label">SQL Scratchpad</span>
            </div>
            <div class="nav-item" data-view="skills" data-roles="developer,admin">
                <span class="nav-icon">✨</span>
                <span class="nav-label">Skills</span>
            </div>
            <div class="nav-item" data-view="lineage" data-roles="developer,admin">
                <span class="nav-icon">🔗</span>
                <span class="nav-label">Lineage</span>
            </div>
            <div class="nav-item" data-view="schema" data-roles="developer,admin">
                <span class="nav-icon">🗂</span>
                <span class="nav-label">Schema Browser</span>
            </div>

            <!-- Administration -->
            <div class="nav-section-label" data-roles="admin">Administration</div>
            <div class="nav-item" data-view="connections" data-roles="admin">
                <span class="nav-icon">🔌</span>
                <span class="nav-label">Connections</span>
            </div>
            <div class="nav-item" data-view="observability" data-roles="admin">
                <span class="nav-icon">📈</span>
                <span class="nav-label">Observability</span>
            </div>
            <div class="nav-item" data-view="privacy" data-roles="admin">
                <span class="nav-icon">👁</span>
                <span class="nav-label">Privacy</span>
            </div>
            <div class="nav-item" data-view="security" data-roles="admin">
                <span class="nav-icon">🔒</span>
                <span class="nav-label">Security</span>
            </div>
            <div class="nav-item" data-view="audit" data-roles="admin">
                <span class="nav-icon">📋</span>
                <span class="nav-label">Audit Log</span>
            </div>
            <div class="nav-item" data-view="toolrbac" data-roles="admin">
                <span class="nav-icon">🛡</span>
                <span class="nav-label">Tool Access</span>
            </div>
            <div class="nav-item" data-view="settings" data-roles="developer,admin">
                <span class="nav-icon">⚙️</span>
                <span class="nav-label">Settings</span>
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
                <h2 class="topbar-title" id="topbarTitle">Chat</h2>
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

        <!-- ══ CHAT ══ -->
        <div class="panel-view chat-container" id="panelChat" style="display:flex">
            <div class="chat-messages" id="chatMessages">
                <div class="welcome-msg">
                    <div class="welcome-icon">✦</div>
                    <h2>Welcome to Vanna Agents</h2>
                    <p>Ask anything about your data in plain English. I'll write the queries, run them, and visualize the results for you.</p>
                    <div class="suggestions">
                        <button class="suggestion-chip">Show me total sales by country</button>
                        <button class="suggestion-chip">Who are the top 5 customers?</button>
                        <button class="suggestion-chip">What genres have the most tracks?</button>
                        <button class="suggestion-chip">Show monthly revenue trend</button>
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

        <!-- ══ DASHBOARD ══ -->
        <div class="panel-view dashboard-panel" id="panelDashboard">
            <div class="panel-header">
                <div><h2>Analytics</h2><p>Overview of your data exploration platform usage.</p></div>
                <button id="clearDashboardBtn" class="settings-btn settings-btn--danger">Reset Stats</button>
            </div>
            <div class="panel-scroll">
                <div class="dashboard-grid" id="dashboardGrid"></div>
                <div class="dashboard-charts">
                    <div class="chart-card">
                        <h3>Recent Activity</h3>
                        <div id="recentActivityList" class="activity-list"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ══ HISTORY ══ -->
        <div class="panel-view history-panel" id="panelHistory">
            <div class="panel-header">
                <div><h2>History</h2><p>Resume previous data exploration sessions.</p></div>
                <button id="clearHistoryBtn" class="settings-btn settings-btn--danger">Clear All</button>
            </div>
            <div class="panel-scroll">
                <div class="history-list" id="historyList"></div>
            </div>
        </div>

        <!-- ══ SQL SCRATCHPAD ══ -->
        <div class="panel-view" id="panelSql">
            <div class="panel-header"><h2>⚡ SQL Scratchpad</h2></div>
            <div class="panel-scroll">
                <div class="scratchpad-card">
                    <div class="scratchpad-toolbar">
                        <span class="scratchpad-hint">Write raw SQL against your connected database</span>
                        <button class="scratchpad-run-btn" id="sqlRunBtn">
                            <svg width="13" height="13" fill="currentColor" viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                            Run
                        </button>
                    </div>
                    <textarea id="sqlEditor" class="sql-editor" placeholder="SELECT * FROM Customer LIMIT 10;" spellcheck="false"></textarea>
                </div>
                <div id="sqlResults" class="sql-results-area"></div>
            </div>
        </div>

        <!-- ══ SKILLS ══ -->
        <div class="panel-view" id="panelSkills">
            <div class="panel-header">
                <h2>✨ Skill Fabric</h2>
                <button class="settings-btn" id="openGenerateSkillBtn">+ Generate Skill</button>
            </div>
            <div class="panel-scroll">
                <div id="skillsError" class="panel-error" style="display:none"></div>
                <div id="skillsList">
                    <div class="panel-empty"><div class="panel-empty-icon">✨</div><p>Loading skills…</p></div>
                </div>
            </div>
            <!-- Generate Skill Modal -->
            <div id="generateSkillModal" class="modal-overlay" style="display:none">
                <div class="modal-card">
                    <div class="modal-header">
                        <h3>Generate Skill</h3>
                        <button class="modal-close" id="closeGenerateSkillBtn">✕</button>
                    </div>
                    <textarea id="skillDescription" class="settings-input" rows="4" placeholder="Describe the skill in natural language, e.g. 'Calculate monthly revenue by region using the sales table.'"></textarea>
                    <div class="modal-footer">
                        <button class="settings-btn settings-btn--ghost" id="cancelGenerateSkillBtn">Cancel</button>
                        <button class="settings-btn" id="generateSkillBtn">Generate</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- ══ LINEAGE ══ -->
        <div class="panel-view" id="panelLineage">
            <div class="panel-header"><h2>🔗 Data Lineage</h2></div>
            <div class="panel-scroll">
                <div id="lineageContent">
                    <div class="panel-empty"><div class="panel-empty-icon">🔗</div><p>No lineage data yet. Run some queries first.</p></div>
                </div>
            </div>
        </div>

        <!-- ══ SCHEMA BROWSER ══ -->
        <div class="panel-view" id="panelSchema">
            <div class="panel-header">
                <h2>🗂 Schema Browser</h2>
                <button class="settings-btn" id="schemaSyncBtn">Sync Now</button>
            </div>
            <div class="panel-scroll">
                <div id="schemaStatus" class="schema-status-bar"></div>
                <div id="schemaContent">
                    <div class="panel-empty"><div class="panel-empty-icon">🗂</div><p>Loading schema…</p></div>
                </div>
            </div>
        </div>

        <!-- ══ CONNECTIONS ══ -->
        <div class="panel-view" id="panelConnections">
            <div class="panel-header"><h2>🔌 Connections &amp; Provider</h2></div>
            <div class="panel-scroll">
                <div class="settings-section">
                    <h3>Language Model</h3>
                    <div class="settings-field">
                        <label>API Key</label>
                        <input type="password" class="settings-input" placeholder="sk-..." id="connLlmKey">
                    </div>
                    <div class="settings-field">
                        <label>DataHub Metadata Endpoint</label>
                        <input type="text" class="settings-input" placeholder="https://..." id="connDatahub" value="http://datahub-gms:8080/graphql">
                    </div>
                </div>
                <div class="settings-section">
                    <h3>Data Warehouse</h3>
                    <div class="settings-field">
                        <label>Connection String (DSN)</label>
                        <input type="password" class="settings-input" placeholder="postgresql://..." id="connDsn">
                    </div>
                    <button class="settings-btn" id="testConnBtn">Test Connection</button>
                    <div id="connTestResult" style="margin-top:0.75rem;font-size:0.8rem;color:var(--text-muted)"></div>
                </div>
            </div>
        </div>

        <!-- ══ OBSERVABILITY ══ -->
        <div class="panel-view" id="panelObservability">
            <div class="panel-header"><h2>📈 Observability Engine</h2></div>
            <div class="panel-scroll">
                <div class="settings-section">
                    <p class="settings-desc">Configure data quality constraints before allowing execution workflows.</p>
                    <div class="settings-toggle-row">
                        <div>
                            <span class="settings-toggle-label">Enable strict checking</span>
                            <span class="settings-toggle-hint">Halt processes on data degradation.</span>
                        </div>
                        <label class="toggle-switch">
                            <input type="checkbox" checked id="obsStrictCheck">
                            <span class="toggle-slider"></span>
                        </label>
                    </div>
                    <div class="settings-field" style="margin-top:1.5rem">
                        <label>GX Configuration Token</label>
                        <input type="password" class="settings-input" placeholder="gxc_auth_..." id="obsGxToken">
                    </div>
                </div>
            </div>
        </div>

        <!-- ══ PRIVACY ══ -->
        <div class="panel-view" id="panelPrivacy">
            <div class="panel-header"><h2>👁 Privacy &amp; Redaction</h2></div>
            <div class="panel-scroll">
                <div class="settings-section">
                    <p class="settings-desc">Select entities to identify and strip via Presidio before payload dispatch.</p>
                    <div class="pii-grid">
                        <label class="pii-check"><input type="checkbox" checked> CREDIT_CARD</label>
                        <label class="pii-check"><input type="checkbox" checked> EMAIL_ADDRESS</label>
                        <label class="pii-check"><input type="checkbox" checked> US_SSN</label>
                        <label class="pii-check"><input type="checkbox" checked> PERSON</label>
                        <label class="pii-check"><input type="checkbox"> IP_ADDRESS</label>
                        <label class="pii-check"><input type="checkbox"> CRYPTO_WALLET</label>
                    </div>
                    <button class="settings-btn" style="margin-top:1.5rem">+ Add Regex Matcher</button>
                </div>
            </div>
        </div>

        <!-- ══ SECURITY ══ -->
        <div class="panel-view" id="panelSecurity">
            <div class="panel-header"><h2>🔒 Security Settings</h2></div>
            <div class="panel-scroll">
                <div id="securityError" class="panel-error" style="display:none"></div>
                <div id="securityContent">
                    <div class="panel-empty"><div class="panel-empty-icon">🔒</div><p>Loading security configuration…</p></div>
                </div>
            </div>
        </div>

        <!-- ══ AUDIT LOG ══ -->
        <div class="panel-view" id="panelAudit">
            <div class="panel-header">
                <h2>📋 Audit Log</h2>
                <button class="settings-btn" id="auditRefreshBtn">Refresh</button>
            </div>
            <div class="panel-scroll">
                <div id="auditContent">
                    <div class="panel-empty"><div class="panel-empty-icon">📋</div><p>Loading audit entries…</p></div>
                </div>
            </div>
        </div>

        <!-- ══ TOOL ACCESS (RBAC) ══ -->
        <div class="panel-view" id="panelToolrbac">
            <div class="panel-header"><h2>🛡 Tool Access Control</h2></div>
            <div class="panel-scroll">
                <div id="toolRbacContent">
                    <div class="panel-empty"><div class="panel-empty-icon">🛡</div><p>Loading tool access rules…</p></div>
                </div>
            </div>
        </div>

        <!-- ══ SETTINGS ══ -->
        <div class="panel-view settings-panel" id="panelSettings">
            <div class="panel-header"><h2>⚙️ Settings</h2></div>
            <div class="panel-scroll">
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
                    <button id="saveLlmBtn" class="settings-btn">Save LLM Config</button>
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
        </div>

    </div><!-- /main-content -->
</div><!-- /dashboard -->

<script src="{static_path}/app.js?v=2.0.2"></script>
</body>
</html>"""


# Backward compatibility
INDEX_HTML = get_index_html()
