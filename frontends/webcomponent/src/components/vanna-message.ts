import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { vannaDesignTokens } from '../styles/vanna-design-tokens.js';

@customElement('vanna-message')
export class VannaMessage extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        padding: 0 var(--vanna-space-2);
        margin-bottom: var(--vanna-space-4);
        font-family: var(--vanna-font-family-default);
        animation: fade-in-up 0.25s ease-out;
      }

      :host(:last-of-type) {
        margin-bottom: 0;
      }

      @keyframes fade-in-up {
        from {
          opacity: 0;
          transform: translateY(16px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      .message {
        position: relative;
        padding: var(--vanna-space-4) var(--vanna-space-5);
        border-radius: var(--vanna-chat-bubble-radius);
        word-wrap: break-word;
        line-height: 1.6;
        display: flex;
        flex-direction: column;
        gap: var(--vanna-space-2);
        max-width: min(85%, 580px);
        transition: transform var(--vanna-duration-300) cubic-bezier(0.16, 1, 0.3, 1), box-shadow var(--vanna-duration-300) ease;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
      }

      .message.assistant {
        background: var(--vanna-background-root);
        border: 1px solid var(--vanna-outline-dimmer);
        color: var(--vanna-foreground-default);
        box-shadow: 0 4px 12px -2px rgba(15, 23, 42, 0.05);
        border-radius: var(--vanna-chat-bubble-radius) var(--vanna-chat-bubble-radius) var(--vanna-chat-bubble-radius) var(--vanna-chat-bubble-radius-sm);
      }

      .message.user {
        margin-left: auto;
        max-width: min(80%, 500px);
        background: linear-gradient(135deg, var(--vanna-iris-light) 0%, var(--vanna-iris) 100%);
        color: white;
        box-shadow: 0 6px 16px -4px rgba(99, 102, 241, 0.25), inset 0 1px 0 rgba(255, 255, 255, 0.2);
        border-radius: var(--vanna-chat-bubble-radius) var(--vanna-chat-bubble-radius) var(--vanna-chat-bubble-radius-sm) var(--vanna-chat-bubble-radius);
        border: 1px solid rgba(255, 255, 255, 0.1);
      }

      .message:hover {
        transform: translateY(-2px);
      }

      .message.assistant:hover {
        box-shadow: 0 6px 16px -2px rgba(15, 23, 42, 0.08);
        border-color: var(--vanna-outline-default);
      }

      .message.user:hover {
        box-shadow: 0 8px 24px -4px rgba(99, 102, 241, 0.35);
      }

      .message-content {
        margin: 0;
        font-size: 15px;
        letter-spacing: 0.01em;
        white-space: pre-wrap;
        font-weight: 400;
      }

      .message-content a {
        color: inherit;
        font-weight: 500;
        text-decoration: underline;
        text-decoration-thickness: 1px;
        text-underline-offset: 2px;
        opacity: 0.9;
      }

      .message-content code {
        font-family: var(--vanna-font-family-mono);
        background: var(--vanna-background-higher);
        padding: 2px 6px;
        border-radius: var(--vanna-border-radius-sm);
        font-size: 13px;
        border: 1px solid var(--vanna-outline-dimmer);
      }

      .message.user .message-content code {
        background: rgba(255, 255, 255, 0.2);
        border-color: rgba(255, 255, 255, 0.3);
      }

      .message-timestamp {
        display: inline-flex;
        align-items: center;
        gap: var(--vanna-space-1);
        font-size: 11px;
        letter-spacing: 0.05em;
        margin-top: var(--vanna-space-2);
        font-family: var(--vanna-font-family-default);
        opacity: 0.7;
        font-weight: 500;
      }

      .message-timestamp::before {
        content: '';
        width: 3px;
        height: 3px;
        border-radius: var(--vanna-border-radius-full);
        background: currentColor;
        opacity: 0.8;
      }

      .message.assistant .message-timestamp {
        align-self: flex-start;
        color: var(--vanna-foreground-dimmest);
      }

      .message.assistant .message-timestamp::before {
        background: var(--vanna-accent-primary-default);
      }

      .message.user .message-timestamp {
        align-self: flex-end;
        color: rgba(255, 255, 255, 0.8);
      }

      .message.user .message-timestamp::before {
        background: rgba(255, 255, 255, 0.8);
      }

      :host([theme="dark"]) .message.assistant {
        background: rgba(30, 41, 59, 0.6);
        border: 1px solid rgba(255, 255, 255, 0.05);
        color: var(--vanna-foreground-default);
        box-shadow: 0 4px 12px -2px rgba(0, 0, 0, 0.4);
      }

      :host([theme="dark"]) .message.assistant .message-content code {
        background: rgba(15, 23, 42, 0.8);
        border-color: rgba(255, 255, 255, 0.05);
      }

      :host([theme="dark"]) .message.assistant .message-timestamp {
        color: var(--vanna-foreground-dimmest);
      }

      :host([theme="dark"]) .message.assistant .message-timestamp::before {
        background: var(--vanna-iris);
      }

      :host([theme="dark"]) .message.user {
        background: linear-gradient(135deg, var(--vanna-iris) 0%, var(--vanna-iris-dark) 100%);
        color: white;
        box-shadow: 0 6px 16px -4px rgba(0, 0, 0, 0.5), inset 0 1px 0 rgba(255, 255, 255, 0.1);
      }

      :host([theme="dark"]) .message.user .message-content code {
        background: rgba(255, 255, 255, 0.15);
        border-color: rgba(255, 255, 255, 0.2);
      }

      :host([theme="dark"]) .message.user .message-timestamp {
        color: rgba(255, 255, 255, 0.8);
      }

      :host([theme="dark"]) .message.user .message-timestamp::before {
        background: rgba(255, 255, 255, 0.8);
      }

      @media (max-width: 600px) {
        .message {
          max-width: 100%;
        }

        .message.user {
          max-width: 100%;
        }
      }
    `
  ];

  @property() content = '';
  @property() type: 'user' | 'assistant' = 'user';
  @property({ type: Number }) timestamp = Date.now();
  @property({ reflect: true }) theme = 'light';

  private formatTimestamp(timestamp: number): string {
    return new Date(timestamp).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  render() {
    return html`
      <div class="message ${this.type}">
        <div class="message-content">${this.content}</div>
        <div class="message-timestamp">
          ${this.formatTimestamp(this.timestamp)}
        </div>
      </div>
    `;
  }
}
