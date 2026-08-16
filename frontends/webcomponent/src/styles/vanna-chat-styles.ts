import { css } from "lit";

export const vannaChatStyles = css`
  *,
  *::before,
  *::after {
    box-sizing: border-box;
  }

  :host {
    position: relative;
    display: block;
    width: 100%;
    max-width: 1320px;
    min-width: 0;
    margin: 0 auto;
    overflow: hidden;
    color: var(--vanna-foreground-default);
    background: var(--vanna-background-root);
    border: 1px solid var(--vanna-outline-default);
    border-radius: var(--vanna-border-radius-xl);
    box-shadow: var(--vanna-shadow-xl);
    font-family: var(--vanna-font-family-default);
    -webkit-font-smoothing: antialiased;
  }

  .spectrum-shell {
    display: block;
    width: 100%;
    height: 100%;
    color: var(--vanna-foreground-default);
    background: var(--vanna-background-root);
    font-family: var(--vanna-font-family-default);

    --spectrum-sans-font-family-stack: var(--vanna-font-family-default);
    --spectrum-code-font-family-stack: var(--vanna-font-family-mono);
    --spectrum-focus-indicator-color: var(--vanna-accent-primary-default);
    --spectrum-accent-background-color-default: var(
      --vanna-accent-primary-default
    );
    --spectrum-accent-background-color-hover: var(
      --vanna-accent-primary-stronger
    );
    --spectrum-accent-background-color-down: var(
      --vanna-accent-primary-strongest
    );
    --spectrum-accent-background-color-key-focus: var(
      --vanna-accent-primary-stronger
    );
  }

  :host(.maximized) {
    position: fixed;
    inset: var(--vanna-space-5);
    z-index: var(--vanna-z-modal);
    width: auto;
    max-width: none;
    margin: 0;
    border-radius: var(--vanna-border-radius-lg);
    box-shadow: var(--vanna-shadow-2xl);
  }

  :host(.minimized) {
    position: fixed !important;
    right: var(--vanna-space-5) !important;
    bottom: var(--vanna-space-5) !important;
    z-index: var(--vanna-z-modal) !important;
    width: 52px !important;
    height: 52px !important;
    max-width: none !important;
    margin: 0 !important;
    cursor: pointer !important;
    color: #ffffff;
    background: var(--vanna-navy) !important;
    border-radius: var(--vanna-border-radius-lg) !important;
    box-shadow: var(--vanna-shadow-lg) !important;
  }

  :host(.minimized) .chat-layout {
    display: none;
  }

  .minimized-icon {
    display: none;
  }

  :host(.minimized) .minimized-icon {
    display: grid;
    width: 100%;
    height: 100%;
    place-items: center;
  }

  :host(.minimized) .minimized-icon svg {
    width: 22px;
    height: 22px;
  }

  .chat-layout {
    display: grid;
    height: 812px;
    max-height: min(90vh, 840px);
    grid-template-rows: 62px minmax(0, 1fr);
    background: var(--vanna-background-root);
  }

  :host(.maximized) .chat-layout {
    height: calc(100dvh - 40px);
    max-height: calc(100dvh - 40px);
  }

  .workbench-body {
    display: grid;
    min-width: 0;
    min-height: 0;
    grid-template-columns: minmax(0, 1fr) 304px;
  }

  .chat-layout.compact .workbench-body {
    grid-template-columns: 1fr;
  }

  .chat-main {
    display: flex;
    min-width: 0;
    min-height: 0;
    flex-direction: column;
    background: var(--vanna-background-root);
  }

  .chat-header {
    position: relative;
    z-index: 2;
    display: flex;
    min-width: 0;
    align-items: center;
    padding: 0 16px;
    background: var(--vanna-background-root);
    border-bottom: 1px solid var(--vanna-outline-default);
  }

  .header-top,
  .header-left,
  .header-top-actions,
  .header-meta,
  .window-controls,
  .workspace-line {
    display: flex;
    align-items: center;
  }

  .header-top {
    width: 100%;
    min-width: 0;
    gap: var(--vanna-space-4);
  }

  .header-left {
    min-width: 0;
    flex: 1;
    gap: 10px;
  }

  .chat-avatar {
    display: grid;
    width: 30px;
    height: 30px;
    flex: 0 0 auto;
    place-items: center;
    color: #ffffff;
    background: var(--vanna-navy);
    border-radius: var(--vanna-border-radius-md);
    font-size: 13px;
    font-weight: 700;
  }

  .header-text {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
  }

  .workspace-line {
    min-width: 0;
    gap: 7px;
  }

  .product-name {
    color: var(--vanna-foreground-default);
    font-size: 13px;
    font-weight: 650;
  }

  .breadcrumb-separator {
    color: var(--vanna-outline-hover);
    font-size: 13px;
  }

  .chat-title {
    overflow: hidden;
    margin: 0;
    color: var(--vanna-foreground-dimmer);
    font-size: 13px;
    font-weight: 520;
    line-height: 1.25;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .chat-subtitle {
    overflow: hidden;
    color: var(--vanna-foreground-dimmest);
    font-size: 11px;
    line-height: 1.25;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .header-top-actions {
    gap: 10px;
    margin-left: auto;
  }

  .header-meta {
    gap: 5px;
  }

  .context-chip {
    display: inline-flex;
    min-height: 24px;
    align-items: center;
    gap: 6px;
    padding: 0 7px;
    color: var(--vanna-foreground-dimmer);
    border-radius: var(--vanna-border-radius-sm);
    font-size: 11px;
    font-weight: 560;
  }

  .context-chip.protocol {
    color: var(--vanna-foreground-dimmer);
    background: var(--vanna-background-default);
    border: 1px solid var(--vanna-outline-default);
    font-family: var(--vanna-font-family-mono);
    font-size: 10px;
  }

  .context-dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--vanna-accent-positive-default);
  }

  .header-progress {
    width: 12px;
    height: 12px;
    flex: 0 0 auto;
    --mod-progress-circle-track-fill-color: var(
      --vanna-accent-primary-default
    );
  }

  .window-controls {
    gap: 2px;
    padding-left: 9px;
    border-left: 1px solid var(--vanna-outline-dimmer);
  }

  .window-control-btn {
    width: 30px;
    height: 30px;
    flex: 0 0 auto;
    color: var(--vanna-foreground-dimmer);

    --mod-actionbutton-height: 30px;
    --mod-actionbutton-min-width: 30px;
    --mod-actionbutton-border-radius: var(--vanna-border-radius-md);
    --mod-actionbutton-edge-to-visual-only: 7px;
  }

  .window-control-btn svg {
    width: 15px;
    height: 15px;
  }

  .chat-messages {
    display: flex;
    min-height: 0;
    flex: 1;
    flex-direction: column;
    gap: var(--vanna-space-4);
    overflow-x: hidden;
    overflow-y: auto;
    padding: 26px 30px 30px;
    scroll-behavior: smooth;
    background: var(--vanna-background-root);
  }

  .chat-messages.has-scroll {
    box-shadow: inset 0 8px 10px -12px rgba(24, 33, 37, 0.55);
  }

  .rich-components-container {
    display: flex;
    width: min(820px, 100%);
    flex-direction: column;
    gap: 18px;
    padding-bottom: 18px;
  }

  .rich-components-container > :not(style) {
    animation: content-enter 180ms ease-out both;
  }

  .unknown-component {
    padding: var(--vanna-space-4);
    color: var(--vanna-foreground-dimmer);
    background: var(--vanna-background-default);
    border: 1px solid var(--vanna-outline-default);
    border-radius: var(--vanna-border-radius-md);
    font-family: var(--vanna-font-family-mono);
    font-size: 12px;
  }

  .unknown-component p,
  .unknown-component pre {
    margin: 0;
  }

  .unknown-component p {
    margin-bottom: var(--vanna-space-2);
  }

  .unknown-component pre {
    overflow-x: auto;
  }

  .empty-state {
    display: flex;
    width: min(650px, 100%);
    margin: auto;
    flex-direction: column;
    align-items: flex-start;
    padding: 38px 18px;
    color: var(--vanna-foreground-dimmer);
    text-align: left;
  }

  .empty-state-icon {
    display: grid;
    width: 38px;
    height: 38px;
    margin-bottom: 22px;
    place-items: center;
    color: var(--vanna-navy);
    background: var(--vanna-background-default);
    border: 1px solid var(--vanna-outline-default);
    border-radius: var(--vanna-border-radius-md);
  }

  .empty-state-icon svg {
    width: 19px;
    height: 19px;
  }

  .empty-state-text {
    max-width: 520px;
    color: var(--vanna-foreground-default);
    font-size: clamp(22px, 3vw, 28px);
    font-weight: 650;
    letter-spacing: -0.025em;
    line-height: 1.18;
  }

  .empty-state-subtitle {
    max-width: 550px;
    margin-top: 9px;
    color: var(--vanna-foreground-dimmer);
    font-size: 14px;
    line-height: 1.55;
  }

  .prompt-suggestions {
    display: grid;
    width: min(560px, 100%);
    margin-top: 26px;
    border-top: 1px solid var(--vanna-outline-dimmer);
  }

  .prompt-suggestion {
    display: flex;
    width: 100%;
    min-height: 43px;
    color: var(--vanna-foreground-default);
    border-bottom: 1px solid var(--vanna-outline-dimmer);
    font-family: var(--vanna-font-family-default);

    --mod-actionbutton-height: 42px;
    --mod-actionbutton-min-width: 100%;
    --mod-actionbutton-border-radius: 0;
    --mod-actionbutton-label-flex-grow: 1;
    --mod-actionbutton-label-text-align: left;
    --mod-actionbutton-font-family: var(--vanna-font-family-default);
  }

  .prompt-suggestion[aria-disabled="true"] {
    cursor: not-allowed;
    opacity: 0.55;
  }

  .chat-input-area {
    display: flex;
    flex: 0 0 auto;
    flex-direction: column;
    gap: 8px;
    padding: 12px 18px 14px;
    background: var(--vanna-background-subtle);
    border-top: 1px solid var(--vanna-outline-default);
  }

  .chat-input-container {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: flex-end;
    gap: 10px;
  }

  .message-input {
    width: 100%;
    min-width: 0;
    min-height: 48px;
    max-height: 126px;

    --mod-textfield-font-family: var(--vanna-font-family-default);
    --mod-textfield-font-size: 14px;
    --mod-textfield-border-radius: var(--vanna-border-radius-lg);
    --mod-textfield-background-color: var(--vanna-background-root);
    --mod-textfield-focus-indicator-color: var(
      --vanna-accent-primary-default
    );
  }

  .send-button {
    min-width: 116px;
    min-height: 48px;
    flex: 0 0 auto;
    align-self: stretch;

    --mod-button-height: 48px;
    --mod-button-min-width: 116px;
    --mod-button-border-radius: var(--vanna-border-radius-lg);
    --mod-button-font-family: var(--vanna-font-family-default);
  }

  .send-button svg {
    width: 15px;
    height: 15px;
  }

  .input-meta {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 0 2px;
    color: var(--vanna-foreground-dimmest);
    font-size: 10px;
    line-height: 1.3;
  }

  .input-security {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--vanna-foreground-dimmer);
    font-weight: 560;
  }

  .input-security svg {
    width: 12px;
    height: 12px;
    color: var(--vanna-accent-primary-default);
  }

  .input-shortcut {
    font-family: var(--vanna-font-family-default);
  }

  .sidebar {
    display: flex;
    min-height: 0;
    flex-direction: column;
    gap: 14px;
    overflow-x: hidden;
    overflow-y: auto;
    padding: 20px 18px;
    background: var(--vanna-background-default);
    border-left: 1px solid var(--vanna-outline-default);
  }

  .sidebar-heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--vanna-outline-default);
  }

  .sidebar-title {
    margin: 0;
    color: var(--vanna-foreground-default);
    font-size: 13px;
    font-weight: 650;
  }

  .evidence-state {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--vanna-foreground-dimmer);
    font-size: 10px;
    font-weight: 560;
  }

  .evidence-state::before {
    width: 7px;
    height: 7px;
    content: "";
    background: var(--vanna-accent-positive-default);
    border-radius: 50%;
  }

  .sidebar-note {
    display: grid;
    margin-top: auto;
    border-top: 1px solid var(--vanna-outline-default);
  }

  .note-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    min-height: 34px;
    padding: 9px 0;
    color: var(--vanna-foreground-dimmest);
    font-size: 10px;
  }

  .note-row + .note-row {
    border-top: 1px solid var(--vanna-outline-dimmer);
  }

  .note-row strong {
    color: var(--vanna-foreground-dimmer);
    font-weight: 620;
    text-align: right;
  }

  @keyframes content-enter {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @media (max-width: 900px) {
    .chat-layout {
      height: min(820px, 94vh);
      max-height: 94vh;
    }

    .workbench-body {
      grid-template-columns: 1fr;
      grid-template-rows: minmax(0, 1fr) 184px;
    }

    .sidebar {
      padding: 12px 16px;
      border-top: 1px solid var(--vanna-outline-default);
      border-left: 0;
    }

    .sidebar-heading {
      padding-bottom: 8px;
    }

    .sidebar-note {
      display: none;
    }
  }

  @media (max-width: 640px) {
    :host {
      height: 100dvh;
      border: 0;
      border-radius: 0;
      box-shadow: none;
    }

    :host(.maximized) {
      inset: 0;
      border-radius: 0;
    }

    .chat-layout,
    :host(.maximized) .chat-layout {
      height: 100dvh;
      max-height: 100dvh;
      grid-template-rows: 58px minmax(0, 1fr);
    }

    .workbench-body {
      grid-template-rows: minmax(0, 1fr) 166px;
    }

    .chat-header {
      padding: 0 11px;
    }

    .chat-avatar {
      width: 28px;
      height: 28px;
    }

    .chat-subtitle,
    .context-chip:not(.protocol) {
      display: none;
    }

    .header-top-actions {
      gap: 5px;
    }

    .window-controls {
      padding-left: 3px;
      border-left: 0;
    }

    .window-control-btn {
      width: 28px;
      height: 28px;

      --mod-actionbutton-height: 28px;
      --mod-actionbutton-min-width: 28px;
    }

    .chat-messages {
      padding: 20px 15px 22px;
    }

    .empty-state {
      padding: 24px 2px;
    }

    .empty-state-icon {
      margin-bottom: 18px;
    }

    .empty-state-text {
      font-size: 22px;
    }

    .prompt-suggestions {
      margin-top: 20px;
    }

    .chat-input-area {
      padding: 10px 11px max(11px, env(safe-area-inset-bottom));
    }

    .send-button {
      min-width: 48px;

      --mod-button-min-width: 48px;
      --mod-button-edge-to-text: 12px;
    }

    .send-label {
      display: none;
    }

    .input-shortcut {
      display: none;
    }

    .sidebar {
      padding-right: 14px;
      padding-left: 14px;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
      scroll-behavior: auto !important;
      animation-duration: 0.01ms !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.01ms !important;
    }
  }
`;
