import { LitElement, html, css } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import "@spectrum-web-components/progress-circle/sp-progress-circle.js";
import { vannaDesignTokens } from "../styles/vanna-design-tokens.js";

interface ProgressItem {
  id: string;
  text: string;
  status: "pending" | "in_progress" | "completed" | "error";
  detail?: string;
}

@customElement("vanna-progress-tracker")
export class VannaProgressTracker extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        overflow: hidden;
        color: var(--vanna-foreground-default);
        background: transparent;
        font-family: var(--vanna-font-family-default);
      }

      .progress-label {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 12px;
        padding: 0 0 8px;
      }

      .progress-label-text {
        margin: 0;
        color: var(--vanna-foreground-dimmer);
        font-size: 10px;
        font-weight: 620;
      }

      .progress-summary {
        color: var(--vanna-foreground-dimmest);
        font-size: 9px;
      }

      .progress-list {
        max-height: 390px;
        overflow-y: auto;
        border-top: 1px solid var(--vanna-outline-dimmer);
      }

      .progress-item {
        position: relative;
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 10px 0;
      }

      .progress-item + .progress-item {
        border-top: 1px solid var(--vanna-outline-dimmer);
      }

      .progress-item.in_progress {
        color: var(--vanna-accent-primary-stronger);
      }

      .progress-item.error {
        color: var(--vanna-accent-negative-stronger);
      }

      .progress-icon {
        display: grid;
        width: 18px;
        height: 18px;
        flex: 0 0 auto;
        margin-top: 1px;
        place-items: center;
        color: var(--vanna-foreground-dimmest);
      }

      .progress-icon.in_progress {
        color: var(--vanna-accent-primary-default);
      }

      .progress-icon.completed {
        color: var(--vanna-accent-positive-default);
      }

      .progress-icon.error {
        color: var(--vanna-accent-negative-default);
      }

      .progress-icon svg {
        width: 14px;
        height: 14px;
      }

      .spinner-mini {
        width: 13px;
        height: 13px;

        --mod-progress-circle-track-fill-color: var(
          --vanna-accent-primary-default
        );
      }

      .progress-content {
        min-width: 0;
        flex: 1;
        padding-top: 0;
      }

      .progress-text {
        margin: 0;
        color: var(--vanna-foreground-default);
        font-size: 11px;
        font-weight: 610;
        line-height: 1.35;
      }

      .progress-detail {
        margin: 3px 0 0;
        color: var(--vanna-foreground-dimmest);
        font-size: 10px;
        line-height: 1.45;
      }

      .progress-item.error .progress-text,
      .progress-item.error .progress-detail {
        color: var(--vanna-accent-negative-stronger);
      }

      .empty-state {
        padding: 12px 0;
        color: var(--vanna-foreground-dimmest);
        font-size: 10px;
        line-height: 1.5;
        text-align: left;
      }

      @media (prefers-reduced-motion: reduce) {
        .spinner-mini {
          animation-duration: 0.01ms;
          animation-iteration-count: 1;
        }
      }
    `,
  ];

  @property() title = "Progress";
  @property() theme = "light";
  @state() private items: ProgressItem[] = [];

  addItem(text: string, detail?: string, id?: string): string {
    const itemId = id || Date.now().toString();
    this.items = [
      ...this.items,
      {
        id: itemId,
        text,
        status: "pending",
        detail,
      },
    ];
    return itemId;
  }

  updateItem(id: string, status: ProgressItem["status"], detail?: string) {
    this.items = this.items.map((item) =>
      item.id === id ? { ...item, status, detail } : item,
    );
  }

  clearItems() {
    this.items = [];
  }

  private getStatusIcon(status: ProgressItem["status"]) {
    switch (status) {
      case "pending":
        return html``;
      case "in_progress":
        return html`<sp-progress-circle
          class="spinner-mini"
          size="s"
          label="Step in progress"
        ></sp-progress-circle>`;
      case "completed":
        return html`
          <svg viewBox="0 0 20 20" fill="currentColor">
            <path
              fill-rule="evenodd"
              d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
              clip-rule="evenodd"
            />
          </svg>
        `;
      case "error":
        return html`
          <svg viewBox="0 0 20 20" fill="currentColor">
            <path
              fill-rule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clip-rule="evenodd"
            />
          </svg>
        `;
    }
  }

  private getProgressSummary() {
    const completed = this.items.filter(
      (item) => item.status === "completed",
    ).length;
    const total = this.items.length;
    const inProgress = this.items.filter(
      (item) => item.status === "in_progress",
    ).length;

    if (inProgress > 0) {
        return `${completed} of ${total} complete`;
    }
    return total > 0 ? `${completed} of ${total} complete` : "";
  }

  render() {
    return html`
      ${this.items.length > 0
        ? html`
            <div class="progress-label">
              <span class="progress-label-text">${this.title}</span>
              <span class="progress-summary">${this.getProgressSummary()}</span>
            </div>
          `
        : ""}

      <div class="progress-list">
        ${this.items.length === 0
          ? html`<div class="empty-state">
              Execution steps will appear here when a question is running.
            </div>`
          : this.items.map(
              (item) => html`
                <div class="progress-item ${item.status}">
                  <div class="progress-icon ${item.status}">
                    ${this.getStatusIcon(item.status)}
                  </div>
                  <div class="progress-content">
                    <p class="progress-text">${item.text}</p>
                    ${item.detail
                      ? html`<p class="progress-detail">${item.detail}</p>`
                      : ""}
                  </div>
                </div>
              `,
            )}
      </div>
    `;
  }
}
