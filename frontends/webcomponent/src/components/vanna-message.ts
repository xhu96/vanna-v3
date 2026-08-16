import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";
import { vannaDesignTokens } from "../styles/vanna-design-tokens.js";

@customElement("vanna-message")
export class VannaMessage extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        margin: 0;
        font-family: var(--vanna-font-family-default);
      }

      .message {
        display: flex;
        width: min(760px, 100%);
        flex-direction: column;
        gap: 7px;
        padding: 2px 0 18px;
        overflow-wrap: anywhere;
        color: var(--vanna-foreground-default);
        border-bottom: 1px solid var(--vanna-outline-dimmer);
      }

      .message.user {
        width: min(700px, 94%);
        padding: 13px 15px;
        background: var(--vanna-background-default);
        border: 1px solid var(--vanna-outline-default);
        border-radius: var(--vanna-border-radius-lg);
      }

      .message-content {
        margin: 0;
        font-size: 14px;
        font-weight: 430;
        line-height: 1.6;
        white-space: pre-wrap;
      }

      .message-content a {
        color: inherit;
        font-weight: 600;
        text-decoration-thickness: 1px;
        text-underline-offset: 3px;
      }

      .message-content code {
        padding: 2px 5px;
        color: inherit;
        background: var(--vanna-background-higher);
        border: 1px solid var(--vanna-outline-dimmer);
        border-radius: var(--vanna-border-radius-sm);
        font-family: var(--vanna-font-family-mono);
        font-size: 12px;
      }

      .message-meta {
        display: flex;
        align-items: center;
        gap: 8px;
        color: var(--vanna-foreground-dimmest);
        font-size: 10px;
        font-weight: 560;
        line-height: 1.2;
      }

      .message-meta span:first-child {
        color: var(--vanna-foreground-default);
        font-weight: 650;
      }

      @media (max-width: 600px) {
        .message.user {
          width: 100%;
        }
      }
    `,
  ];

  @property() content = "";
  @property() type: "user" | "assistant" = "user";
  @property({ type: Number }) timestamp = Date.now();
  @property({ reflect: true }) theme = "light";

  private formatTimestamp(timestamp: number): string {
    if (Math.abs(Date.now() - timestamp) < 60_000) return "Now";
    return new Date(timestamp).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  render() {
    const speaker = this.type === "user" ? "You" : "Vanna";
    return html`
      <div class="message ${this.type}" aria-label="${speaker} message">
        <div class="message-meta">
          <span>${speaker}</span>
          <span>${this.formatTimestamp(this.timestamp)}</span>
        </div>
        <div class="message-content">${this.content}</div>
      </div>
    `;
  }
}
