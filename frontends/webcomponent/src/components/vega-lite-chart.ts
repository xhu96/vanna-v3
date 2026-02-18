import { LitElement, html, css } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { vannaDesignTokens } from '../styles/vanna-design-tokens.js';
import embed from 'vega-embed';

@customElement('vega-lite-chart')
export class VegaLiteChart extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        width: 100%;
        min-height: 360px;
      }

      .chart-root {
        width: 100%;
      }

      .error {
        color: var(--vanna-accent-negative-default);
        font-style: italic;
        padding: var(--vanna-space-4);
      }
    `
  ];

  @property({ type: Object }) spec: Record<string, any> = {};
  @property({ type: Array }) dataset: Array<Record<string, any>> = [];
  @property({ type: String }) error = '';

  firstUpdated() {
    this.renderChart();
  }

  updated(changed: Map<string | number | symbol, unknown>) {
    if (changed.has('spec') || changed.has('dataset')) {
      this.renderChart();
    }
  }

  private async renderChart() {
    const el = this.shadowRoot?.querySelector('.chart-root') as HTMLElement | null;
    if (!el) return;
    if (!this.spec || Object.keys(this.spec).length === 0) return;

    try {
      const viewSpec = {
        ...this.spec,
        data: {
          ...(this.spec.data || {}),
          values: this.dataset || [],
        },
      };
      await embed(el, viewSpec, {
        actions: false,
        renderer: 'svg',
      });
      this.error = '';
    } catch (err) {
      this.error = err instanceof Error ? err.message : 'Failed to render Vega-Lite chart';
    }
  }

  render() {
    return html`
      ${this.error ? html`<div class="error">${this.error}</div>` : null}
      <div class="chart-root"></div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'vega-lite-chart': VegaLiteChart;
  }
}

