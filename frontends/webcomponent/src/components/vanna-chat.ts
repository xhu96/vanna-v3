import { LitElement, html } from "lit";
import { customElement, property, state } from "lit/decorators.js";
import type { ActionButton } from "@spectrum-web-components/action-button";
import type { Button } from "@spectrum-web-components/button";
import type { Textfield } from "@spectrum-web-components/textfield";
import "@spectrum-web-components/action-button/sp-action-button.js";
import "@spectrum-web-components/button/sp-button.js";
import "@spectrum-web-components/progress-circle/sp-progress-circle.js";
import "@spectrum-web-components/textfield/sp-textfield.js";
import "@spectrum-web-components/theme/sp-theme.js";
import "@spectrum-web-components/theme/spectrum-two/scale-medium.js";
import "@spectrum-web-components/theme/spectrum-two/theme-dark.js";
import "@spectrum-web-components/theme/spectrum-two/theme-light.js";
import { vannaChatStyles } from "../styles/vanna-chat-styles.js";
import { vannaDesignTokens } from "../styles/vanna-design-tokens.js";
import {
  VannaApiClient,
  type ApiProtocol,
  type ChatRequest,
  type ChatStreamChunk,
} from "../services/api-client.js";
import { normalizeV3Event, type V3ChatEvent } from "../types/events-v3.js";
import { ComponentManager, RichComponent } from "./rich-component-system.js";
import "./vanna-status-bar.js";
import "./vanna-progress-tracker.js";
import "./vanna-message.js";
import "./rich-card.js";
import "./rich-task-list.js";
import "./rich-progress-bar.js";
import "./plotly-chart.js";
import "./vega-lite-chart.js";

@customElement("vanna-chat")
export class VannaChat extends LitElement {
  static styles = [vannaDesignTokens, vannaChatStyles];

  @property() title = "Vanna";
  @property() placeholder = "Ask a question about your data";
  @property({ type: Boolean }) disabled = false;
  @property({ type: Boolean }) showProgress = true;
  @property({ type: Boolean }) allowMinimize = true;
  @property({ reflect: true }) theme = "light";
  @property({ attribute: "api-base" }) apiBaseUrl = "";
  @property({ attribute: "api-version", reflect: true })
  apiVersion: ApiProtocol = "v2";
  @property({ reflect: true }) transport: "sse" | "poll" = "sse";
  @property({ attribute: "sse-endpoint" }) sseEndpoint =
    "/api/vanna/v2/chat_sse";
  @property({ attribute: "ws-endpoint" }) wsEndpoint =
    "/api/vanna/v2/chat_websocket";
  @property({ attribute: "poll-endpoint" }) pollEndpoint =
    "/api/vanna/v2/chat_poll";
  @property() subtitle = "";
  @property() startingState: "normal" | "maximized" | "minimized" = "normal";

  @state() private currentMessage = "";
  @state() private status: "idle" | "working" | "error" | "success" = "idle";
  @state() private statusMessage = "";
  @state() private statusDetail = "";
  private _windowState: "normal" | "maximized" | "minimized" = "normal";

  @property({ reflect: false })
  get windowState() {
    return this._windowState;
  }

  set windowState(value: "normal" | "maximized" | "minimized") {
    const oldValue = this._windowState;
    this._windowState = value;
    this.requestUpdate("windowState", oldValue);
  }

  private apiClient!: VannaApiClient;
  private conversationId: string;
  private componentManager: ComponentManager | null = null;
  private componentObserver: MutationObserver | null = null;
  private suggestionContainer: HTMLElement | null = null;
  private activeRequest: AbortController | null = null;
  private customHeaders: Record<string, string> = {};

  constructor() {
    super();
    // Note: Don't create apiClient here - attributes haven't been set yet!
    // It will be created lazily in getApiClient() or firstUpdated()
    this.conversationId = this.generateId();
  }

  /**
   * Ensure API client is created/updated with current endpoint values
   */
  private ensureApiClient() {
    const v3 = this.apiVersion === "v3";
    const sseEndpoint =
      v3 &&
      this.sseEndpoint === "/api/vanna/v2/chat_sse" &&
      !this.hasAttribute("sse-endpoint")
        ? undefined
        : this.sseEndpoint || undefined;
    const pollEndpoint =
      v3 &&
      this.pollEndpoint === "/api/vanna/v2/chat_poll" &&
      !this.hasAttribute("poll-endpoint")
        ? undefined
        : this.pollEndpoint || undefined;
    const wsEndpoint =
      v3 &&
      this.wsEndpoint === "/api/vanna/v2/chat_websocket" &&
      !this.hasAttribute("ws-endpoint")
        ? undefined
        : this.wsEndpoint || undefined;

    this.apiClient = new VannaApiClient({
      protocol: this.apiVersion,
      baseUrl: this.apiBaseUrl,
      sseEndpoint,
      wsEndpoint,
      pollEndpoint,
      customHeaders: this.customHeaders,
    });
  }

  firstUpdated() {
    // Create API client now that attributes have been set
    this.ensureApiClient();

    // Initialize component manager with rich components container (fallback)
    const richContainer = this.shadowRoot?.querySelector(
      ".rich-components-container",
    ) as HTMLElement;
    if (richContainer) {
      this.componentManager = new ComponentManager(richContainer);

      // Watch for changes in the rich components container to manage empty state
      this.componentObserver = new MutationObserver(() => {
        // Update empty state visibility
        this.updateEmptyState();
      });

      this.componentObserver.observe(richContainer, {
        childList: true,
        subtree: true,
        attributes: false,
      });
    }

    this.suggestionContainer = this.shadowRoot?.querySelector(
      ".prompt-suggestions",
    ) as HTMLElement | null;
    this.suggestionContainer?.addEventListener(
      "click",
      this.handleSuggestionContainerClick,
    );
    this.syncSuggestedPromptState();
    this.syncComposerState();

    // Set initial window state from startingState property
    if (this.startingState !== "normal") {
      this._windowState = this.startingState;
    }

    // Set initial CSS class
    this.classList.add(this._windowState);

    // Starter UI is a V2 compatibility request; V3 chat messages are non-empty.
    if (this.apiVersion === "v2") this.requestStarterUI();
  }

  /**
   * Request starter UI (buttons, welcome messages) from backend
   */
  private async requestStarterUI(): Promise<void> {
    try {
      const request = {
        message: "",
        conversation_id: this.conversationId,
        request_id: this.generateId(),
        metadata: {
          starter_ui_request: true,
        },
      };

      // Stream the starter UI response
      await this.handleStreamingResponse(request);
    } catch {
      // Fail silently - starter UI is optional
    }
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.cancelCurrentRequest();

    // Clean up mutation observer
    if (this.componentObserver) {
      this.componentObserver.disconnect();
      this.componentObserver = null;
    }
    this.suggestionContainer?.removeEventListener(
      "click",
      this.handleSuggestionContainerClick,
    );
    this.suggestionContainer = null;
  }

  updated(changedProperties: Map<string, any>) {
    super.updated(changedProperties);

    // Update host classes based on window state
    if (changedProperties.has("windowState")) {
      this.classList.remove("normal", "maximized", "minimized");
      this.classList.add(this._windowState);
    }

    if (
      changedProperties.has("apiVersion") ||
      changedProperties.has("apiBaseUrl") ||
      changedProperties.has("sseEndpoint") ||
      changedProperties.has("wsEndpoint") ||
      changedProperties.has("pollEndpoint")
    ) {
      this.ensureApiClient();
    }

    if (changedProperties.has("disabled")) {
      this.syncSuggestedPromptState();
      this.syncComposerState();
    }
  }

  private handleInput(e: Event) {
    const input = e.target as Textfield;
    this.currentMessage = input.value;
    this.syncComposerState();
  }

  private applySuggestedPrompt(prompt: string) {
    if (this.disabled) return;

    this.currentMessage = prompt;
    const input = this.shadowRoot?.querySelector(
      ".message-input",
    ) as Textfield | null;
    if (input) {
      input.value = prompt;
      input.focus();
    }
    this.syncComposerState();
  }

  private readonly handleSuggestionContainerClick = (event: Event) => {
    const target = event.target as Element | null;
    const button = target?.closest<ActionButton>(".prompt-suggestion");
    if (!button || !this.suggestionContainer?.contains(button)) return;
    this.applySuggestedPrompt(button.dataset.prompt || "");
  };

  private syncSuggestedPromptState() {
    this.suggestionContainer
      ?.querySelectorAll<ActionButton>(".prompt-suggestion")
      .forEach((button) => {
        button.disabled = this.disabled;
        button.setAttribute("aria-disabled", String(this.disabled));
      });
  }

  private syncComposerState() {
    const input = this.shadowRoot?.querySelector(
      ".message-input",
    ) as Textfield | null;
    const send = this.shadowRoot?.querySelector(
      ".send-button",
    ) as Button | null;
    if (input) input.disabled = this.disabled;
    if (send) send.disabled = this.disabled || !this.currentMessage.trim();
  }

  private handleKeyPress(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      this.sendMessage();
    }
  }

  /**
   * Send a message programmatically (can be called from buttons or external code)
   * Returns a Promise that resolves with success status
   */
  sendMessage(messageText?: string): Promise<boolean> {
    // Use provided message or fall back to current input
    // Check if messageText is actually a string (not an event object)
    const textToSend =
      typeof messageText === "string" ? messageText : this.currentMessage;

    if (!textToSend.trim() || this.disabled) {
      return Promise.resolve(false);
    }

    return this._sendMessageInternal(textToSend);
  }

  private async _sendMessageInternal(messageText: string): Promise<boolean> {
    // Auto-maximize window when user sends a message (if not already maximized or minimized)
    if (this.windowState !== "maximized" && this.windowState !== "minimized") {
      this.maximizeWindow();
    }

    // Create user message as a rich component and send to ComponentManager
    const userRichComponent: RichComponent = {
      id: `user-message-${Date.now()}`,
      type: "user-message",
      lifecycle: "create",
      data: {
        content: messageText,
        sender: "user",
      },
      children: [],
      timestamp: new Date().toISOString(),
      visible: true,
      interactive: false,
    };

    // Add user message to ComponentManager for chronological ordering
    if (this.componentManager) {
      const update = {
        operation: "create" as const,
        target_id: userRichComponent.id,
        component: userRichComponent,
        timestamp: userRichComponent.timestamp,
      };
      this.componentManager.processUpdate(update);
    }

    // Update empty state after a brief delay to let ComponentManager render
    setTimeout(() => this.updateEmptyState(), 0);

    // Update the view
    this.requestUpdate();

    // Update status to working (initial frontend status before backend responds)
    this.setStatus("working", "Sending message...", "");

    // Clear input only if we're sending from the input field
    if (messageText === this.currentMessage) {
      this.currentMessage = "";
      const input = this.shadowRoot?.querySelector(
        ".message-input",
      ) as Textfield;
      if (input) {
        input.value = "";
      }
      this.syncComposerState();
    }

    // Dispatch event for external listeners
    this.dispatchEvent(
      new CustomEvent("message-sent", {
        detail: { message: { content: messageText, type: "user" } },
        bubbles: true,
        composed: true,
      }),
    );

    try {
      // Create the request
      const request = {
        message: messageText,
        conversation_id: this.conversationId,
        request_id: this.generateId(),
        metadata: {},
      };

      // Stream the response
      await this.handleStreamingResponse(request);
      return true; // Success
    } catch (error) {
      this.setStatus(
        "error",
        "Failed to send message",
        error instanceof Error ? error.message : "Unknown error",
      );

      // Add error message
      this.addMessage(
        `Sorry, I encountered an error: ${error instanceof Error ? error.message : "Unknown error"}`,
        "assistant",
      );
      return false; // Failure
    }
  }

  private minimizeWindow(e?: Event) {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    this.windowState = "minimized";
    this.dispatchEvent(
      new CustomEvent("window-state-changed", {
        detail: { state: "minimized" },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private maximizeWindow(e?: Event) {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    this.windowState = "maximized";
    this.dispatchEvent(
      new CustomEvent("window-state-changed", {
        detail: { state: "maximized" },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private restoreWindow(e?: Event) {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    this.windowState = "normal";
    this.dispatchEvent(
      new CustomEvent("window-state-changed", {
        detail: { state: "normal" },
        bubbles: true,
        composed: true,
      }),
    );
  }

  addMessage(content: string, type: "user" | "assistant") {
    // Create message as a rich component and send to ComponentManager
    const richComponent: RichComponent = {
      id: `${type}-message-${Date.now()}`,
      type: `${type}-message`,
      lifecycle: "create",
      data: {
        content: content,
        sender: type,
      },
      children: [],
      timestamp: new Date().toISOString(),
      visible: true,
      interactive: false,
    };

    if (this.componentManager) {
      const update = {
        operation: "create" as const,
        target_id: richComponent.id,
        component: richComponent,
        timestamp: richComponent.timestamp,
      };
      this.componentManager.processUpdate(update);
    }
  }

  setStatus(status: typeof this.status, message: string, detail?: string) {
    this.status = status;
    this.statusMessage = message;
    this.statusDetail = detail || "";
  }

  clearStatus() {
    this.statusMessage = "";
    this.statusDetail = "";
    this.status = "idle";
  }

  getProgressTracker(): HTMLElement | null {
    return this.shadowRoot?.querySelector("vanna-progress-tracker") || null;
  }

  private async handleStreamingResponse(request: ChatRequest) {
    if (this.transport !== "sse" && this.transport !== "poll") {
      throw new Error("Unsupported Vanna chat transport");
    }
    this.ensureApiClient();
    this.cancelCurrentRequest();
    const controller = new AbortController();
    this.activeRequest = controller;

    // Note: Status bar updates are now controlled by backend via StatusBarUpdateComponent
    // Frontend only shows initial "Sending message..." status (set in _sendMessageInternal)
    // and handles connection errors below

    try {
      if (this.apiVersion === "v3") {
        const events =
          this.transport === "poll"
            ? await this.apiClient.sendV3Poll(request, {
                signal: controller.signal,
              })
            : null;
        if (events) {
          for (const event of [...events.events, events.terminal_event]) {
            await this.processV3Event(event);
          }
        } else {
          for await (const event of this.apiClient.streamV3Events(request, {
            signal: controller.signal,
          })) {
            await this.processV3Event(event);
          }
        }
      } else if (this.transport === "poll") {
        const response = await this.apiClient.sendPollMessage(request, {
          signal: controller.signal,
        });
        for (const chunk of response.chunks) await this.processChunk(chunk);
      } else {
        for await (const chunk of this.apiClient.streamChat(request, {
          signal: controller.signal,
        })) {
          await this.processChunk(chunk);
        }
      }
    } finally {
      if (this.activeRequest === controller) this.activeRequest = null;
    }
  }

  private async processV3Event(event: V3ChatEvent): Promise<void> {
    this.dispatchEvent(
      new CustomEvent("v3-event-received", {
        detail: { event },
        bubbles: true,
        composed: true,
      }),
    );
    const chunk = normalizeV3Event(event);
    if (chunk) await this.processChunk(chunk);
  }

  private async processChunk(chunk: ChatStreamChunk) {
    // Dispatch chunk event for external listeners
    this.dispatchEvent(
      new CustomEvent("chunk-received", {
        detail: { chunk },
        bubbles: true,
        composed: true,
      }),
    );

    // Handle rich components via ComponentManager
    if (chunk.rich && this.componentManager) {
      if (chunk.rich.id && chunk.rich.lifecycle) {
        // Standard rich component with lifecycle
        const component = chunk.rich as RichComponent;
        const update = {
          operation: chunk.rich.lifecycle as any,
          target_id: chunk.rich.id,
          component: component,
          timestamp: new Date().toISOString(),
        };
        this.componentManager.processUpdate(update);
      } else if (chunk.rich.type === "component_update") {
        // Component update format
        this.componentManager.processUpdate(chunk.rich as any);
      } else {
        // Generic rich component
        const component = chunk.rich as RichComponent;
        const update = {
          operation: "create" as const,
          target_id: component.id || `component-${Date.now()}`,
          component: component,
          timestamp: new Date().toISOString(),
        };
        this.componentManager.processUpdate(update);
      }

      return;
    }

    // Update progress tracker for legacy components (keep for backward compatibility)
    const progressTracker = this.getProgressTracker();
    if (progressTracker && "addStep" in progressTracker) {
      (progressTracker as any).addStep({
        id: `chunk-${Date.now()}`,
        title: this.getChunkTitle(chunk),
        status: "completed",
        timestamp: chunk.timestamp,
      });
    }

    // Handle different chunk types (legacy components)
    const componentType = chunk.rich?.type;
    switch (componentType) {
      case "text":
        // Text chunks are handled in the main loop
        break;

      case "thinking":
        // Legacy: Status bar updates now handled by backend via StatusBarUpdateComponent
        // This case is kept for backward compatibility but doesn't update status
        break;

      case "tool_execution":
        // Legacy: Status bar updates now handled by backend via StatusBarUpdateComponent
        // This case is kept for backward compatibility but doesn't update status
        break;

      case "error":
        throw new Error(chunk.rich.data?.message || "Unknown error from agent");

      default:
      // Unknown V2 component types are intentionally ignored.
    }
  }

  private getChunkTitle(chunk: ChatStreamChunk): string {
    const componentType = chunk.rich?.type;
    switch (componentType) {
      case "text":
        return "Generating response";
      case "thinking":
        return "Thinking";
      case "tool_execution":
        return `Tool: ${chunk.rich.data?.tool_name || "Unknown"}`;
      default:
        return `Processing ${componentType || "component"}`;
    }
  }

  private generateId(): string {
    return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
  }

  /**
   * Update the API base URL and recreate the client
   */
  updateApiBaseUrl(baseUrl: string) {
    this.apiBaseUrl = baseUrl;
    this.ensureApiClient();
  }

  /**
   * Get the API client instance for direct access
   */
  getApiClient(): VannaApiClient {
    this.ensureApiClient();
    return this.apiClient;
  }

  /**
   * Set custom headers for authentication or other purposes
   */
  setCustomHeaders(headers: Record<string, string>) {
    this.customHeaders = { ...headers };
    if (this.apiClient) this.apiClient.setCustomHeaders(headers);
  }

  /** Cancel the current SSE or poll request without replaying it. */
  cancelCurrentRequest(): void {
    this.activeRequest?.abort();
    this.activeRequest = null;
  }

  /**
   * Update empty state visibility based on whether there are components
   */
  private updateEmptyState() {
    const emptyState = this.shadowRoot?.querySelector(
      "#empty-state",
    ) as HTMLElement;
    const richContainer = this.shadowRoot?.querySelector(
      ".rich-components-container",
    ) as HTMLElement;

    if (emptyState && richContainer) {
      // ComponentManager injects a style node; only rendered components count as content.
      const hasContent = Array.from(richContainer.children).some(
        (child) => child.tagName !== "STYLE",
      );
      emptyState.style.display = hasContent ? "none" : "flex";
    }
  }

  /**
   * Update scroll indicator based on scroll position
   */
  private updateScrollIndicator() {
    const messagesContainer = this.shadowRoot?.querySelector(".chat-messages");
    if (!messagesContainer) return;

    // Check if there's content scrolled above
    const hasScrolledContent = messagesContainer.scrollTop > 10;

    // Update scroll indicator class
    messagesContainer.classList.toggle("has-scroll", hasScrolledContent);
  }

  /**
   * Scroll to the top of the last message/component that was added
   * This always scrolls regardless of current scroll position
   */
  scrollToLastMessage() {
    const messagesContainer = this.shadowRoot?.querySelector(".chat-messages");
    const richContainer = this.shadowRoot?.querySelector(
      ".rich-components-container",
    );

    if (!messagesContainer || !richContainer) return;

    // Get the last child element (the most recently added component)
    const lastComponent = richContainer.lastElementChild as HTMLElement;
    if (!lastComponent) return;

    // Scroll so the top of the last component is visible
    lastComponent.scrollIntoView({ behavior: "smooth", block: "start" });

    // Update scroll indicator after scrolling
    setTimeout(() => this.updateScrollIndicator(), 100);
  }

  /**
   * Clear all messages (useful for testing)
   */
  clearMessages() {
    if (this.componentManager) {
      this.componentManager.clear();
    }
    this.updateEmptyState();
    this.requestUpdate();
  }

  /**
   * Add multiple messages at once (useful for testing scrolling)
   */
  addTestMessages(count: number = 10) {
    for (let i = 1; i <= count; i++) {
      setTimeout(() => {
        const type = i % 2 === 0 ? "assistant" : "user";
        const content = `This is test message number ${i}. Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.`;
        this.addMessage(content, type);
      }, i * 100); // Stagger the messages to simulate real timing
    }
  }

  render() {
    return html`
      <sp-theme
        class="spectrum-shell"
        .system=${"spectrum-two"}
        .color=${this.theme === "dark" ? "dark" : "light"}
        .scale=${"medium"}
        lang="en"
      >
      <!-- Minimized icon - shown only when minimized via CSS and allowMinimize is true -->
      ${this.allowMinimize
        ? html`
            <div class="minimized-icon" @click=${this.restoreWindow}>
              <svg
                viewBox="0 0 24 24"
                fill="currentColor"
                width="32"
                height="32"
              >
                <path
                  d="M20 2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h14l4 4V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"
                />
              </svg>
            </div>
          `
        : ""}

      <div class="chat-layout ${this.showProgress ? "" : "compact"}">
        <header class="chat-header">
          <div class="header-top">
            <div class="header-left">
              <div class="chat-avatar" aria-hidden="true">V</div>
              <div class="header-text">
                <div class="workspace-line">
                  <span class="product-name">Vanna</span>
                  <span class="breadcrumb-separator" aria-hidden="true">/</span>
                  <h2 class="chat-title">${this.title}</h2>
                </div>
                <div class="chat-subtitle">
                  ${this.subtitle || "Semantic workspace"}
                </div>
              </div>
            </div>
              <div class="header-top-actions">
                <div class="header-meta" aria-label="Session status">
                  <span class="context-chip">
                  ${this.status === "working"
                    ? html`<sp-progress-circle
                        class="header-progress"
                        size="s"
                        label="Processing request"
                      ></sp-progress-circle>`
                    : html`<span
                        class="context-dot"
                        aria-hidden="true"
                      ></span>`}
                  ${this.status === "working" ? "Working" : "Ready"}
                </span>
                <span class="context-chip protocol"
                  >${this.apiVersion.toUpperCase()}</span
                >
              </div>
              <div class="window-controls">
                ${this.allowMinimize
                  ? html`
                      <sp-action-button
                        class="window-control-btn minimize"
                        quiet
                        size="s"
                        label="Minimize"
                        @click=${this.minimizeWindow}
                      >
                        <svg
                          slot="icon"
                          viewBox="0 0 24 24"
                          fill="none"
                          aria-hidden="true"
                        >
                          <path
                            d="M6 12h12"
                            stroke="currentColor"
                            stroke-width="1.7"
                            stroke-linecap="round"
                          />
                        </svg>
                      </sp-action-button>
                    `
                  : ""}
                ${this.windowState === "maximized"
                  ? html`
                      <sp-action-button
                        class="window-control-btn restore"
                        quiet
                        size="s"
                        label="Restore"
                        @click=${this.restoreWindow}
                      >
                        <svg
                          slot="icon"
                          viewBox="0 0 24 24"
                          fill="none"
                          aria-hidden="true"
                        >
                          <rect
                            x="6"
                            y="8"
                            width="10"
                            height="10"
                            rx="1"
                            stroke="currentColor"
                            stroke-width="1.5"
                          />
                          <path
                            d="M9 8V6h9v9h-2"
                            stroke="currentColor"
                            stroke-width="1.5"
                          />
                        </svg>
                      </sp-action-button>
                    `
                  : html`
                      <sp-action-button
                        class="window-control-btn maximize"
                        quiet
                        size="s"
                        label="Maximize"
                        @click=${this.maximizeWindow}
                      >
                        <svg
                          slot="icon"
                          viewBox="0 0 24 24"
                          fill="none"
                          aria-hidden="true"
                        >
                          <rect
                            x="6"
                            y="6"
                            width="12"
                            height="12"
                            rx="1"
                            stroke="currentColor"
                            stroke-width="1.5"
                          />
                        </svg>
                      </sp-action-button>
                    `}
              </div>
            </div>
          </div>
        </header>

        <div class="workbench-body">
          <main class="chat-main">

          <div class="chat-messages">
            <div class="empty-state" id="empty-state">
              <div class="empty-state-icon">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path
                    d="M5 17V7M5 17H19"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                  />
                  <path
                    d="M8 14L11 10.5L14 12L19 6.5"
                    stroke="currentColor"
                    stroke-width="1.8"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </div>
              <div class="empty-state-text">
                Ask a question about your business data
              </div>
              <div class="empty-state-subtitle">
                Vanna resolves governed metrics, runs read-only queries, and
                keeps the evidence with the answer.
              </div>
              <div class="prompt-suggestions" aria-label="Suggested questions">
                <sp-action-button
                  class="prompt-suggestion"
                  quiet
                  size="m"
                  data-prompt="Compare revenue by region"
                  aria-disabled="false"
                >
                  Compare revenue by region
                </sp-action-button>
                <sp-action-button
                  class="prompt-suggestion"
                  quiet
                  size="m"
                  data-prompt="Explain this month's variance"
                  aria-disabled="false"
                >
                  Explain this month's variance
                </sp-action-button>
                <sp-action-button
                  class="prompt-suggestion"
                  quiet
                  size="m"
                  data-prompt="Show retention by cohort"
                  aria-disabled="false"
                >
                  Show retention by cohort
                </sp-action-button>
              </div>
            </div>

            <div class="rich-components-container"></div>
          </div>

          <div class="chat-input-area">
            <vanna-status-bar
              .status=${this.status}
              .message=${this.statusMessage}
              .detail=${this.statusDetail}
              theme=${this.theme}
            >
            </vanna-status-bar>

            <div class="chat-input-container">
              <sp-textfield
                class="message-input"
                multiline
                grows
                size="m"
                label="Question for Vanna"
                .value=${this.currentMessage}
                .placeholder=${this.placeholder}
                .disabled=${this.disabled}
                @input=${this.handleInput}
                @keydown=${this.handleKeyPress}
                rows="1"
              ></sp-textfield>
              <sp-button
                class="send-button"
                variant="accent"
                treatment="fill"
                size="m"
                .disabled=${this.disabled || !this.currentMessage.trim()}
                @click=${() => this.sendMessage()}
              >
                <svg
                  slot="icon"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
                </svg>
                <span class="send-label">Ask Vanna</span>
              </sp-button>
            </div>
            <div class="input-meta">
              <span class="input-security">
                <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path
                    d="M4.5 7V5.5a3.5 3.5 0 117 0V7M3 7h10v7H3V7z"
                    stroke="currentColor"
                    stroke-width="1.4"
                    stroke-linejoin="round"
                  />
                </svg>
                Governed query path
              </span>
              <span class="input-shortcut"
                >Enter to send / Shift + Enter for a new line</span
              >
            </div>
          </div>
          </main>

          ${this.showProgress
            ? html`
              <aside class="sidebar" aria-label="Answer evidence">
                <div class="sidebar-heading">
                  <h3 class="sidebar-title">Evidence</h3>
                  <span class="evidence-state"
                    >${this.status === "working" ? "Updating" : "Attached"}</span
                  >
                </div>
                <vanna-progress-tracker
                  title="Verification record"
                  theme=${this.theme}
                ></vanna-progress-tracker>
                <div class="sidebar-note">
                  <div class="note-row">
                    <span>Protocol</span>
                    <strong>${this.apiVersion.toUpperCase()}</strong>
                  </div>
                  <div class="note-row">
                    <span>Query mode</span>
                    <strong>Read only</strong>
                  </div>
                  <div class="note-row">
                    <span>Answer record</span>
                    <strong
                      >${this.apiVersion === "v3"
                        ? "Lineage enabled"
                        : "Activity enabled"}</strong
                    >
                  </div>
                </div>
              </aside>
            `
            : ""}
        </div>
      </div>
      </sp-theme>
    `;
  }
}
