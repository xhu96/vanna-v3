import { LitElement, html, css } from "lit";
import { customElement, property } from "lit/decorators.js";
import { vannaDesignTokens } from "../styles/vanna-design-tokens.js";
import Plotly from "plotly.js-dist-min";
import {
  buildSafePlotlyConfig,
  sanitizePlotlyData,
  sanitizePlotlyValue,
} from "../security/content-security.js";

export interface PlotlyData {
  x?: any[];
  y?: any[];
  type?: any;
  mode?: any;
  name?: string;
  marker?: any;
  line?: any;
  [key: string]: any;
}

export interface PlotlyLayout {
  title?: any;
  xaxis?: any;
  yaxis?: any;
  font?: any;
  paper_bgcolor?: string;
  plot_bgcolor?: string;
  margin?: any;
  showlegend?: boolean;
  height?: number;
  width?: number;
  modebar?: any;
  [key: string]: any;
}

@customElement("plotly-chart")
export class PlotlyChart extends LitElement {
  static styles = [
    vannaDesignTokens,
    css`
      :host {
        display: block;
        font-family: var(--vanna-font-family-default);
        width: 100%;
        height: 100%;
      }

      .plotly-div {
        width: 100%;
        min-height: 280px;
      }

      /* Plotly layering fix for Shadow DOM */
      .plotly-div,
      .plotly-div .js-plotly-plot,
      .plotly-div .plot-container,
      .plotly-div .svg-container {
        position: relative;
        width: 100%;
        height: 100%;
      }

      .plotly-div svg.main-svg {
        position: absolute;
        top: 0;
        left: 0;
      }

      .plotly-div .hoverlayer {
        pointer-events: none;
      }

      .error-message {
        padding: var(--vanna-space-4);
        color: var(--vanna-accent-negative-default);
        text-align: center;
        font-style: italic;
      }

      .loading-message {
        padding: var(--vanna-space-4);
        color: var(--vanna-foreground-dimmer);
        text-align: center;
        font-style: italic;
      }

      @media (max-width: 600px) {
        .plotly-div {
          min-height: 240px;
        }
      }
    `,
  ];

  @property({ type: Array }) data: PlotlyData[] = [];
  @property({ type: Object }) layout: PlotlyLayout = {};
  @property({ type: Object }) config = {};
  @property({ type: Boolean }) loading = false;
  @property() error = "";
  @property() theme: "light" | "dark" = "dark";

  private plotlyDiv?: HTMLElement;
  private resizeObserver?: ResizeObserver;

  firstUpdated() {
    this.plotlyDiv = this.shadowRoot?.querySelector(
      ".plotly-div",
    ) as HTMLElement;
    this._renderChart();
    this._setupResizeObserver();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.resizeObserver?.disconnect();
  }

  private _setupResizeObserver() {
    if (!this.plotlyDiv) return;

    this.resizeObserver = new ResizeObserver(() => {
      if (this.plotlyDiv && this.data.length > 0) {
        const width = this.plotlyDiv.offsetWidth;
        Plotly.relayout(this.plotlyDiv, { width });
      }
    });

    this.resizeObserver.observe(this.plotlyDiv);
  }

  updated(changedProperties: Map<string | number | symbol, unknown>) {
    if (
      changedProperties.has("config") ||
      changedProperties.has("data") ||
      changedProperties.has("layout") ||
      changedProperties.has("theme")
    ) {
      this._renderChart();
    }
  }

  private _getDefaultLayout(): PlotlyLayout {
    const isDark = this.theme === "dark";

    const requestedLayout = sanitizePlotlyValue(this.layout || {});

    const mergedLayout = {
      ...requestedLayout,
      // Only add font/modebar if not already set by backend
      font: requestedLayout.font || {
        family:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
        color: isDark ? "#edf5f3" : "#49636b",
        size: 11,
      },
      modebar: requestedLayout.modebar || {
        bgcolor: isDark ? "rgba(19, 25, 28, 0.92)" : "rgba(255, 255, 255, 0.94)",
        color: isDark ? "#b2c5c3" : "#71868b",
        activecolor: isDark ? "#f2f5f5" : "#182125",
        orientation: "h",
      },
      // Set explicit dimensions for Shadow DOM compatibility
      autosize: false,
      width: requestedLayout.width || undefined,
      height: requestedLayout.height || 280,
    };

    // If backend didn't set background colors, use transparent
    if (!requestedLayout.paper_bgcolor) {
      mergedLayout.paper_bgcolor = "transparent";
    }
    if (!requestedLayout.plot_bgcolor) {
      mergedLayout.plot_bgcolor = "transparent";
    }

    return mergedLayout;
  }

  private _getDefaultConfig() {
    return buildSafePlotlyConfig(this.config);
  }

  private async _renderChart() {
    if (
      !this.plotlyDiv ||
      this.loading ||
      this.error ||
      this.data.length === 0
    ) {
      return;
    }

    try {
      const layout = this._getDefaultLayout();
      const config = this._getDefaultConfig();

      const data = sanitizePlotlyData(this.data);
      await Plotly.newPlot(this.plotlyDiv, data, layout, config);
    } catch (err) {
      this.error =
        err instanceof Error ? err.message : "Failed to render chart";
    }
  }

  render() {
    return html`
      ${this.loading
        ? html` <div class="loading-message">Loading chart...</div> `
        : this.error
          ? html` <div class="error-message">Error: ${this.error}</div> `
          : html` <div class="plotly-div"></div> `}
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "plotly-chart": PlotlyChart;
  }
}
