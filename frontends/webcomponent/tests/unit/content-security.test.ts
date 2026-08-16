import { afterEach, describe, expect, it, vi } from 'vitest';
import { RichCard } from '../../src/components/rich-card';
import {
  ArtifactComponentRenderer,
  CardComponentRenderer,
  ComponentRegistry,
  type RichComponent,
} from '../../src/components/rich-component-system';
import {
  buildSafePlotlyConfig,
  buildStaticArtifactDocument,
  renderSanitizedMarkdown,
  sanitizeArtifactContent,
  sanitizeHtml,
  sanitizePlotlyData,
  sanitizePlotlyValue,
  sanitizeVegaSpec,
  STATIC_ARTIFACT_CSP,
} from '../../src/security/content-security';

function component(type: string, data: Record<string, unknown>): RichComponent {
  return {
    children: [],
    data,
    id: `test-${type}`,
    interactive: false,
    lifecycle: 'create',
    timestamp: new Date(0).toISOString(),
    type,
    visible: true,
  };
}

function parseFragment(value: string): HTMLElement {
  const root = document.createElement('div');
  root.innerHTML = value;
  return root;
}

afterEach(() => {
  document.body.replaceChildren();
  delete (window as Window & { __xss?: string }).__xss;
});

describe('reviewed content sanitization boundary', () => {
  it('removes scripts, event handlers, and executable URLs while preserving safe markup', () => {
    const value = sanitizeHtml(`
      <strong id="safe">Safe</strong>
      <script>window.__xss = 'script'</script>
      <img src="https://images.example.test/a.png" onerror="window.__xss = 'event'">
      <a id="javascript" href="javascript:alert(1)" onclick="alert(1)">bad</a>
      <a id="data" href="data:text/html,<script>alert(1)</script>">data</a>
      <a id="https" href="https://example.test/docs" target="_blank">docs</a>
      <svg><use id="external-use" href="https://attacker.invalid/icons.svg#x"></use></svg>
      <svg><use id="external-xlink" xlink:href="https://attacker.invalid/icons.svg#x"></use></svg>
    `);
    const root = parseFragment(value);

    expect(root.querySelector('#safe')?.textContent).toBe('Safe');
    expect(root.querySelector('script')).toBeNull();
    expect(root.querySelector('img')?.hasAttribute('onerror')).toBe(false);
    expect(root.querySelector('img')?.hasAttribute('src')).toBe(false);
    expect(root.querySelector('#javascript')?.hasAttribute('href')).toBe(false);
    expect(root.querySelector('#javascript')?.hasAttribute('onclick')).toBe(false);
    expect(root.querySelector('#data')?.hasAttribute('href')).toBe(false);
    expect(root.querySelector('#https')?.getAttribute('href')).toBe('https://example.test/docs');
    expect(root.querySelector('#https')?.getAttribute('rel')).toBe('noreferrer noopener');
    expect(root.querySelector('#external-use')?.getAttribute('href') ?? null).toBeNull();
    expect(root.querySelector('#external-xlink')?.getAttribute('xlink:href') ?? null).toBeNull();
  });

  it('treats raw HTML in model Markdown as text', async () => {
    const element = new RichCard();
    element.markdown = true;
    element.content = '# Safe\n\n<img src=x onerror="window.__xss = 1"><script>window.__xss = 2</script>';
    document.body.append(element);

    await element.updateComplete;

    const content = element.shadowRoot?.querySelector('.card-content');
    expect(content).not.toBeNull();
    expect(content!.querySelector('script')).toBeNull();
    expect(content!.querySelector('img')).toBeNull();
    expect(content!.textContent).toContain('<img src=x');
    expect(renderSanitizedMarkdown('**bold**')).toContain('<strong>bold</strong>');
    expect((window as Window & { __xss?: string }).__xss).toBeUndefined();
  });

  it('sanitizes legacy card HTML and blocks payload-controlled DOM properties', () => {
    const legacy = new CardComponentRenderer().render(component('card', {
      content: '<strong>Allowed</strong><img src=x onerror="window.__xss = 1"><script>alert(1)</script>',
      title: '<img src=x onerror="window.__xss = 2">Title',
    }));

    expect(legacy.querySelector('.card-content strong')?.textContent).toBe('Allowed');
    expect(legacy.querySelector('script')).toBeNull();
    expect(legacy.querySelector('[onerror]')).toBeNull();
    expect(legacy.querySelector('img')?.hasAttribute('src')).toBe(false);

    const mapped = new ComponentRegistry().render(component('card', {
      content: 'Safe card',
      innerHTML: '<img src=x onerror="window.__xss = 3">',
      title: 'Mapped',
    })) as RichCard;
    expect(mapped.innerHTML).toBe('');
    expect((mapped as RichCard & { innerHTML: string }).innerHTML).not.toContain('onerror');
  });
});

describe('chart payload hardening', () => {
  it('sanitizes Plotly strings/resources and applies renderer config last', () => {
    const payload = sanitizePlotlyValue({
      annotations: [{ text: '<a href="javascript:alert(1)">Label</a>' }],
      images: [{ source: 'https://attacker.invalid/image.svg' }],
      title: { text: '<img src=x onerror=alert(1)>Safe<script>alert(2)</script>' },
      xsrc: 'attacker:grid',
    });
    const config = buildSafePlotlyConfig({
      displayModeBar: true,
      plotlyServerURL: 'https://attacker.invalid',
      responsive: false,
      showLink: true,
      showSendToCloud: true,
    });

    expect(payload.title.text).toBe('Safe');
    expect(payload.annotations[0].text).toBe('Label');
    expect(payload).not.toHaveProperty('images');
    expect(payload).not.toHaveProperty('xsrc');
    expect(config).toMatchObject({
      displayModeBar: false,
      plotlyServerURL: '',
      responsive: true,
      showLink: false,
      showSendToCloud: false,
    });
  });

  it('removes Vega resource, expression, and composition channels', () => {
    const spec = sanitizeVegaSpec({
      data: { url: 'https://attacker.invalid/data.json' },
      encoding: {
        href: { field: 'link' },
        x: { axis: { labelExpr: 'datum.label' }, field: 'category' },
      },
      title: '<img src=x onerror=alert(1)>Quarterly<script>alert(2)</script>',
      transform: [{ calculate: 'datum.value * 2', as: 'double' }],
    });

    expect(spec.title).toBe('Quarterly');
    expect(spec.data).not.toHaveProperty('url');
    expect(spec.encoding).not.toHaveProperty('href');
    expect(spec.encoding.x.axis).not.toHaveProperty('labelExpr');
    expect(spec).not.toHaveProperty('transform');
  });

  it('rejects network-capable Plotly traces and bounded payload violations', () => {
    expect(() => sanitizePlotlyData([{ type: 'scattermapbox', x: [1], y: [2] }]))
      .toThrow('trace type is not allowed');
    expect(() => sanitizePlotlyValue({ value: Number.NaN }))
      .toThrow('numbers must be finite');
    expect(() => sanitizePlotlyValue({ values: new Array(5_001).fill(1) }))
      .toThrow('5,000 items');
    expect(() => sanitizePlotlyValue({ value: 'x'.repeat(2 * 1024 * 1024) }))
      .toThrow('2 MiB');
  });

  it('drops parent-page UI redress styles but keeps renderer-owned bounds', () => {
    const root = parseFragment(sanitizeHtml(`
      <div id="overlay" style="position: fixed; inset: 0; width: 100%">overlay</div>
      <div id="progress" style="width: 50%; color: red">progress</div>
    `, 'ui'));

    expect(root.querySelector('#overlay')?.getAttribute('style')).toBe('width: 100%');
    expect(root.querySelector('#progress')?.getAttribute('style')).toContain('width: 50%');
    expect(root.querySelector('#progress')?.getAttribute('style')).toContain('color: red');
  });
});

describe('static artifact isolation', () => {
  const maliciousArtifact = `
    <strong id="safe">Static</strong>
    <a id="javascript" href="javascript:parent.document.body.dataset.xss=1">bad</a>
    <a id="data" href="data:text/html,bad">data</a>
    <a id="network" href="https://attacker.invalid/open">network</a>
    <img src="https://attacker.invalid/pixel" onerror="parent.document.body.dataset.xss=2">
    <style>@import url(https://attacker.invalid/style.css);</style>
    <script>fetch('https://attacker.invalid/fetch'); window.open('https://attacker.invalid');</script>
  `;

  it('returns sanitized static HTML with a restrictive CSP and no external URLs', () => {
    const content = parseFragment(sanitizeArtifactContent(maliciousArtifact, 'html'));
    const standalone = buildStaticArtifactDocument(maliciousArtifact, 'html', '<img onerror=alert(1)>');

    expect(content.querySelector('#safe')?.textContent).toBe('Static');
    expect(content.querySelector('script')).toBeNull();
    expect(content.querySelector('style')).toBeNull();
    expect(content.querySelector('[onerror]')).toBeNull();
    expect(content.querySelectorAll('a[href]')).toHaveLength(0);
    expect(content.querySelector('img')?.hasAttribute('src')).toBe(false);
    expect(standalone).toContain(`content="${STATIC_ARTIFACT_CSP}"`);
    expect(standalone).not.toContain('attacker.invalid');
    expect(standalone).not.toContain('<script>');
  });

  it('renders JavaScript artifacts as escaped source', () => {
    const source = '<script>window.parent.document.body.dataset.xss = 1</script>';
    const content = sanitizeArtifactContent(source, 'application/javascript');
    const root = parseFragment(content);

    expect(root.querySelector('script')).toBeNull();
    expect(root.querySelector('pre code')?.textContent).toBe(source);
  });

  it('uses an empty iframe sandbox and a static fullscreen instead of a popup', () => {
    const open = vi.spyOn(window, 'open');
    const renderer = new ArtifactComponentRenderer();
    const element = renderer.render(component('artifact', {
      artifact_id: 'artifact-1',
      artifact_type: 'html',
      content: maliciousArtifact,
      external_renderable: true,
      fullscreen_capable: true,
      title: 'Static artifact',
    }));
    document.body.append(element);

    const frame = element.querySelector('iframe') as HTMLIFrameElement;
    expect(frame.getAttribute('sandbox')).toBe('');
    expect(frame.srcdoc).toContain("script-src 'none'");
    expect(frame.srcdoc).not.toContain('attacker.invalid');

    (element.querySelector('.external-btn') as HTMLButtonElement).click();
    const fullscreenFrame = document.querySelector('.fullscreen-iframe') as HTMLIFrameElement;
    expect(open).not.toHaveBeenCalled();
    expect(fullscreenFrame.getAttribute('sandbox')).toBe('');
  });
});
