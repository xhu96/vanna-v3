import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";
import "@spectrum-web-components/progress-circle/sp-progress-circle.js";
import { vannaDesignTokens } from "../styles/vanna-design-tokens.js";

@customElement("vanna-status-bar")
export class VannaStatusBar extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        max-height: 52px;
        overflow: hidden;
        padding: 7px 9px;
        color: var(--vanna-foreground-dimmer);
        background: var(--vanna-background-root);
        border: 1px solid var(--vanna-outline-default);
        border-radius: var(--vanna-border-radius-md);
        font-family: var(--vanna-font-family-default);
        font-size: 11px;
        opacity: 1;
        transition:
          opacity var(--vanna-duration-200) ease,
          transform var(--vanna-duration-200) ease,
          max-height var(--vanna-duration-200) ease,
          padding var(--vanna-duration-200) ease;
      }

      :host(.no-content),
      :host(:empty) {
        max-height: 0;
        padding-top: 0;
        padding-bottom: 0;
        pointer-events: none;
        opacity: 0;
        transform: translateY(-3px);
      }

      :host(.entering) {
        animation: status-enter 200ms ease-out;
      }

      :host(.exiting) {
        opacity: 0;
        transform: translateY(-3px);
      }

      :host([status="working"]) {
        color: var(--vanna-foreground-default);
        background: var(--vanna-background-root);
        border-color: var(--vanna-outline-default);
      }

      :host([status="success"]) {
        color: var(--vanna-accent-positive-stronger);
        background: var(--vanna-accent-positive-subtle);
        border-color: var(--vanna-accent-positive-default);
      }

      :host([status="error"]) {
        color: var(--vanna-accent-negative-stronger);
        background: var(--vanna-accent-negative-subtle);
        border-color: var(--vanna-accent-negative-default);
      }

      .status-content {
        display: flex;
        min-width: 0;
        align-items: center;
        gap: 8px;
      }

      .status-indicator {
        width: 7px;
        height: 7px;
        flex: 0 0 auto;
        background: var(--vanna-outline-hover);
        border-radius: 50%;
      }

      .status-indicator.success {
        background: var(--vanna-accent-positive-default);
      }

      .status-indicator.error {
        background: var(--vanna-accent-negative-default);
      }

      .status-progress {
        width: 13px;
        height: 13px;
        flex: 0 0 auto;

        --mod-progress-circle-track-fill-color: var(
          --vanna-accent-primary-default
        );
      }

      .status-text {
        min-width: 0;
        overflow: hidden;
        font-weight: 600;
        line-height: 1.35;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .status-detail {
        margin-left: auto;
        overflow: hidden;
        color: var(--vanna-foreground-dimmest);
        font-size: 10px;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      @keyframes status-enter {
        from {
          opacity: 0;
          transform: translateY(-3px);
        }
        to {
          opacity: 1;
          transform: translateY(0);
        }
      }

      @media (prefers-reduced-motion: reduce) {
        :host,
        .status-progress {
          animation-duration: 0.01ms !important;
          animation-iteration-count: 1 !important;
          transition-duration: 0.01ms !important;
        }
      }
    `,
  ];

  @property() status: "idle" | "working" | "error" | "success" = "idle";
  @property() message = "";
  @property() detail = "";
  @property() theme = "light";

  private _previousHasContent = false;
  private _enterTimeout: number | null = null;
  private _exitTimeout: number | null = null;
  private _lastUpdateTime = 0;

  disconnectedCallback() {
    super.disconnectedCallback();

    // Clean up pending animation timeouts when component is removed
    if (this._enterTimeout !== null) {
      clearTimeout(this._enterTimeout);
      this._enterTimeout = null;
    }
    if (this._exitTimeout !== null) {
      clearTimeout(this._exitTimeout);
      this._exitTimeout = null;
    }
  }

  updated(_changedProperties: Map<string | number | symbol, unknown>) {
    // Update CSS class based on content
    const hasContent = Boolean(this.message && this.message.trim());

    // Cancel any pending animation timeouts to prevent race conditions
    if (this._enterTimeout !== null) {
      clearTimeout(this._enterTimeout);
      this._enterTimeout = null;
    }
    if (this._exitTimeout !== null) {
      clearTimeout(this._exitTimeout);
      this._exitTimeout = null;
    }

    // Debounce rapid updates to prevent animation jank
    const now = Date.now();
    const timeSinceLastUpdate = now - this._lastUpdateTime;
    const shouldDebounce = timeSinceLastUpdate < 100; // 100ms debounce

    // Handle animation classes
    if (hasContent !== this._previousHasContent) {
      if (hasContent) {
        // Content appeared - animate in
        this.classList.remove("no-content", "exiting");

        if (!shouldDebounce) {
          // Only animate if not rapid-firing
          this.classList.add("entering");

          // Remove entering class after animation
          this._enterTimeout = window.setTimeout(() => {
            this.classList.remove("entering");
            this._enterTimeout = null;
          }, 300);
        }
      } else {
        // Content disappeared - animate out
        this.classList.remove("entering");

        if (!shouldDebounce) {
          // Only animate if not rapid-firing
          this.classList.add("exiting");

          // Add no-content class after animation
          this._exitTimeout = window.setTimeout(() => {
            this.classList.remove("exiting");
            this.classList.add("no-content");
            this._exitTimeout = null;
          }, 300);
        } else {
          // If rapid-firing, skip animation and go straight to no-content
          this.classList.add("no-content");
        }
      }
    } else if (!hasContent) {
      // Ensure no-content class is applied when no content
      this.classList.add("no-content");
    }

    this._previousHasContent = hasContent;
    this._lastUpdateTime = now;
  }

  render() {
    // Only show if there's actual content (message) to display
    if (!this.message || !this.message.trim()) {
      return html``;
    }

    return html`
      <div
        class="status-content"
        role=${this.status === "error" ? "alert" : "status"}
        aria-live=${this.status === "error" ? "assertive" : "polite"}
      >
        ${this.status === "working"
          ? html`<sp-progress-circle
              class="status-progress"
              size="s"
              label=${this.message}
            ></sp-progress-circle>`
          : html`<div class="status-indicator ${this.status}"></div>`}
        <span class="status-text">${this.message}</span>
        ${this.detail
          ? html`<span class="status-detail">${this.detail}</span>`
          : ""}
      </div>
    `;
  }
}
