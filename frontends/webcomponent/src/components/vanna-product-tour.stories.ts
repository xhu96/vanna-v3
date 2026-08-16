import type { Meta, StoryObj } from "@storybook/web-components";
import { html } from "lit";
import "./vanna-chat";

const meta: Meta = {
  title: "Product/Vanna 3 Workbench",
  component: "vanna-chat",
  parameters: {
    layout: "fullscreen",
    controls: { disable: true },
  },
};

export default meta;
type Story = StoryObj;

const revenueData = [
  { region: "North America", revenue: 14.8, growth: 18.2 },
  { region: "Europe", revenue: 12.6, growth: 11.4 },
  { region: "Asia Pacific", revenue: 11.2, growth: 24.7 },
  { region: "Latin America", revenue: 9.6, growth: 8.9 },
];

const revenueChart = {
  format: "vega-lite",
  schema_version: "1.0",
  spec: {
    width: "container",
    height: 206,
    background: "#ffffff",
    mark: {
      type: "bar",
      color: "#087b72",
      cornerRadiusTopLeft: 2,
      cornerRadiusTopRight: 2,
    },
    encoding: {
      x: {
        field: "region",
        type: "nominal",
        sort: "-y",
        axis: {
          title: null,
          labelAngle: 0,
          labelColor: "#566168",
          labelFontSize: 10,
          labelLimit: 126,
          tickSize: 0,
          domainColor: "#d7dcdf",
        },
      },
      y: {
        field: "revenue",
        type: "quantitative",
        axis: {
          title: "Revenue ($M)",
          titleColor: "#737e84",
          titleFontSize: 10,
          labelColor: "#737e84",
          labelFontSize: 9,
          gridColor: "#e5e8ea",
          domain: false,
          tickSize: 0,
        },
      },
    },
    config: {
      view: { stroke: null },
      axis: {
        labelFont: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
        titleFont: "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
      },
    },
  },
  dataset: revenueData,
  metadata: {
    title: "Revenue by region",
    row_count: revenueData.length,
  },
};

type TourChat = HTMLElement & {
  dataset: DOMStringMap;
  addMessage(content: string, type: "user" | "assistant"): void;
  getProgressTracker(): {
    addItem(text: string, detail?: string, id?: string): string;
    updateItem(
      id: string,
      status: "pending" | "in_progress" | "completed" | "error",
      detail?: string,
    ): void;
  } | null;
  setStatus(
    status: "idle" | "working" | "error" | "success",
    message: string,
    detail?: string,
  ): void;
  componentManager?: {
    processUpdate(update: Record<string, unknown>): void;
  };
};

function createComponent(
  chat: TourChat,
  id: string,
  type: string,
  data: Record<string, unknown>,
) {
  chat.componentManager?.processUpdate({
    operation: "create",
    target_id: id,
    component: {
      id,
      type,
      lifecycle: "create",
      data,
      children: [],
      timestamp: new Date().toISOString(),
      visible: true,
      interactive: false,
    },
    timestamp: new Date().toISOString(),
  });
}

function addTable(chat: TourChat) {
  createComponent(chat, "tour-revenue-table", "dataframe", {
    title: "Query result",
    description: "Illustrative FY 2026 revenue by region",
    data: revenueData,
    columns: ["region", "revenue", "growth"],
    column_types: {
      region: "string",
      revenue: "number",
      growth: "number",
    },
    row_count: revenueData.length,
    column_count: 3,
    searchable: false,
    filterable: false,
    exportable: false,
    sortable: true,
    compact: true,
  });
}

function addChart(chat: TourChat) {
  createComponent(chat, "tour-revenue-chart", "chart", {
    title: "Revenue by region, FY 2026",
    data: revenueChart,
  });
}

function getChat() {
  return document.querySelector("#vanna-product-tour") as TourChat | null;
}

function addVerificationSteps(chat: TourChat) {
  const tracker = chat.getProgressTracker();
  if (!tracker) return null;
  return {
    tracker,
    semantic: tracker.addItem(
      "Semantic metric resolved",
      "revenue / dbt Semantic Layer",
      "tour-semantic",
    ),
    policy: tracker.addItem(
      "Tenant policy applied",
      "read-only scope / all regions",
      "tour-policy",
    ),
    query: tracker.addItem(
      "Governed query executed",
      "waiting for result",
      "tour-query",
    ),
    validation: tracker.addItem(
      "Result validated",
      "pending checks",
      "tour-validation",
    ),
    lineage: tracker.addItem(
      "Lineage attached",
      "pending evidence",
      "tour-lineage",
    ),
  };
}

function mountCompletedTour() {
  window.setTimeout(() => {
    const chat = getChat();
    if (!chat || chat.dataset.tourInitialized) return;
    chat.dataset.tourInitialized = "true";

    chat.addMessage(
      "Compare FY 2026 revenue by region and explain the largest change.",
      "user",
    );
    chat.addMessage(
      "Asia Pacific is growing fastest at 24.7%. North America remains the largest region at $14.8M, bringing total revenue to $48.2M.",
      "assistant",
    );
    addChart(chat);

    const steps = addVerificationSteps(chat);
    if (!steps) return;
    steps.tracker.updateItem(
      steps.semantic,
      "completed",
      "revenue / dbt Semantic Layer",
    );
    steps.tracker.updateItem(
      steps.policy,
      "completed",
      "read-only scope / all regions",
    );
    steps.tracker.updateItem(steps.query, "completed", "642 ms / 4 rows");
    steps.tracker.updateItem(
      steps.validation,
      "completed",
      "row count + reconciliation checks",
    );
    steps.tracker.updateItem(
      steps.lineage,
      "completed",
      "schema v184 / High confidence",
    );
    chat.setStatus("success", "Answer verified", "High confidence");
    window.setTimeout(() => {
      const messages = chat.shadowRoot?.querySelector(".chat-messages");
      if (messages && window.innerWidth > 640) messages.scrollTop = 0;
    }, 300);
  }, 120);
}

function mountAnimatedTour() {
  window.setTimeout(() => {
    const chat = getChat();
    if (!chat || chat.dataset.tourInitialized) return;
    chat.dataset.tourInitialized = "true";

    window.setTimeout(() => {
      chat.addMessage(
        "Compare FY 2026 revenue by region and explain the largest change.",
        "user",
      );
      chat.setStatus("working", "Resolving semantic metric", "revenue");
      const steps = addVerificationSteps(chat);
      if (!steps) return;
      steps.tracker.updateItem(
        steps.semantic,
        "in_progress",
        "matching governed definition",
      );

      window.setTimeout(() => {
        steps.tracker.updateItem(
          steps.semantic,
          "completed",
          "revenue / dbt Semantic Layer",
        );
        steps.tracker.updateItem(
          steps.policy,
          "in_progress",
          "checking tenant scope",
        );
        chat.setStatus("working", "Applying query policy", "tenant scope");
      }, 1500);

      window.setTimeout(() => {
        steps.tracker.updateItem(
          steps.policy,
          "completed",
          "read-only scope / all regions",
        );
        steps.tracker.updateItem(
          steps.query,
          "in_progress",
          "Postgres / read only",
        );
        chat.setStatus("working", "Running governed query", "Postgres");
      }, 2900);

      window.setTimeout(() => {
        steps.tracker.updateItem(steps.query, "completed", "642 ms / 4 rows");
        steps.tracker.updateItem(
          steps.validation,
          "in_progress",
          "reconciling totals",
        );
        addTable(chat);
        chat.setStatus("working", "Validating result", "2 checks");
      }, 4400);

      window.setTimeout(() => {
        chat.addMessage(
          "Asia Pacific is growing fastest at 24.7%. North America remains the largest region at $14.8M, bringing total revenue to $48.2M.",
          "assistant",
        );
        addChart(chat);
      }, 6400);

      window.setTimeout(() => {
        steps.tracker.updateItem(
          steps.validation,
          "completed",
          "row count + reconciliation checks",
        );
        steps.tracker.updateItem(
          steps.lineage,
          "completed",
          "schema v184 / High confidence",
        );
        chat.setStatus("success", "Answer verified", "High confidence");
      }, 8500);
    }, 900);
  }, 100);
}

function tourFrame(animated: boolean) {
  animated ? mountAnimatedTour() : mountCompletedTour();
  return html`
    <style>
      html,
      body,
      #storybook-root {
        min-width: 320px;
        min-height: 100%;
        margin: 0;
      }

      .vanna-demo-stage {
        box-sizing: border-box;
        display: grid;
        min-height: 100vh;
        place-items: center;
        padding: clamp(18px, 3vw, 42px);
        background: #eef1f2;
      }

      #vanna-product-tour {
        width: min(1420px, 100%);
      }

      @media (max-width: 640px) {
        .vanna-demo-stage {
          padding: 0;
        }
      }
    </style>
    <main class="vanna-demo-stage">
      <vanna-chat
        id="vanna-product-tour"
        api-version="v3"
        title="Revenue analysis"
        subtitle="Demo workspace / FY 2026 planning"
        placeholder="Ask a follow-up question"
        .allowMinimize=${false}
        .showProgress=${true}
        theme="light"
      ></vanna-chat>
    </main>
  `;
}

export const ProductOverview: Story = {
  render: () => tourFrame(false),
};

export const ProductTour: Story = {
  render: () => tourFrame(true),
};
