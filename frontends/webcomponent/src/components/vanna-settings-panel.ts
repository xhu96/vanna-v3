import { LitElement, html, css } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { vannaDesignTokens } from '../styles/vanna-design-tokens.js';

@customElement('vanna-settings-panel')
export class VannaSettingsPanel extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        font-family: var(--vanna-font-family-default);
        position: fixed;
        inset: 0;
        z-index: 1000;
        pointer-events: none;
      }

      .modal-backdrop {
        position: absolute;
        inset: 0;
        background: rgba(15, 23, 42, 0.4);
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
        opacity: 0;
        transition: opacity var(--vanna-duration-300) ease;
        pointer-events: none;
      }

      .modal-backdrop.open {
        opacity: 1;
        pointer-events: auto;
      }

      .modal-container {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -45%) scale(0.95);
        width: 100%;
        max-width: 600px;
        background: var(--vanna-background-root);
        border: 1px solid var(--vanna-outline-dimmer);
        border-radius: var(--vanna-border-radius-2xl);
        box-shadow: 0 25px 50px -12px rgba(15, 23, 42, 0.25);
        opacity: 0;
        pointer-events: none;
        transition: all var(--vanna-duration-400) cubic-bezier(0.16, 1, 0.3, 1);
        display: flex;
        flex-direction: column;
        max-height: 85vh;
      }

      .modal-container.open {
        transform: translate(-50%, -50%) scale(1);
        opacity: 1;
        pointer-events: auto;
      }

      .modal-header {
        padding: var(--vanna-space-5);
        border-bottom: 1px solid var(--vanna-outline-dimmer);
        display: flex;
        align-items: center;
        justify-content: space-between;
      }

      .modal-title {
        font-size: 1.25rem;
        font-weight: 600;
        color: var(--vanna-foreground-stronger);
        margin: 0;
        letter-spacing: -0.01em;
      }

      .close-button {
        background: transparent;
        border: none;
        color: var(--vanna-foreground-dimmer);
        cursor: pointer;
        padding: var(--vanna-space-2);
        border-radius: var(--vanna-border-radius-full);
        display: flex;
        align-items: center;
        justify-content: center;
        transition: all var(--vanna-duration-200) ease;
      }

      .close-button:hover {
        background: var(--vanna-background-higher);
        color: var(--vanna-foreground-default);
      }

      .modal-tabs {
        display: flex;
        padding: 0 var(--vanna-space-5);
        border-bottom: 1px solid var(--vanna-outline-dimmer);
        background: var(--vanna-background-higher);
      }

      .tab {
        padding: var(--vanna-space-4) var(--vanna-space-5);
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        color: var(--vanna-foreground-dimmer);
        font-weight: 500;
        font-size: 0.9rem;
        cursor: pointer;
        transition: all var(--vanna-duration-200) ease;
      }

      .tab:hover {
        color: var(--vanna-foreground-default);
      }

      .tab.active {
        color: var(--vanna-iris);
        border-bottom-color: var(--vanna-iris);
      }

      .modal-body {
        padding: var(--vanna-space-6) var(--vanna-space-5);
        overflow-y: auto;
        flex: 1;
      }

      .form-group {
        margin-bottom: var(--vanna-space-5);
      }

      .form-label {
        display: block;
        font-size: 0.875rem;
        font-weight: 500;
        color: var(--vanna-foreground-default);
        margin-bottom: var(--vanna-space-2);
      }

      .form-input, .form-select {
        width: 100%;
        padding: 10px 14px;
        background: var(--vanna-background-higher);
        border: 1px solid var(--vanna-outline-default);
        border-radius: var(--vanna-border-radius-lg);
        color: var(--vanna-foreground-default);
        font-family: var(--vanna-font-family-mono);
        font-size: 0.875rem;
        transition: all var(--vanna-duration-200) ease;
        box-sizing: border-box;
      }

      .form-input:focus, .form-select:focus {
        outline: none;
        border-color: var(--vanna-iris);
        box-shadow: 0 0 0 3px var(--vanna-accent-primary-subtle);
      }

      .form-input::placeholder {
        color: var(--vanna-foreground-dimmest);
        font-family: var(--vanna-font-family-default);
      }

      .form-description {
        font-size: 0.75rem;
        color: var(--vanna-foreground-dimmer);
        margin-top: var(--vanna-space-1);
        line-height: 1.4;
      }

      .modal-footer {
        padding: var(--vanna-space-4) var(--vanna-space-5);
        border-top: 1px solid var(--vanna-outline-dimmer);
        display: flex;
        justify-content: flex-end;
        gap: var(--vanna-space-3);
        background: var(--vanna-background-root);
        border-bottom-left-radius: var(--vanna-border-radius-2xl);
        border-bottom-right-radius: var(--vanna-border-radius-2xl);
      }

      .btn {
        padding: 8px 16px;
        border-radius: 99px;
        font-size: 0.875rem;
        font-weight: 500;
        cursor: pointer;
        transition: all var(--vanna-duration-200) ease;
        border: 1px solid transparent;
      }

      .btn-secondary {
        background: transparent;
        border-color: var(--vanna-outline-dimmer);
        color: var(--vanna-foreground-default);
      }

      .btn-secondary:hover {
        background: var(--vanna-background-higher);
        border-color: var(--vanna-outline-default);
      }

      .btn-primary {
        background: var(--vanna-iris);
        color: white;
        box-shadow: 0 2px 4px rgba(99, 102, 241, 0.2);
      }

      .btn-primary:hover {
        background: var(--vanna-iris-dark);
        box-shadow: 0 4px 6px rgba(99, 102, 241, 0.3);
        transform: translateY(-1px);
      }

      .btn-primary:active {
        transform: translateY(0);
      }

      .alert {
        padding: var(--vanna-space-3) var(--vanna-space-4);
        border-radius: var(--vanna-border-radius-lg);
        margin-bottom: var(--vanna-space-4);
        font-size: 0.875rem;
        display: flex;
        align-items: center;
        gap: var(--vanna-space-2);
      }

      .alert-success {
        background: rgba(16, 185, 129, 0.1);
        color: var(--vanna-emerald);
        border: 1px solid rgba(16, 185, 129, 0.2);
      }

      .alert-error {
        background: rgba(244, 63, 94, 0.1);
        color: var(--vanna-rose);
        border: 1px solid rgba(244, 63, 94, 0.2);
      }

      /* Hidden utility */
      .hidden {
        display: none !important;
      }
    `
  ];

  @property({ type: Boolean }) open = false;
  @property() apiBase = '';
  
  @state() private activeTab: 'llm' | 'db' = 'llm';
  @state() private llmProvider: 'openrouter' | 'anthropic' | 'openai' = 'openrouter';
  @state() private llmApiKey = '';
  @state() private llmModel = '';
  
  @state() private dbType: 'sqlite' | 'postgres' | 'snowflake' = 'sqlite';
  @state() private dbUri = '';

  @state() private statusMessage = '';
  @state() private statusType: 'success' | 'error' | '' = '';
  @state() private isLoading = false;

  private _close() {
    this.open = false;
    this.statusMessage = '';
    // Dispatch event so parent component knows it closed
    this.dispatchEvent(new CustomEvent('settings-closed', {
      bubbles: true,
      composed: true
    }));
  }

  private _handleTab(tab: 'llm' | 'db') {
    this.activeTab = tab;
    this.statusMessage = '';
  }

  private async _saveConfig() {
    this.isLoading = true;
    this.statusMessage = '';
    this.statusType = '';

    const endpoint = this.activeTab === 'llm' 
      ? `${this.apiBase}/api/vanna/v3/config/llm`
      : `${this.apiBase}/api/vanna/v3/config/db`;

    const payload = this.activeTab === 'llm'
      ? { provider: this.llmProvider, api_key: this.llmApiKey, model: this.llmModel }
      : { type: this.dbType, uri: this.dbUri };

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const err = await response.json();
        throw new Error(err.detail || 'Failed to update configuration');
      }

      await response.json();
      this.statusType = 'success';
      this.statusMessage = 'Configuration updated successfully! The agent context has been reset.';
      
      // Tell parent to refresh/reset chat
      this.dispatchEvent(new CustomEvent('config-updated', {
        bubbles: true,
        composed: true,
        detail: { type: this.activeTab }
      }));
      
    } catch (e: any) {
      this.statusType = 'error';
      this.statusMessage = e.message || 'An network error occurred';
    } finally {
      this.isLoading = false;
    }
  }

  render() {
    return html`
      <div class="modal-backdrop ${this.open ? 'open' : ''}" @click=${this._close}></div>
      <div class="modal-container ${this.open ? 'open' : ''}">
        
        <div class="modal-header">
          <h2 class="modal-title">Developer Settings</h2>
          <button class="close-button" @click=${this._close}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M18 6L6 18M6 6l12 12"></path>
            </svg>
          </button>
        </div>

        <div class="modal-tabs">
          <button 
            class="tab ${this.activeTab === 'llm' ? 'active' : ''}" 
            @click=${() => this._handleTab('llm')}>
            LLM Configuration
          </button>
          <button 
            class="tab ${this.activeTab === 'db' ? 'active' : ''}" 
            @click=${() => this._handleTab('db')}>
            Database Sources
          </button>
        </div>

        <div class="modal-body">
          ${this.statusMessage ? html`
            <div class="alert alert-${this.statusType}">
              ${this.statusType === 'success' ? '✅' : '❌'} ${this.statusMessage}
            </div>
          ` : ''}

          <!-- LLM TAB -->
          <div class="${this.activeTab !== 'llm' ? 'hidden' : ''}">
            <div class="form-group">
              <label class="form-label">Provider</label>
              <select class="form-select" @change=${(e: any) => this.llmProvider = e.target.value}>
                <option value="openrouter" ?selected=${this.llmProvider === 'openrouter'}>OpenRouter</option>
                <option value="anthropic" ?selected=${this.llmProvider === 'anthropic'}>Anthropic</option>
                <option value="openai" ?selected=${this.llmProvider === 'openai'}>OpenAI</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">API Key</label>
              <input type="password" class="form-input" 
                placeholder="sk-..." 
                .value=${this.llmApiKey}
                @input=${(e: any) => this.llmApiKey = e.target.value}>
              <div class="form-description">Injected securely on the server. Never stored in local storage.</div>
            </div>
            <div class="form-group">
              <label class="form-label">Model (Optional)</label>
              <input type="text" class="form-input" 
                placeholder="e.g. gpt-4o" 
                .value=${this.llmModel}
                @input=${(e: any) => this.llmModel = e.target.value}>
            </div>
          </div>

          <!-- DB TAB -->
          <div class="${this.activeTab !== 'db' ? 'hidden' : ''}">
             <div class="form-group">
              <label class="form-label">Connection Type</label>
              <select class="form-select" @change=${(e: any) => this.dbType = e.target.value}>
                <option value="sqlite" ?selected=${this.dbType === 'sqlite'}>SQLite (Local)</option>
                <option value="postgres" ?selected=${this.dbType === 'postgres'}>PostgreSQL</option>
                <option value="snowflake" ?selected=${this.dbType === 'snowflake'}>Snowflake</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Connection URI / File Path</label>
              <input type="text" class="form-input" 
                placeholder="/path/to/db.sqlite or postgresql://..." 
                .value=${this.dbUri}
                @input=${(e: any) => this.dbUri = e.target.value}>
              <div class="form-description">WARNING: Connecting to a new database will clear the active Agent memory and chat context.</div>
            </div>
          </div>

        </div>

        <div class="modal-footer">
          <button class="btn btn-secondary" @click=${this._close}>Cancel</button>
          <button class="btn btn-primary" @click=${this._saveConfig} ?disabled=${this.isLoading}>
            ${this.isLoading ? 'Saving...' : 'Save & Hot-Swap'}
          </button>
        </div>
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'vanna-settings-panel': VannaSettingsPanel;
  }
}
