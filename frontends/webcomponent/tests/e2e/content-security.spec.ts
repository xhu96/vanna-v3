import { expect, test } from '@playwright/test';

const baseComponent = {
  children: [],
  interactive: false,
  lifecycle: 'create',
  timestamp: '2026-01-01T00:00:00.000Z',
  visible: true,
};

test('keeps model card HTML, handlers, and executable links inert', async ({ page }) => {
  const attackerRequests: string[] = [];
  await page.route('https://attacker.invalid/**', async (route) => {
    attackerRequests.push(route.request().url());
    await route.abort();
  });
  await page.goto('/tests/e2e/harness.html');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true', { timeout: 15_000 });

  const state = await page.evaluate(async (base) => {
    const registry = new (window as any).VannaComponents.ComponentRegistry();
    (window as any).__xss = [];

    const card = registry.render({
      ...base,
      id: 'security-card',
      type: 'card',
      data: {
        content: '# Safe heading\n\n<img src=x onerror="window.__xss.push(\'card-event\')"><script>window.__xss.push(\'card-script\')</script>',
        innerHTML: '<img src=x onerror="window.__xss.push(\'property\')">',
        markdown: true,
        title: '<img src=x onerror="window.__xss.push(\'title\')">Card title',
      },
    });
    card.id = 'security-card';
    document.body.append(card);
    await (card as any).updateComplete;

    const links = registry.render({
      ...base,
      id: 'security-links',
      type: 'status_card',
      data: {
        description: `
          <a id="javascript-link" href="javascript:window.__xss.push('javascript')" onclick="window.__xss.push('click')">bad</a>
          <a id="data-link" href="data:text/html,<script>window.__xss.push('data')</script>">data</a>
          <a id="safe-link" href="https://example.test/docs" target="_blank">safe</a>
          <img id="remote-image" src="https://attacker.invalid/tracker.png">
          <svg><use id="remote-use" href="https://attacker.invalid/icons.svg#x"></use></svg>
          <svg><use id="remote-xlink" xlink:href="https://attacker.invalid/icons.svg#x"></use></svg>
          <div id="overlay" style="position:fixed;inset:0">overlay</div>
        `,
        status: 'success',
        title: 'Link policy',
      },
    });
    links.id = 'security-links';
    document.body.append(links);

    const shadow = card.shadowRoot!;
    return {
      cardHasImage: Boolean(shadow.querySelector('.card-content img')),
      cardHasScript: Boolean(shadow.querySelector('.card-content script')),
      cardLightDom: card.innerHTML,
      cardText: shadow.querySelector('.card-content')?.textContent,
      dataHref: links.querySelector('#data-link')?.getAttribute('href'),
      javascriptHref: links.querySelector('#javascript-link')?.getAttribute('href'),
      javascriptOnclick: links.querySelector('#javascript-link')?.getAttribute('onclick'),
      overlayStyle: links.querySelector('#overlay')?.getAttribute('style'),
      remoteSrc: links.querySelector('#remote-image')?.getAttribute('src'),
      remoteUseHref: links.querySelector('#remote-use')?.getAttribute('href') ?? null,
      remoteUseXlink: links.querySelector('#remote-xlink')?.getAttribute('xlink:href') ?? null,
      safeHref: links.querySelector('#safe-link')?.getAttribute('href'),
      safeRel: links.querySelector('#safe-link')?.getAttribute('rel'),
      xss: (window as any).__xss,
    };
  }, baseComponent);

  expect(state).toMatchObject({
    cardHasImage: false,
    cardHasScript: false,
    cardLightDom: '',
    dataHref: null,
    javascriptHref: null,
    javascriptOnclick: null,
    overlayStyle: null,
    remoteSrc: null,
    remoteUseHref: null,
    remoteUseXlink: null,
    safeHref: 'https://example.test/docs',
    safeRel: 'noreferrer noopener',
    xss: [],
  });
  expect(state.cardText).toContain('<img src=x');
  expect(attackerRequests).toEqual([]);
});

test('sanitizes Vega chart titles/specs and blocks external chart resources', async ({ page }) => {
  const attackerRequests: string[] = [];
  await page.route('https://attacker.invalid/**', async (route) => {
    attackerRequests.push(route.request().url());
    await route.abort();
  });
  await page.goto('/tests/e2e/harness.html');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true', { timeout: 15_000 });

  await page.evaluate((base) => {
    const registry = new (window as any).VannaComponents.ComponentRegistry();
    (window as any).__chartXss = false;
    const chart = registry.render({
      ...base,
      id: 'security-chart',
      type: 'chart',
      data: {
        data: {
          dataset: [{ category: 'A', link: 'javascript:alert(1)', value: 2 }],
          format: 'vega-lite',
          spec: {
            data: { url: 'https://attacker.invalid/chart.json' },
            encoding: {
              href: { field: 'link' },
              x: { field: 'category', type: 'nominal' },
              y: { field: 'value', type: 'quantitative' },
            },
            mark: 'bar',
            title: '<img src=x onerror="window.__chartXss=true">Spec title',
          },
        },
        title: '<img src=x onerror="window.__chartXss=true">Quarterly',
      },
    });
    chart.id = 'security-chart';
    document.body.append(chart);
  }, baseComponent);

  await expect(page.locator('#security-chart vega-lite-chart')).toHaveCount(1);
  await expect(page.locator('#security-chart vega-lite-chart .chart-root svg')).toHaveCount(1);
  await page.waitForTimeout(250);

  const state = await page.evaluate(() => ({
    hasTitleImage: Boolean(document.querySelector('#security-chart .chart-title img')),
    title: document.querySelector('#security-chart .chart-title')?.textContent,
    xss: (window as any).__chartXss,
  }));
  expect(state).toEqual({
    hasTitleImage: false,
    title: '<img src=x onerror="window.__chartXss=true">Quarterly',
    xss: false,
  });
  expect(attackerRequests).toEqual([]);
});

test('isolates static artifacts from parent, opener, popup, and network access', async ({ page }) => {
  const attackerRequests: string[] = [];
  let popupCount = 0;
  page.on('popup', () => {
    popupCount += 1;
  });
  await page.route('https://attacker.invalid/**', async (route) => {
    attackerRequests.push(route.request().url());
    await route.abort();
  });
  await page.goto('/tests/e2e/harness.html');
  await expect(page.locator('html')).toHaveAttribute('data-ready', 'true', { timeout: 15_000 });

  await page.evaluate((base) => {
    const registry = new (window as any).VannaComponents.ComponentRegistry();
    (window as any).__artifactXss = [];
    document.addEventListener('artifact-opened', (event) => {
      const detail = (event as CustomEvent).detail;
      if (detail.trigger === 'user-action') {
        (window as any).__artifactEvent = {
          content: detail.content,
          standalone: detail.getStandaloneHTML(),
        };
      }
    });

    const artifact = registry.render({
      ...base,
      id: 'security-artifact',
      type: 'artifact',
      data: {
        artifact_id: 'static-html',
        artifact_type: 'html',
        content: `
          <strong id="safe-artifact-content">Static content</strong>
          <a id="artifact-javascript" href="javascript:parent.document.body.dataset.pwned=1">bad</a>
          <a id="artifact-data" href="data:text/html,bad">data</a>
          <a id="artifact-network" href="https://attacker.invalid/open">network</a>
          <img src="https://attacker.invalid/pixel" onerror="parent.document.body.dataset.pwned=2">
          <style>@import url(https://attacker.invalid/style.css);</style>
          <script>
            parent.document.body.dataset.pwned = 'script';
            if (opener) opener.document.body.dataset.pwned = 'opener';
            fetch('https://attacker.invalid/fetch');
            window.open('https://attacker.invalid/popup');
          </script>
        `,
        external_renderable: true,
        fullscreen_capable: true,
        title: 'Static HTML',
      },
    });
    artifact.id = 'security-artifact';
    document.body.append(artifact);

    const javascriptArtifact = registry.render({
      ...base,
      id: 'javascript-artifact',
      type: 'artifact',
      data: {
        artifact_id: 'source-js',
        artifact_type: 'javascript',
        content: `parent.document.body.dataset.pwned = 'javascript-source'; fetch('https://attacker.invalid/js');`,
        title: 'JavaScript source',
      },
    });
    javascriptArtifact.id = 'javascript-artifact';
    document.body.append(javascriptArtifact);
  }, baseComponent);

  const preview = page.locator('#security-artifact .artifact-iframe');
  await expect(preview).toHaveAttribute('sandbox', '');
  await expect(preview).toHaveAttribute('referrerpolicy', 'no-referrer');
  const srcdoc = await preview.getAttribute('srcdoc');
  expect(srcdoc).toContain("script-src 'none'");
  expect(srcdoc).toContain("connect-src 'none'");
  expect(srcdoc).not.toContain('attacker.invalid');
  expect(srcdoc).not.toContain('<script>');

  const artifactFrame = page.frameLocator('#security-artifact .artifact-iframe');
  await expect(artifactFrame.locator('#safe-artifact-content')).toHaveText('Static content');
  await expect(artifactFrame.locator('script')).toHaveCount(0);
  await expect(artifactFrame.locator('[onerror]')).toHaveCount(0);
  await expect(artifactFrame.locator('a[href]')).toHaveCount(0);

  const isolation = await artifactFrame.locator('body').evaluate(() => {
    let parentAccessible = false;
    try {
      void window.parent.document.body;
      parentAccessible = true;
    } catch {
      parentAccessible = false;
    }
    return { openerIsNull: window.opener === null, parentAccessible };
  });
  expect(isolation).toEqual({ openerIsNull: true, parentAccessible: false });

  const sourceFrame = page.frameLocator('#javascript-artifact .artifact-iframe');
  await expect(sourceFrame.locator('pre code')).toContainText('parent.document.body.dataset.pwned');
  await expect(sourceFrame.locator('script')).toHaveCount(0);

  await page.locator('#security-artifact .external-btn').click();
  await expect(page.locator('.artifact-fullscreen-overlay .fullscreen-iframe')).toHaveAttribute(
    'sandbox',
    ''
  );
  await page.waitForTimeout(250);

  const state = await page.evaluate(() => ({
    event: (window as any).__artifactEvent,
    parentPwned: document.body.dataset.pwned ?? null,
    xss: (window as any).__artifactXss,
  }));
  expect(state.parentPwned).toBeNull();
  expect(state.xss).toEqual([]);
  expect(state.event.content).not.toContain('attacker.invalid');
  expect(state.event.content).not.toContain('<script>');
  expect(state.event.standalone).toContain("script-src 'none'");
  expect(state.event.standalone).not.toContain('attacker.invalid');
  expect(attackerRequests).toEqual([]);
  expect(popupCount).toBe(0);
});
