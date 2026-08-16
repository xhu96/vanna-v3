import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";
import { vannaDesignTokens } from "../styles/vanna-design-tokens.js";
import embed from "vega-embed";
import {
  sanitizeVegaData,
  sanitizeVegaSpec,
} from "../security/content-security.js";

const blockExternalResource = async (uri: string): Promise<string> => {
  throw new Error(`External Vega resource blocked: ${uri}`);
};

const staticOnlyLoader = Object.freeze({
  file: blockExternalResource,
  http: blockExternalResource,
  load: blockExternalResource,
  sanitize: async (uri: string): Promise<{ href: string }> => {
    throw new Error(`External Vega link blocked: ${uri}`);
  },
});

const SAFE_VEGA_EMBED_OPTIONS = Object.freeze({
  actions: false,
  ast: true,
  hover: false,
  loader: staticOnlyLoader,
  renderer: "svg" as const,
  tooltip: false,
});

@customElement("vega-lite-chart")
export class VegaLiteChart extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        width: 100%;
        min-height: 250px;
        font-family: var(--vanna-font-family-default);
      }

      .chart-root {
        width: 100%;
      }

      .chart-root :where(svg, canvas) {
        max-width: 100%;
      }

      .error {
        color: var(--vanna-accent-negative-default);
        font-style: italic;
        padding: var(--vanna-space-4);
      }

      @media (max-width: 600px) {
        :host {
          min-height: 230px;
        }
      }
    `,
  ];

  @property({ type: Object }) spec: Record<string, any> = {};
  @property({ type: Array, attribute: "chart-data" }) chartData: Array<
    Record<string, any>
  > = [];
  @property({ type: String }) error = "";

  firstUpdated() {
    this.renderChart();
  }

  updated(changed: Map<string | number | symbol, unknown>) {
    if (changed.has("spec") || changed.has("chartData")) {
      this.renderChart();
    }
  }

  private async renderChart() {
    const el = this.shadowRoot?.querySelector(
      ".chart-root",
    ) as HTMLElement | null;
    if (!el) return;
    if (!this.spec || Object.keys(this.spec).length === 0) return;

    try {
      const safeSpec = sanitizeVegaSpec(this.spec);
      const viewSpec = {
        ...safeSpec,
        data: {
          ...(safeSpec.data &&
          typeof safeSpec.data === "object" &&
          !Array.isArray(safeSpec.data)
            ? safeSpec.data
            : {}),
          values: sanitizeVegaData(this.chartData || []),
        },
      };
      await embed(el, viewSpec as unknown as Parameters<typeof embed>[1], {
        ...SAFE_VEGA_EMBED_OPTIONS,
      });
      this.error = "";
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : "Failed to render Vega-Lite chart";
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
    "vega-lite-chart": VegaLiteChart;
  }
}
