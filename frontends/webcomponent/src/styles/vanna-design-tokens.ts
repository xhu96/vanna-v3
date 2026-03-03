import { css } from 'lit';

// Vanna Premium UI Design Tokens
export const vannaDesignTokens = css`
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@500;600;700&display=swap');

  :host {
    /* Premium Brand Colors */
    --vanna-iris: #6366F1;
    --vanna-iris-light: #818CF8;
    --vanna-iris-dark: #4F46E5;
    
    --vanna-emerald: #10B981;
    --vanna-rose: #F43F5E;
    --vanna-amber: #F59E0B;

    /* Color Palette - Light mode (Premium Apple/ChatGPT-esque) */
    --vanna-background-root: rgb(255, 255, 255);
    --vanna-background-default: rgb(252, 253, 254);
    --vanna-background-higher: rgb(249, 250, 251);
    --vanna-background-highest: rgb(243, 244, 246);
    --vanna-background-subtle: rgba(249, 250, 251, 0.5);
    --vanna-background-lower: rgb(229, 231, 235);

    --vanna-foreground-default: rgb(15, 23, 42);
    --vanna-foreground-dimmer: rgb(71, 85, 105);
    --vanna-foreground-dimmest: rgb(100, 116, 139);

    /* Primary Accents */
    --vanna-accent-primary-default: var(--vanna-iris);
    --vanna-accent-primary-stronger: var(--vanna-iris-dark);
    --vanna-accent-primary-strongest: #3730A3;
    --vanna-accent-primary-subtle: rgba(99, 102, 241, 0.1);
    --vanna-accent-primary-hover: var(--vanna-iris-light);

    /* Status Accents */
    --vanna-accent-positive-default: var(--vanna-emerald);
    --vanna-accent-positive-stronger: #059669;
    --vanna-accent-positive-subtle: rgba(16, 185, 129, 0.1);

    --vanna-accent-negative-default: var(--vanna-rose);
    --vanna-accent-negative-stronger: #E11D48;
    --vanna-accent-negative-subtle: rgba(244, 63, 94, 0.1);

    --vanna-accent-warning-default: var(--vanna-amber);
    --vanna-accent-warning-stronger: #D97706;
    --vanna-accent-warning-subtle: rgba(245, 158, 11, 0.1);

    /* Outline/Border colors - Extremely subtle glass-like */
    --vanna-outline-default: rgba(15, 23, 42, 0.06);
    --vanna-outline-dimmer: rgba(15, 23, 42, 0.04);
    --vanna-outline-dimmest: rgba(15, 23, 42, 0.02);
    --vanna-outline-hover: rgba(99, 102, 241, 0.3);

    /* Typography - Premium Modern Fonts */
    --vanna-font-family-default: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
    --vanna-font-family-serif: 'Outfit', -apple-system, BlinkMacSystemFont, "Segoe UI", serif;
    --vanna-font-family-mono: "ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "Liberation Mono", "Courier New", monospace;

    /* Spacing scale */
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

    /* Border radius - Highly Organic */
    --vanna-border-radius-sm: 8px;
    --vanna-border-radius-md: 12px;
    --vanna-border-radius-lg: 16px;
    --vanna-border-radius-xl: 24px;
    --vanna-border-radius-2xl: 32px;
    --vanna-border-radius-full: 9999px;

    /* Shadows - Deep, Soft, Premium Drop Shadows */
    --vanna-shadow-xs: 0 1px 2px 0 rgba(15, 23, 42, 0.02);
    --vanna-shadow-sm: 0 1px 3px 0 rgba(15, 23, 42, 0.04), 0 1px 2px -1px rgba(15, 23, 42, 0.03);
    --vanna-shadow-md: 0 4px 6px -1px rgba(15, 23, 42, 0.05), 0 2px 4px -2px rgba(15, 23, 42, 0.03);
    --vanna-shadow-lg: 0 10px 15px -3px rgba(15, 23, 42, 0.06), 0 4px 6px -4px rgba(15, 23, 42, 0.04);
    --vanna-shadow-xl: 0 20px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04);
    --vanna-shadow-2xl: 0 25px 50px -12px rgba(15, 23, 42, 0.15);
    
    /* Elegant Inner Edge Lighting */
    --vanna-inner-glow: inset 0 1px 0 0 rgba(255, 255, 255, 0.8);

    /* Animation durations - Snappy but fluid */
    --vanna-duration-75: 75ms;
    --vanna-duration-100: 100ms;
    --vanna-duration-150: 150ms;
    --vanna-duration-200: 200ms;
    --vanna-duration-300: 300ms;
    --vanna-duration-400: 400ms;
    --vanna-duration-500: 500ms;
    --vanna-duration-700: 700ms;

    /* Z-index scale */
    --vanna-z-dropdown: 1000;
    --vanna-z-sticky: 1020;
    --vanna-z-fixed: 1030;
    --vanna-z-modal: 1040;
    --vanna-z-popover: 1050;
    --vanna-z-tooltip: 1060;

    /* Chat-specific custom variables */
    --vanna-chat-bubble-radius: 24px;
    --vanna-chat-bubble-radius-sm: 6px;
    --vanna-chat-spacing: 24px;
    --vanna-chat-avatar-size: 36px;
  }

  /* Dark Theme Overrides - OLED Blacks and Frosted Glass */
  :host([theme="dark"]) {
    --vanna-background-root: rgb(11, 15, 25);
    --vanna-background-default: rgb(17, 24, 39);
    --vanna-background-higher: rgb(26, 32, 44);
    --vanna-background-highest: rgb(31, 41, 55);
    --vanna-background-subtle: rgba(31, 41, 55, 0.5);
    --vanna-background-lower: rgb(9, 11, 19);

    --vanna-foreground-default: rgb(248, 250, 252);
    --vanna-foreground-dimmer: rgb(203, 213, 225);
    --vanna-foreground-dimmest: rgb(148, 163, 184);

    --vanna-accent-primary-default: var(--vanna-iris-light);
    --vanna-accent-primary-stronger: var(--vanna-iris);
    --vanna-accent-primary-strongest: var(--vanna-iris-dark);
    --vanna-accent-primary-subtle: rgba(129, 140, 248, 0.15);
    --vanna-accent-primary-hover: #A5B4FC;

    --vanna-accent-positive-default: #34D399;
    --vanna-accent-positive-stronger: var(--vanna-emerald);
    --vanna-accent-positive-subtle: rgba(52, 211, 153, 0.15);

    --vanna-accent-negative-default: #FB7185;
    --vanna-accent-negative-stronger: var(--vanna-rose);
    --vanna-accent-negative-subtle: rgba(251, 113, 133, 0.15);

    --vanna-accent-warning-default: #FBBF24;
    --vanna-accent-warning-stronger: var(--vanna-amber);
    --vanna-accent-warning-subtle: rgba(251, 191, 36, 0.15);

    /* Very subtle glass outlines for dark mode */
    --vanna-outline-default: rgba(255, 255, 255, 0.08);
    --vanna-outline-dimmer: rgba(255, 255, 255, 0.05);
    --vanna-outline-dimmest: rgba(255, 255, 255, 0.03);
    --vanna-outline-hover: rgba(129, 140, 248, 0.4);

    /* Deep layered shadows */
    --vanna-shadow-xs: 0 1px 2px 0 rgba(0, 0, 0, 0.4);
    --vanna-shadow-sm: 0 1px 3px 0 rgba(0, 0, 0, 0.5), 0 1px 2px -1px rgba(0, 0, 0, 0.4);
    --vanna-shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.6), 0 2px 4px -2px rgba(0, 0, 0, 0.5);
    --vanna-shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.7), 0 4px 6px -4px rgba(0, 0, 0, 0.6);
    --vanna-shadow-xl: 0 20px 25px -5px rgba(0, 0, 0, 0.8), 0 8px 10px -6px rgba(0, 0, 0, 0.7);
    --vanna-shadow-2xl: 0 25px 50px -12px rgba(0, 0, 0, 0.9);
    
    --vanna-inner-glow: inset 0 1px 0 0 rgba(255, 255, 255, 0.06);
  }
`;
