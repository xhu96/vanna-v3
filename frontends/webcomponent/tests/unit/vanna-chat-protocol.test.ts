import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  embed: vi.fn().mockResolvedValue({}),
  newPlot: vi.fn().mockResolvedValue(undefined),
  relayout: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("plotly.js-dist-min", () => ({
  default: { newPlot: mocks.newPlot, relayout: mocks.relayout },
}));
vi.mock("vega-embed", () => ({ default: mocks.embed }));

// Happy DOM does not implement the delegated focus and form internals used by
// Spectrum. Real component behavior is covered by the Playwright integration
// test; this lightweight stand-in keeps these tests focused on Vanna protocol
// and composer state.
vi.mock("@spectrum-web-components/textfield/sp-textfield.js", () => {
  if (!customElements.get("sp-textfield")) {
    customElements.define(
      "sp-textfield",
      class extends HTMLElement {
        disabled = false;
        placeholder = "";
        value = "";
      },
    );
  }
  return {};
});

vi.mock("@spectrum-web-components/theme/sp-theme.js", () => {
  if (!customElements.get("sp-theme")) {
    customElements.define(
      "sp-theme",
      class extends HTMLElement {
        color = "";
        scale = "";
        system = "";
      },
    );
  }
  return {};
});
vi.mock("@spectrum-web-components/theme/spectrum-two/scale-medium.js", () => ({}));
vi.mock("@spectrum-web-components/theme/spectrum-two/theme-dark.js", () => ({}));
vi.mock("@spectrum-web-components/theme/spectrum-two/theme-light.js", () => ({}));

import { VannaChat } from "../../src/components/vanna-chat";

const encoder = new TextEncoder();

function event(
  eventType: string,
  payload: Record<string, unknown>,
  sequence = 0,
) {
  return {
    event_version: "v3",
    event_type: eventType,
    event_id: `evt_${sequence}`,
    sequence,
    conversation_id: "conv_1",
    request_id: "req_1",
    timestamp: "2026-08-11T12:00:00.000Z",
    payload,
  };
}

function frame(value: ReturnType<typeof event>): string {
  return `id: ${value.event_id}\nevent: ${value.event_type}\ndata: ${JSON.stringify(value)}\n\n`;
}

function lineagePayload() {
  return {
    evidence: {
      schema_version: null,
      schema_snapshot_id: null,
      schema_hash: null,
      schema_drifted: false,
      semantic: { coverage: "not_applicable", metric_names: [] },
      retrieved_sources: [],
      tool_calls: [],
      sql_executions: [],
      validation_checks: [{ name: "agent_lineage_emitted", passed: false }],
      confidence: { tier: "Low", signals: ["missing_agent_lineage"] },
    },
  };
}

function streamResponse(body: string): Response {
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        if (body) controller.enqueue(encoder.encode(body));
        controller.close();
      },
    }),
    { status: 200 },
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

describe("<vanna-chat> protocol selection", () => {
  it("keeps the guided empty state visible and makes prompt starters keyboard-operable", async () => {
    const chat = document.createElement("vanna-chat") as VannaChat;
    chat.apiVersion = "v3";
    document.body.append(chat);
    await chat.updateComplete;
    await new Promise((resolve) => setTimeout(resolve, 0));

    const emptyState = chat.shadowRoot?.querySelector(
      "#empty-state",
    ) as HTMLElement;
    const suggestion = chat.shadowRoot?.querySelector(
      ".prompt-suggestion",
    ) as HTMLButtonElement;
    expect(emptyState.style.display).not.toBe("none");
    expect(suggestion.disabled).toBe(false);
    suggestion.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await chat.updateComplete;
    const input = chat.shadowRoot?.querySelector(
      ".message-input",
    ) as HTMLTextAreaElement;
    const send = chat.shadowRoot?.querySelector(
      ".send-button",
    ) as HTMLButtonElement;
    expect(input.value).toBe("Compare revenue by region");
    expect(send.disabled).toBe(false);
  });

  it("registers and renders message rows when imported standalone", async () => {
    const chat = document.createElement("vanna-chat") as VannaChat;
    chat.apiVersion = "v3";
    document.body.append(chat);
    await chat.updateComplete;

    chat.addMessage("A visible governed answer", "assistant");
    await new Promise((resolve) => setTimeout(resolve, 0));

    const message = chat.shadowRoot?.querySelector("vanna-message");
    expect(customElements.get("vanna-message")).toBeDefined();
    expect(
      message?.shadowRoot?.querySelector(".message-content")?.textContent,
    ).toBe("A visible governed answer");
  });

  it("defaults to V2 and derives V3 endpoints only when explicitly selected", () => {
    const chat = new VannaChat();

    expect(chat.apiVersion).toBe("v2");
    expect(chat.getApiClient().getEndpoints()).toMatchObject({
      sse: "/api/vanna/v2/chat_sse",
      poll: "/api/vanna/v2/chat_poll",
    });

    chat.apiVersion = "v3";
    expect(chat.getApiClient().getEndpoints()).toMatchObject({
      sse: "/api/vanna/v3/chat/events",
      poll: "/api/vanna/v3/chat/poll",
    });
  });

  it('maps api-version="v3" and preserves authentication headers across clients', async () => {
    const chat = document.createElement("vanna-chat") as VannaChat;
    chat.setAttribute("api-version", "v3");
    chat.setCustomHeaders({ Authorization: "Bearer secret" });
    document.body.append(chat);
    await chat.updateComplete;

    expect(chat.apiVersion).toBe("v3");
    expect(chat.getApiClient().getCustomHeaders()).toEqual({
      Authorization: "Bearer secret",
    });
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });

  it("dispatches validated V3 events and normalizes non-terminal content", async () => {
    const body =
      frame(
        event("assistant_text", { text: "Revenue increased.", delta: false }),
      ) +
      frame(event("lineage", lineagePayload(), 1)) +
      frame(event("done", { status: "completed", event_count: 3 }, 2));
    vi.mocked(fetch).mockResolvedValue(streamResponse(body));
    const chat = document.createElement("vanna-chat") as VannaChat;
    chat.apiVersion = "v3";
    document.body.append(chat);
    await chat.updateComplete;
    const received: string[] = [];
    chat.addEventListener("v3-event-received", (rawEvent) => {
      received.push((rawEvent as CustomEvent).detail.event.event_type);
    });

    expect(await chat.sendMessage("Show revenue")).toBe(true);

    expect(received).toEqual(["assistant_text", "lineage", "done"]);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/vanna/v3/chat/events");
  });

  it("uses poll only when selected explicitly", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          event_version: "v3",
          conversation_id: "conv_1",
          request_id: "req_1",
          events: [event("lineage", lineagePayload())],
          terminal_event: event(
            "done",
            { status: "completed", event_count: 2 },
            1,
          ),
        }),
        { status: 200 },
      ),
    );
    const chat = new VannaChat();
    chat.apiVersion = "v3";
    chat.transport = "poll";

    expect(await chat.sendMessage("Show revenue")).toBe(true);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/vanna/v3/chat/poll");
  });

  it("never replays an accepted SSE request through poll after stream failure", async () => {
    vi.mocked(fetch).mockResolvedValue(streamResponse(""));
    const chat = new VannaChat();
    chat.apiVersion = "v3";

    expect(await chat.sendMessage("Show revenue")).toBe(false);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/vanna/v3/chat/events");
  });
});
