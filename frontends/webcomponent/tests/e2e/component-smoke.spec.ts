import { expect, test } from '@playwright/test';

test('loads the frontend entry point and renders without a backend', async ({ page }) => {
  await page.goto('/tests/e2e/harness.html');

  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true', { timeout: 15_000 });
  await expect(page.locator('vanna-status-bar').locator('.status-text')).toHaveText(
    'Frontend bundle loaded'
  );

  const registered = await page.evaluate(() => ({
    actionButton: Boolean(customElements.get('sp-action-button')),
    chat: Boolean(customElements.get('vanna-chat')),
    statusBar: Boolean(customElements.get('vanna-status-bar')),
    textfield: Boolean(customElements.get('sp-textfield')),
    theme: Boolean(customElements.get('sp-theme')),
    vegaChart: Boolean(customElements.get('vega-lite-chart')),
  }));
  expect(registered).toEqual({
    actionButton: true,
    chat: true,
    statusBar: true,
    textfield: true,
    theme: true,
    vegaChart: true,
  });
});

test('uses Spectrum controls without breaking prompt focus or composer state', async ({ page }) => {
  await page.goto('/tests/e2e/harness.html');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true', { timeout: 15_000 });

  const chat = page.locator('#chat');
  const suggestion = chat.locator('sp-action-button.prompt-suggestion').first();
  const field = chat.locator('sp-textfield.message-input');
  const send = chat.locator('sp-button.send-button');

  await suggestion.click();
  await expect(field).toHaveJSProperty('value', 'Compare revenue by region');
  await expect(send).toBeEnabled();

  const focus = await page.evaluate(() => {
    const chatElement = document.querySelector('#chat') as HTMLElement & {
      shadowRoot: ShadowRoot;
    };
    const fieldElement = chatElement.shadowRoot.querySelector(
      'sp-textfield.message-input',
    ) as HTMLElement & { shadowRoot: ShadowRoot };
    const theme = chatElement.shadowRoot.querySelector('sp-theme');
    return {
      color: theme?.getAttribute('color'),
      control: fieldElement.shadowRoot.activeElement?.tagName,
      field: chatElement.shadowRoot.activeElement === fieldElement,
      host: document.activeElement === chatElement,
      scale: theme?.getAttribute('scale'),
      system: theme?.getAttribute('system'),
    };
  });

  expect(focus).toEqual({
    color: 'light',
    control: 'TEXTAREA',
    field: true,
    host: true,
    scale: 'medium',
    system: 'spectrum-two',
  });
});
