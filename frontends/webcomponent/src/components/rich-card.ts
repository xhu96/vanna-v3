import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";
import { vannaDesignTokens } from "../styles/vanna-design-tokens.js";
import {
  renderSanitizedHtml,
  renderSanitizedMarkdown,
} from "../security/content-security.js";

export interface CardAction {
  label: string;
  action: string;
  variant?: "primary" | "secondary";
}

@customElement("rich-card")
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
        border: 1px solid var(--vanna-outline-default);
        border-radius: var(--vanna-border-radius-lg);
        background: var(--vanna-background-default);
        box-shadow: var(--vanna-shadow-sm);
        overflow: hidden;
        transition: box-shadow var(--vanna-duration-200) ease;
      }

      .card:hover {
        box-shadow: var(--vanna-shadow-md);
      }

      .card-header {
        display: flex;
        align-items: center;
        padding: var(--vanna-space-4) var(--vanna-space-5);
        background: var(--vanna-background-higher);
        border-bottom: 1px solid var(--vanna-outline-default);
        gap: var(--vanna-space-3);
      }

      .card-header.collapsible {
        cursor: pointer;
      }

      .card-icon {
        font-size: 1.25rem;
        display: flex;
        align-items: center;
      }

      .card-title-section {
        flex: 1;
      }

      .card-title {
        margin: 0;
        font-size: 1rem;
        font-weight: 600;
        color: var(--vanna-foreground-default);
      }

      .card-subtitle {
        margin: var(--vanna-space-1) 0 0 0;
        font-size: 0.875rem;
        color: var(--vanna-foreground-dimmer);
      }

      .card-status {
        padding: var(--vanna-space-1) var(--vanna-space-2);
        border-radius: var(--vanna-border-radius-md);
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
      }

      .card-status.status-success {
        background: #d4edda;
        color: #155724;
      }

      .card-status.status-warning {
        background: #fff3cd;
        color: #856404;
      }

      .card-status.status-error {
        background: #f8d7da;
        color: #721c24;
      }

      .card-status.status-info {
        background: #d1ecf1;
        color: #0c5460;
      }

      .card-toggle {
        background: none;
        border: none;
        cursor: pointer;
        font-size: 1rem;
        color: var(--vanna-foreground-dimmer);
        padding: var(--vanna-space-1);
        border-radius: var(--vanna-border-radius-sm);
        transition: background-color var(--vanna-duration-200) ease;
      }

      .card-toggle:hover {
        background: var(--vanna-background-root);
      }

      .card-content {
        padding: var(--vanna-space-4) var(--vanna-space-5);
        line-height: 1.5;
        color: var(--vanna-foreground-default);
        transition: all var(--vanna-duration-200) ease;
        overflow: hidden;
      }

      .card-content.collapsed {
        max-height: 0;
        padding-top: 0;
        padding-bottom: 0;
      }

      .card-content h1,
      .card-content h2,
      .card-content h3 {
        margin: var(--vanna-space-2) 0;
        font-weight: 600;
      }

      .card-content h1 {
        font-size: 1.5rem;
      }

      .card-content h2 {
        font-size: 1.25rem;
      }

      .card-content h3 {
        font-size: 1.125rem;
      }

      .card-content p {
        margin: var(--vanna-space-2) 0;
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
        padding: var(--vanna-space-1) var(--vanna-space-2);
        border-radius: var(--vanna-border-radius-sm);
        font-family: monospace;
        font-size: 0.875em;
      }

      .card-content strong {
        font-weight: 600;
      }

      .card-actions {
        padding: var(--vanna-space-3) var(--vanna-space-5);
        background: var(--vanna-background-root);
        border-top: 1px solid var(--vanna-outline-default);
        display: flex;
        gap: var(--vanna-space-2);
      }

      .card-action {
        padding: var(--vanna-space-2) var(--vanna-space-4);
        border-radius: var(--vanna-border-radius-md);
        border: 1px solid var(--vanna-outline-default);
        background: var(--vanna-background-default);
        color: var(--vanna-foreground-default);
        cursor: pointer;
        font-size: 0.875rem;
        font-weight: 500;
        transition: all var(--vanna-duration-200) ease;
      }

      .card-action:hover {
        background: var(--vanna-background-higher);
      }

      .card-action.primary {
        background: var(--vanna-accent-primary-default);
        color: white;
        border-color: var(--vanna-accent-primary-default);
      }

      .card-action.primary:hover {
        background: var(--vanna-accent-primary-stronger);
      }

      :host {
        margin-bottom: 0;
      }

      .card {
        background: var(--vanna-background-root);
        border-color: var(--vanna-outline-default);
        border-radius: var(--vanna-border-radius-lg);
        box-shadow: none;
      }

      .card:hover {
        box-shadow: none;
      }

      .card-header {
        padding: 14px 17px;
        background: var(--vanna-background-subtle);
        border-bottom-color: var(--vanna-outline-dimmer);
      }

      .card-title {
        font-family: var(--vanna-font-family-display);
        font-size: 14px;
        font-weight: 650;
        letter-spacing: -0.015em;
      }

      .card-subtitle {
        font-size: 11px;
        line-height: 1.45;
      }

      .card-status {
        border-radius: var(--vanna-border-radius-full);
        font-family: var(--vanna-font-family-default);
        font-size: 10px;
        letter-spacing: 0;
        text-transform: none;
      }

      .card-status.status-success {
        color: var(--vanna-accent-positive-stronger);
        background: var(--vanna-accent-positive-subtle);
      }

      .card-status.status-warning {
        color: var(--vanna-accent-warning-stronger);
        background: var(--vanna-accent-warning-subtle);
      }

      .card-status.status-error {
        color: var(--vanna-accent-negative-stronger);
        background: var(--vanna-accent-negative-subtle);
      }

      .card-status.status-info {
        color: var(--vanna-accent-primary-stronger);
        background: var(--vanna-accent-primary-subtle);
      }

      .card-content {
        padding: 16px 17px;
        font-size: 13px;
        line-height: 1.6;
      }

      .card-actions {
        padding: 11px 17px;
        background: var(--vanna-background-subtle);
        border-top-color: var(--vanna-outline-dimmer);
      }

      .card-action {
        padding: 7px 11px;
        background: var(--vanna-background-root);
        border-radius: var(--vanna-border-radius-md);
        font-size: 11px;
        font-weight: 650;
      }

      .card-action.primary {
        background: var(--vanna-navy);
        border-color: var(--vanna-navy);
      }

      .card-toggle svg {
        display: block;
        width: 16px;
        height: 16px;
        transition: transform var(--vanna-duration-100) ease;
      }

      .card-toggle[aria-expanded="false"] svg {
        transform: rotate(-90deg);
      }

      .card-action:focus-visible,
      .card-toggle:focus-visible {
        outline: 2px solid var(--vanna-teal);
        outline-offset: 2px;
      }

      @media (prefers-reduced-motion: reduce) {
        .card,
        .card-content,
        .card-action {
          transition-duration: 0.01ms;
        }
      }
    `,
  ];

  @property() title = "";
  @property() subtitle = "";
  @property() content = "";
  @property() icon = "";
  @property() status: "info" | "success" | "warning" | "error" = "info";
  @property({ type: Array }) actions: CardAction[] = [];
  @property({ type: Boolean }) collapsible = false;
  @property({ type: Boolean }) collapsed = false;
  @property({ type: Boolean }) markdown = false;
  @property() theme: "light" | "dark" = "dark";

  private _toggleCollapsed() {
    if (this.collapsible) {
      this.collapsed = !this.collapsed;
    }
  }

  render() {
    const contentHtml = this.markdown
      ? html`<div class="card-content ${this.collapsed ? "collapsed" : ""}">
          ${renderSanitizedHtml(renderSanitizedMarkdown(this.content))}
        </div>`
      : html`<div class="card-content ${this.collapsed ? "collapsed" : ""}">
          ${this.content}
        </div>`;

    return html`
      <div class="card">
        <div
          class="card-header ${this.collapsible ? "collapsible" : ""}"
          @click=${this._toggleCollapsed}
        >
          ${this.icon ? html`<span class="card-icon">${this.icon}</span>` : ""}
          <div class="card-title-section">
            <h3 class="card-title">${this.title}</h3>
            ${this.subtitle
              ? html`<p class="card-subtitle">${this.subtitle}</p>`
              : ""}
          </div>
          ${this.status
            ? html`<span class="card-status status-${this.status}"
                >${this.status}</span
              >`
            : ""}
          ${this.collapsible
            ? html`
                <button
                  class="card-toggle"
                  type="button"
                  aria-label="Toggle details"
                  aria-expanded=${String(!this.collapsed)}
                >
                  <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path
                      d="M4.5 6l3.5 3.5L11.5 6"
                      stroke="currentColor"
                      stroke-width="1.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                </button>
              `
            : ""}
        </div>
        ${contentHtml}
        ${this.actions.length > 0
          ? html`
              <div class="card-actions">
                ${this.actions.map(
                  (action) => html`
                    <button
                      class="card-action ${action.variant || "secondary"}"
                      @click=${() => this._handleAction(action.action)}
                    >
                      ${action.label}
                    </button>
                  `,
                )}
              </div>
            `
          : ""}
      </div>
    `;
  }

  private async _handleAction(action: string) {
    // Dispatch event for any listeners
    this.dispatchEvent(
      new CustomEvent("card-action", {
        detail: { action },
        bubbles: true,
        composed: true,
      }),
    );

    // Also directly send to vanna-chat
    const vannaChat = document.querySelector("vanna-chat") as any;
    if (vannaChat && typeof vannaChat.sendMessage === "function") {
      try {
        await vannaChat.sendMessage(action);
      } catch {
        // The chat component owns user-visible transport errors.
      }
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "rich-card": RichCard;
  }
}
