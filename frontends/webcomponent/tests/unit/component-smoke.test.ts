import { describe, expect, it } from "vitest";
import { VannaStatusBar } from "../../src/components/vanna-status-bar";
import { VegaLiteChart } from "../../src/components/vega-lite-chart";

describe("web component smoke", () => {
  it("registers and renders a basic component", async () => {
    const element = document.createElement(
      "vanna-status-bar",
    ) as VannaStatusBar;
    element.status = "success";
    element.message = "Frontend ready";
    document.body.append(element);

    await element.updateComplete;

    expect(customElements.get("vanna-status-bar")).toBe(VannaStatusBar);
    expect(element.shadowRoot?.querySelector(".status-text")?.textContent).toBe(
      "Frontend ready",
    );
    expect(
      element.shadowRoot
        ?.querySelector(".status-content")
        ?.getAttribute("role"),
    ).toBe("status");

    element.remove();
  });

  it("keeps HTMLElement.dataset separate from Vega chart data", async () => {
    const element = document.createElement("vega-lite-chart") as VegaLiteChart;
    element.chartData = [{ category: "A", value: 1 }];
    document.body.append(element);

    await element.updateComplete;

    expect(element.dataset).toBeDefined();
    expect(element.chartData).toEqual([{ category: "A", value: 1 }]);

    element.remove();
  });
});
