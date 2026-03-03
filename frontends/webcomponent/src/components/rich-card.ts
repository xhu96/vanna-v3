import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { vannaDesignTokens } from '../styles/vanna-design-tokens.js';

export interface CardAction {
  label: string;
  action: string;
  variant?: 'primary' | 'secondary';
}

@customElement('rich-card')
export class RichCard extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        margin-bottom: var(--vanna-space-4);
        font-family: var(--vanna-font-family-default);
      }

      .card {
        border: 1px solid var(--vanna-outline-dimmer);
        border-radius: var(--vanna-border-radius-xl);
        background: var(--vanna-background-root);
        box-shadow: 0 4px 12px -2px rgba(15, 23, 42, 0.05);
        overflow: hidden;
        transition: box-shadow var(--vanna-duration-300) ease, transform var(--vanna-duration-300) ease;
      }

      .card:hover {
        box-shadow: 0 8px 24px -4px rgba(15, 23, 42, 0.08);
      }

      .card-header {
        display: flex;
        align-items: center;
        padding: var(--vanna-space-4) var(--vanna-space-5);
        background: var(--vanna-background-root);
        border-bottom: 1px solid var(--vanna-outline-dimmer);
        gap: var(--vanna-space-3);
      }

      .card-header.collapsible {
        cursor: pointer;
        transition: background-color var(--vanna-duration-200) ease;
      }
      
      .card-header.collapsible:hover {
        background: var(--vanna-background-higher);
      }

      .card-icon {
        font-size: 1.25rem;
        display: flex;
        align-items: center;
        color: var(--vanna-iris);
        background: var(--vanna-accent-primary-subtle);
        padding: 8px;
        border-radius: var(--vanna-border-radius-md);
      }

      .card-title-section {
        flex: 1;
      }

      .card-title {
        margin: 0;
        font-size: 1rem;
        font-weight: 600;
        color: var(--vanna-foreground-default);
        letter-spacing: -0.01em;
      }

      .card-subtitle {
        margin: var(--vanna-space-1) 0 0 0;
        font-size: 0.875rem;
        color: var(--vanna-foreground-dimmer);
      }

      .card-status {
        padding: var(--vanna-space-1) var(--vanna-space-2);
        border-radius: var(--vanna-border-radius-full);
        font-size: 0.65rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
      }

      .card-status.status-success {
        background: rgba(16, 185, 129, 0.1);
        color: var(--vanna-emerald);
      }

      .card-status.status-warning {
        background: rgba(245, 158, 11, 0.1);
        color: var(--vanna-amber);
      }

      .card-status.status-error {
        background: rgba(244, 63, 94, 0.1);
        color: var(--vanna-rose);
      }

      .card-status.status-info {
        background: rgba(99, 102, 241, 0.1);
        color: var(--vanna-iris);
      }

      .card-toggle {
        background: var(--vanna-background-higher);
        border: 1px solid var(--vanna-outline-dimmer);
        cursor: pointer;
        font-size: 0.7rem;
        color: var(--vanna-foreground-dimmer);
        padding: var(--vanna-space-2);
        border-radius: var(--vanna-border-radius-full);
        transition: all var(--vanna-duration-200) ease;
        display: flex;
        align-items: center;
        justify-content: center;
        width: 24px;
        height: 24px;
      }

      .card-toggle:hover {
        background: var(--vanna-background-highest);
        color: var(--vanna-foreground-default);
        transform: scale(1.05);
      }

      .card-content {
        padding: var(--vanna-space-5);
        line-height: 1.6;
        color: var(--vanna-foreground-dimmer);
        transition: all var(--vanna-duration-300) cubic-bezier(0.16, 1, 0.3, 1);
        overflow: hidden;
      }

      .card-content.collapsed {
        max-height: 0;
        padding-top: 0;
        padding-bottom: 0;
        opacity: 0;
      }

      .card-content h1,
      .card-content h2,
      .card-content h3 {
        margin: var(--vanna-space-3) 0 var(--vanna-space-2);
        font-weight: 600;
        color: var(--vanna-foreground-default);
        letter-spacing: -0.01em;
      }

      .card-content h1 {
        font-size: 1.25rem;
      }

      .card-content h2 {
        font-size: 1.125rem;
      }

      .card-content h3 {
        font-size: 1rem;
      }

      .card-content p {
        margin: 0 0 var(--vanna-space-3) 0;
      }

      .card-content p:last-child {
        margin-bottom: 0;
      }

      .card-content ul {
        margin: var(--vanna-space-2) 0;
        padding-left: var(--vanna-space-5);
      }

      .card-content li {
        margin: var(--vanna-space-1) 0;
      }

      .card-content code {
        background: var(--vanna-background-higher);
        padding: 2px 4px;
        border: 1px solid var(--vanna-outline-dimmer);
        border-radius: var(--vanna-border-radius-sm);
        font-family: var(--vanna-font-family-mono);
        font-size: 0.85em;
        color: var(--vanna-foreground-default);
      }

      .card-content strong {
        font-weight: 600;
        color: var(--vanna-foreground-default);
      }

      .card-actions {
        padding: var(--vanna-space-3) var(--vanna-space-5);
        background: var(--vanna-background-root);
        border-top: 1px solid var(--vanna-outline-dimmest);
        display: flex;
        flex-wrap: wrap;
        gap: var(--vanna-space-2);
      }

      .card-action {
        padding: 6px 14px;
        border-radius: 99px;
        border: 1px solid var(--vanna-outline-dimmer);
        background: var(--vanna-background-root);
        color: var(--vanna-foreground-default);
        cursor: pointer;
        font-size: 0.8rem;
        font-weight: 500;
        transition: all var(--vanna-duration-200) ease;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05);
      }

      .card-action:hover {
        background: var(--vanna-background-higher);
        border-color: var(--vanna-outline-default);
        transform: translateY(-1px);
        box-shadow: 0 2px 4px rgba(15, 23, 42, 0.05);
      }

      .card-action:active {
        transform: translateY(0);
      }

      .card-action.primary {
        background: var(--vanna-iris);
        color: white;
        border-color: var(--vanna-iris);
        box-shadow: 0 2px 4px rgba(99, 102, 241, 0.2);
      }

      .card-action.primary:hover {
        background: var(--vanna-iris-dark);
        border-color: var(--vanna-iris-dark);
        box-shadow: 0 4px 6px rgba(99, 102, 241, 0.25);
      }
    `
  ];

  @property() title = '';
  @property() subtitle = '';
  @property() content = '';
  @property() icon = '';
  @property() status: 'info' | 'success' | 'warning' | 'error' = 'info';
  @property({ type: Array }) actions: CardAction[] = [];
  @property({ type: Boolean }) collapsible = false;
  @property({ type: Boolean }) collapsed = false;
  @property({ type: Boolean }) markdown = false;
  @property() theme: 'light' | 'dark' = 'dark';

  private _toggleCollapsed() {
    if (this.collapsible) {
      this.collapsed = !this.collapsed;
    }
  }

  private _escapeHtml(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  private _renderMarkdown(text: string): string {
    // Escape all HTML entities first to prevent XSS, then apply markdown transforms.
    const escaped = this._escapeHtml(text);
    return escaped
      .replace(/^### (.*$)/gm, '<h3>$1</h3>')
      .replace(/^## (.*$)/gm, '<h2>$1</h2>')
      .replace(/^# (.*$)/gm, '<h1>$1</h1>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/^- (.*$)/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
      .replace(/\n\n/g, '</p><p>')
      .replace(/^(?!<[h|u|l|p])(.+)$/gm, '<p>$1</p>');
  }

  render() {
    const contentHtml = this.markdown
      ? html`<div class="card-content ${this.collapsed ? 'collapsed' : ''}" .innerHTML=${this._renderMarkdown(this.content)}></div>`
      : html`<div class="card-content ${this.collapsed ? 'collapsed' : ''}">${this.content}</div>`;

    return html`
      <div class="card">
        <div class="card-header ${this.collapsible ? 'collapsible' : ''}"
             @click=${this._toggleCollapsed}>
          ${this.icon ? html`<span class="card-icon">${this.icon}</span>` : ''}
          <div class="card-title-section">
            <h3 class="card-title">${this.title}</h3>
            ${this.subtitle ? html`<p class="card-subtitle">${this.subtitle}</p>` : ''}
          </div>
          ${this.status ? html`<span class="card-status status-${this.status}">${this.status}</span>` : ''}
          ${this.collapsible ? html`
            <button class="card-toggle">${this.collapsed ? '▶' : '▼'}</button>
          ` : ''}
        </div>
        ${contentHtml}
        ${this.actions.length > 0 ? html`
          <div class="card-actions">
            ${this.actions.map(action => html`
              <button class="card-action ${action.variant || 'secondary'}"
                      @click=${() => this._handleAction(action.action)}>
                ${action.label}
              </button>
            `)}
          </div>
        ` : ''}
      </div>
    `;
  }

  private async _handleAction(action: string) {
    console.log('🔘 Card action button clicked (rich-card)');
    console.log('   Action:', action);

    // Dispatch event for any listeners
    this.dispatchEvent(new CustomEvent('card-action', {
      detail: { action },
      bubbles: true,
      composed: true
    }));

    // Also directly send to vanna-chat
    const vannaChat = document.querySelector('vanna-chat') as any;
    if (vannaChat && typeof vannaChat.sendMessage === 'function') {
      console.log('   Found vanna-chat, sending message...');
      try {
        const success = await vannaChat.sendMessage(action);
        if (success) {
          console.log('   ✅ Action sent successfully');
        } else {
          console.error('   ❌ Failed to send action');
        }
      } catch (error) {
        console.error('   ❌ Error sending action:', error);
      }
    } else {
      console.warn('   ⚠️ vanna-chat component not found or sendMessage not available');
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'rich-card': RichCard;
  }
}