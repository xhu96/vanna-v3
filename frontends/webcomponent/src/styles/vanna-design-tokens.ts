import { css, unsafeCSS } from "lit";
import plexMonoRegularUrl from "@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-400-normal.woff2?url";
import plexMonoSemiboldUrl from "@fontsource/ibm-plex-mono/files/ibm-plex-mono-latin-600-normal.woff2?url";
import plexSansUrl from "@fontsource-variable/ibm-plex-sans/files/ibm-plex-sans-latin-wght-normal.woff2?url";

const plexSansSource = unsafeCSS(plexSansUrl);
const plexMonoRegularSource = unsafeCSS(plexMonoRegularUrl);
const plexMonoSemiboldSource = unsafeCSS(plexMonoSemiboldUrl);

// Shared product tokens for the framework-agnostic component surface.
export const vannaDesignTokens = css`
  @font-face {
    font-family: "Vanna Plex Sans";
    font-style: normal;
    font-weight: 100 700;
    font-display: swap;
    src: url("${plexSansSource}") format("woff2");
  }

  @font-face {
    font-family: "Vanna Plex Mono";
    font-style: normal;
    font-weight: 400;
    font-display: swap;
    src: url("${plexMonoRegularSource}") format("woff2");
  }

  @font-face {
    font-family: "Vanna Plex Mono";
    font-style: normal;
    font-weight: 600;
    font-display: swap;
    src: url("${plexMonoSemiboldSource}") format("woff2");
  }

  :host {
    --vanna-navy: #16383c;
    --vanna-cream: #f4f6f7;
    --vanna-teal: #087b72;
    --vanna-orange: #c35f2f;
    --vanna-magenta: #9b3f61;

    --vanna-background-root: #ffffff;
    --vanna-background-default: #f5f7f8;
    --vanna-background-higher: #eef1f2;
    --vanna-background-highest: #e3e7e9;
    --vanna-background-subtle: #fafbfb;
    --vanna-background-lower: #e9edef;

    --vanna-foreground-default: #182125;
    --vanna-foreground-dimmer: #566168;
    --vanna-foreground-dimmest: #737e84;

    --vanna-accent-primary-default: #087b72;
    --vanna-accent-primary-stronger: #06665f;
    --vanna-accent-primary-strongest: #064d48;
    --vanna-accent-primary-subtle: #e7f3f1;
    --vanna-accent-primary-hover: #066b64;

    --vanna-accent-positive-default: #087b72;
    --vanna-accent-positive-stronger: #06665f;
    --vanna-accent-positive-subtle: #e7f3f1;

    --vanna-accent-negative-default: #b4473e;
    --vanna-accent-negative-stronger: #91372f;
    --vanna-accent-negative-subtle: #f9eceb;

    --vanna-accent-warning-default: #c35f2f;
    --vanna-accent-warning-stronger: #9f4820;
    --vanna-accent-warning-subtle: #fbefe8;

    --vanna-outline-default: #d7dcdf;
    --vanna-outline-dimmer: #e5e8ea;
    --vanna-outline-dimmest: #eef0f1;
    --vanna-outline-hover: #abb4b9;

    --vanna-font-family-default:
      "Vanna Plex Sans", "Avenir Next", "Segoe UI", sans-serif;
    --vanna-font-family-display: var(--vanna-font-family-default);
    --vanna-font-family-serif: Georgia, serif;
    --vanna-font-family-mono:
      "Vanna Plex Mono", "SFMono-Regular", Consolas, monospace;

    --vanna-space-0: 0px;
    --vanna-space-1: 4px;
    --vanna-space-2: 8px;
    --vanna-space-3: 12px;
    --vanna-space-4: 16px;
    --vanna-space-5: 20px;
    --vanna-space-6: 24px;
    --vanna-space-7: 28px;
    --vanna-space-8: 32px;
    --vanna-space-10: 40px;
    --vanna-space-12: 48px;
    --vanna-space-16: 64px;

    --vanna-border-radius-sm: 3px;
    --vanna-border-radius-md: 6px;
    --vanna-border-radius-lg: 8px;
    --vanna-border-radius-xl: 10px;
    --vanna-border-radius-2xl: 12px;
    --vanna-border-radius-full: 9999px;

    --vanna-shadow-xs: 0 1px 2px rgba(24, 33, 37, 0.05);
    --vanna-shadow-sm: 0 2px 6px rgba(24, 33, 37, 0.06);
    --vanna-shadow-md: 0 8px 24px rgba(24, 33, 37, 0.08);
    --vanna-shadow-lg: 0 14px 36px rgba(24, 33, 37, 0.11);
    --vanna-shadow-xl: 0 22px 54px rgba(24, 33, 37, 0.12);
    --vanna-shadow-2xl: 0 28px 72px rgba(24, 33, 37, 0.16);

    --vanna-duration-75: 75ms;
    --vanna-duration-100: 100ms;
    --vanna-duration-150: 150ms;
    --vanna-duration-200: 200ms;
    --vanna-duration-300: 300ms;
    --vanna-duration-500: 500ms;
    --vanna-duration-700: 700ms;

    --vanna-z-dropdown: 1000;
    --vanna-z-sticky: 1020;
    --vanna-z-fixed: 1030;
    --vanna-z-modal: 1040;
    --vanna-z-popover: 1050;
    --vanna-z-tooltip: 1060;

    --vanna-chat-bubble-radius: 8px;
    --vanna-chat-bubble-radius-sm: 6px;
    --vanna-chat-spacing: 16px;
    --vanna-chat-avatar-size: 36px;
  }

  :host([theme="dark"]) {
    --vanna-background-root: #13191c;
    --vanna-background-default: #192125;
    --vanna-background-higher: #202a2e;
    --vanna-background-highest: #29353a;
    --vanna-background-subtle: #161d20;
    --vanna-background-lower: #0e1315;

    --vanna-foreground-default: #f2f5f5;
    --vanna-foreground-dimmer: #b5bec2;
    --vanna-foreground-dimmest: #8d989d;

    --vanna-accent-primary-default: #58bdb3;
    --vanna-accent-primary-stronger: #79cec6;
    --vanna-accent-primary-strongest: #9cddd7;
    --vanna-accent-primary-subtle: #173936;
    --vanna-accent-primary-hover: #72cbc3;

    --vanna-accent-positive-default: #58bdb3;
    --vanna-accent-positive-stronger: #79cec6;
    --vanna-accent-positive-subtle: #173936;

    --vanna-accent-negative-default: #e1847c;
    --vanna-accent-negative-stronger: #eda39d;
    --vanna-accent-negative-subtle: #3c2222;

    --vanna-accent-warning-default: #e69369;
    --vanna-accent-warning-stronger: #efad8c;
    --vanna-accent-warning-subtle: #3d2a20;

    --vanna-outline-default: #354146;
    --vanna-outline-dimmer: #293338;
    --vanna-outline-dimmest: #222b2f;
    --vanna-outline-hover: #5c6b71;

    --vanna-shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.22);
    --vanna-shadow-sm: 0 2px 6px rgba(0, 0, 0, 0.24);
    --vanna-shadow-md: 0 8px 24px rgba(0, 0, 0, 0.28);
    --vanna-shadow-lg: 0 14px 36px rgba(0, 0, 0, 0.34);
    --vanna-shadow-xl: 0 22px 54px rgba(0, 0, 0, 0.38);
    --vanna-shadow-2xl: 0 28px 72px rgba(0, 0, 0, 0.46);
  }
`;
