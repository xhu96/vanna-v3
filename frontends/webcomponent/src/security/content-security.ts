import DOMPurify from 'dompurify';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';

export type ContentProfile = 'ui' | 'rich-text' | 'chart' | 'artifact';

const HTML_TAGS = [
  'a', 'abbr', 'article', 'aside', 'b', 'blockquote', 'br', 'button', 'caption',
  'code', 'col', 'colgroup', 'dd', 'del', 'details', 'div', 'dl', 'dt', 'em',
  'figcaption', 'figure', 'footer', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'header', 'hr', 'i', 'img', 'input', 'kbd', 'li', 'main', 'mark', 'nav',
  'ol', 'p', 'pre', 'q', 's', 'samp', 'section', 'small', 'span', 'strong',
  'sub', 'summary', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead',
  'tr', 'u', 'ul', 'var',
];

const SVG_TAGS = [
  'circle', 'clippath', 'defs', 'desc', 'ellipse', 'g', 'lineargradient',
  'line', 'mask', 'path', 'pattern', 'polygon', 'polyline', 'radialgradient',
  'rect', 'stop', 'svg', 'symbol', 'text', 'title', 'tspan', 'use',
];

const UI_TAGS = [...HTML_TAGS, ...SVG_TAGS];
const RICH_TEXT_TAGS = [
  'a', 'abbr', 'b', 'blockquote', 'br', 'code', 'dd', 'del', 'div', 'dl',
  'dt', 'em', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'hr', 'i', 'img',
  'kbd', 'li', 'mark', 'ol', 'p', 'pre', 'q', 's', 'samp', 'small', 'span',
  'strong', 'sub', 'sup', 'table', 'tbody', 'td', 'tfoot', 'th', 'thead',
  'tr', 'u', 'ul', 'var',
];
const CHART_TAGS = ['b', 'br', 'em', 'i', 's', 'span', 'strong', 'sub', 'sup', 'u'];

const HTML_ATTRIBUTES = [
  'alt', 'checked', 'cite', 'class', 'colspan', 'datetime', 'dir', 'disabled',
  'download', 'height', 'href', 'id', 'lang', 'open', 'placeholder', 'rel',
  'role', 'rowspan', 'scope', 'src', 'style', 'tabindex', 'target', 'title',
  'type', 'value', 'width',
];

const SVG_ATTRIBUTES = [
  'clip-path', 'clip-rule', 'cx', 'cy', 'd', 'dx', 'dy', 'fill', 'fill-opacity',
  'fill-rule', 'font-family', 'font-size', 'font-style', 'font-weight', 'fx',
  'fy', 'gradienttransform', 'gradientunits', 'height', 'href', 'id', 'mask',
  'offset', 'opacity', 'patterncontentunits', 'patterntransform', 'patternunits',
  'points', 'preserveaspectratio', 'r', 'rx', 'ry', 'spreadmethod', 'stop-color',
  'stop-opacity', 'stroke', 'stroke-dasharray', 'stroke-linecap',
  'stroke-linejoin', 'stroke-miterlimit', 'stroke-opacity', 'stroke-width',
  'style', 'text-anchor', 'transform', 'viewbox', 'width', 'x', 'x1', 'x2',
  'xlink:href', 'xmlns', 'y', 'y1', 'y2',
];

const ALLOWED_URL = /^(?:(?:https?|mailto):|[#/?]|\.{1,2}\/|[a-z0-9._~-]+(?:[/?#]|$))/i;
const ACTIVE_CSS = /(?:url\s*\(|image-set\s*\(|@import|@font-face|@namespace|expression\s*\(|behavior\s*:|-moz-binding\s*:|\\)/i;
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f-\u009f]/g;
const URL_ATTRIBUTES = new Set(['cite', 'href', 'src', 'xlink:href']);
const FORBIDDEN_OBJECT_KEYS = new Set(['__proto__', 'constructor', 'prototype']);
const VEGA_RESOURCE_KEYS = new Set(['href', 'src', 'srcset', 'url']);
const VEGA_UNSAFE_KEYS = new Set([
  'calculate', 'condition', 'expr', 'facet', 'filter', 'hconcat', 'layer',
  'params', 'repeat', 'resolve', 'selection', 'transform', 'vconcat',
]);
const PLOTLY_RESOURCE_KEYS = new Set([
  'href', 'mapboxaccesstoken', 'plotlyserverurl', 'source', 'src', 'topojsonurl', 'url',
]);
const PLOTLY_UNSAFE_KEYS = new Set(['geo', 'images', 'map', 'mapbox']);
const SAFE_PLOTLY_TRACE_TYPES = new Set(['bar', 'pie', 'scatter']);
const UI_STYLE_PROPERTIES = new Set([
  'color', 'font-size', 'font-style', 'font-weight', 'text-align', 'width',
]);
const JAVASCRIPT_ARTIFACT_TYPES = new Set([
  'd3', 'javascript', 'js', 'three', 'threejs', 'ts', 'typescript',
]);
const DROP_WITH_CONTENT = new Set([
  'base', 'embed', 'form', 'iframe', 'link', 'math', 'meta', 'object', 'script',
  'template',
]);

const PROFILE_TAGS: Record<ContentProfile, string[]> = {
  artifact: [...UI_TAGS, 'style'],
  chart: CHART_TAGS,
  'rich-text': RICH_TEXT_TAGS,
  ui: UI_TAGS,
};

const PROFILE_ATTRIBUTES: Record<ContentProfile, string[]> = {
  artifact: [...HTML_ATTRIBUTES, ...SVG_ATTRIBUTES],
  chart: ['class'],
  'rich-text': HTML_ATTRIBUTES,
  ui: [...HTML_ATTRIBUTES, ...SVG_ATTRIBUTES],
};

export const STATIC_ARTIFACT_CSP = [
  "default-src 'none'",
  "base-uri 'none'",
  "connect-src 'none'",
  "font-src 'none'",
  "form-action 'none'",
  "frame-src 'none'",
  "child-src 'none'",
  "img-src 'none'",
  "manifest-src 'none'",
  "media-src 'none'",
  "navigate-to 'none'",
  "object-src 'none'",
  "script-src 'none'",
  "style-src 'unsafe-inline'",
  "worker-src 'none'",
].join('; ');

function asString(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

export function escapeHtmlText(value: unknown): string {
  return asString(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function sanitizeUrl(value: string, profile: ContentProfile, resource: boolean): string | null {
  const normalized = value.replace(CONTROL_CHARACTERS, '').trim();
  if (!normalized || normalized.startsWith('\\')) {
    return null;
  }

  if (profile === 'artifact') {
    return /^#[a-z0-9_.:-]+$/i.test(normalized) ? normalized : null;
  }

  // Model-controlled rich content must not trigger browser requests by itself.
  if (resource) {
    return /^#[a-z0-9_.:-]+$/i.test(normalized) ? normalized : null;
  }

  if (!ALLOWED_URL.test(normalized)) {
    return null;
  }

  const scheme = normalized.match(/^([a-z][a-z0-9+.-]*):/i)?.[1]?.toLowerCase();
  if (scheme && scheme !== 'http' && scheme !== 'https' && (!resource && scheme !== 'mailto')) {
    return null;
  }

  return normalized;
}

function sanitizeUiStyle(value: string): string | null {
  const safeDeclarations: string[] = [];
  for (const declaration of value.split(';')) {
    const separator = declaration.indexOf(':');
    if (separator < 1) continue;

    const property = declaration.slice(0, separator).trim().toLowerCase();
    const rawValue = declaration.slice(separator + 1).trim();
    if (!UI_STYLE_PROPERTIES.has(property) || !rawValue || ACTIVE_CSS.test(rawValue)) {
      continue;
    }

    let safe = false;
    if (property === 'width') {
      const match = rawValue.match(/^(\d+(?:\.\d+)?)%$/);
      safe = Boolean(match && Number(match[1]) >= 0 && Number(match[1]) <= 100);
    } else if (property === 'font-size') {
      const match = rawValue.match(/^(\d+(?:\.\d+)?)(px|em|rem|%)$/i);
      safe = Boolean(match && Number(match[1]) >= 0 && Number(match[1]) <= 200);
    } else if (property === 'font-style') {
      safe = /^(?:italic|normal|oblique)$/i.test(rawValue);
    } else if (property === 'font-weight') {
      safe = /^(?:normal|bold|[1-9]00)$/i.test(rawValue);
    } else if (property === 'text-align') {
      safe = /^(?:start|end|left|right|center|justify)$/i.test(rawValue);
    } else if (property === 'color') {
      safe = /^(?:#[0-9a-f]{3,8}|[a-z]{1,32}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%]+\))$/i.test(rawValue);
    }

    if (safe) safeDeclarations.push(`${property}: ${rawValue}`);
  }
  return safeDeclarations.length > 0 ? safeDeclarations.join('; ') : null;
}

function hardenSanitizedFragment(fragment: ParentNode, profile: ContentProfile): void {
  const allowedTags = new Set(PROFILE_TAGS[profile]);
  const allowedAttributes = new Set(PROFILE_ATTRIBUTES[profile]);

  Array.from(fragment.querySelectorAll('*')).forEach((element) => {
    const tagName = element.localName.toLowerCase();
    if (!allowedTags.has(tagName)) {
      if (DROP_WITH_CONTENT.has(tagName)) {
        element.remove();
      } else {
        element.replaceWith(...Array.from(element.childNodes));
      }
      return;
    }

    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();

      const isAria = /^aria-[a-z0-9_.:-]+$/i.test(name);
      const isData = profile === 'ui' && /^data-[a-z0-9_.:-]+$/i.test(name);
      if (
        (!allowedAttributes.has(name) && !isAria && !isData) ||
        name.startsWith('on') ||
        name === 'srcdoc' ||
        name === 'srcset'
      ) {
        element.removeAttribute(attribute.name);
        continue;
      }

      if (URL_ATTRIBUTES.has(name)) {
        const isUserNavigation = name === 'href' && tagName === 'a';
        const isPassiveCitation = name === 'cite';
        const safeUrl = sanitizeUrl(
          attribute.value,
          profile,
          !isUserNavigation && !isPassiveCitation,
        );
        if (safeUrl === null) {
          element.removeAttribute(attribute.name);
        } else {
          element.setAttribute(attribute.name, safeUrl);
        }
      }

      if (name === 'style') {
        if (profile === 'artifact') {
          if (ACTIVE_CSS.test(attribute.value)) element.removeAttribute(attribute.name);
        } else if (profile === 'ui') {
          const safeStyle = sanitizeUiStyle(attribute.value);
          if (safeStyle === null) {
            element.removeAttribute(attribute.name);
          } else {
            element.setAttribute(attribute.name, safeStyle);
          }
        } else {
          element.removeAttribute(attribute.name);
        }
      }

      if (['clip-path', 'fill', 'filter', 'mask', 'stroke'].includes(name)) {
        const references = attribute.value.match(/url\s*\((.*?)\)/gi) ?? [];
        if (
          attribute.value.includes('\\') ||
          references.some((reference) => !/^url\s*\(\s*['"]?#[a-z0-9_.:-]+['"]?\s*\)$/i.test(reference))
        ) {
          element.removeAttribute(attribute.name);
        }
      }
    }

    if (tagName === 'style' && ACTIVE_CSS.test(element.textContent ?? '')) {
      element.remove();
      return;
    }

    if (tagName === 'a') {
      if (profile === 'artifact') {
        element.removeAttribute('download');
        element.removeAttribute('target');
        element.setAttribute('rel', 'noreferrer noopener');
      } else if (element.getAttribute('target') === '_blank') {
        element.setAttribute('rel', 'noreferrer noopener');
      } else if (element.hasAttribute('target')) {
        element.setAttribute('target', '_self');
      }
    }
  });
}

function stripExecutableElements(value: string): string {
  let output = value.replace(/\0/g, '');
  for (const tagName of DROP_WITH_CONTENT) {
    const pairedTag = new RegExp(
      `<\\s*${tagName}\\b[^>]*>[\\s\\S]*?<\\s*\\/\\s*${tagName}\\s*>`,
      'gi'
    );
    let previous: string;
    do {
      previous = output;
      output = output.replace(pairedTag, '');
    } while (output !== previous);
    output = output.replace(new RegExp(`<\\s*\\/?\\s*${tagName}\\b[^>]*>`, 'gi'), '');
  }
  return output;
}

function structurallySanitize(value: string, profile: ContentProfile): string {
  const template = document.createElement('template');
  template.innerHTML = stripExecutableElements(value);
  hardenSanitizedFragment(template.content, profile);
  return template.innerHTML;
}

export function sanitizeHtml(value: unknown, profile: ContentProfile = 'rich-text'): string {
  // Pre-sanitize structurally so DOM shims that DOMPurify cannot support never see active nodes.
  const structurallySafe = structurallySanitize(asString(value), profile);
  if (!DOMPurify.isSupported) {
    return structurallySafe;
  }

  const purified = DOMPurify.sanitize(structurallySafe, {
    ALLOWED_ATTR: PROFILE_ATTRIBUTES[profile],
    ALLOWED_TAGS: PROFILE_TAGS[profile],
    ALLOWED_URI_REGEXP: ALLOWED_URL,
    ALLOW_ARIA_ATTR: true,
    ALLOW_DATA_ATTR: profile === 'ui',
    ALLOW_UNKNOWN_PROTOCOLS: false,
    FORBID_ATTR: ['formaction', 'ping', 'srcdoc', 'srcset'],
    FORBID_TAGS: [...DROP_WITH_CONTENT],
    KEEP_CONTENT: true,
    RETURN_TRUSTED_TYPE: false,
    SAFE_FOR_XML: true,
  });

  return structurallySanitize(String(purified), profile);
}

export function setSanitizedHtml(
  element: Element,
  value: unknown,
  profile: ContentProfile = 'ui'
): void {
  element.innerHTML = sanitizeHtml(value, profile);
}

export function renderSanitizedHtml(value: unknown, profile: ContentProfile = 'rich-text') {
  return unsafeHTML(sanitizeHtml(value, profile));
}

export function sanitizePlainText(value: unknown): string {
  const template = document.createElement('template');
  template.innerHTML = sanitizeHtml(value, 'chart');
  return template.content.textContent ?? '';
}

export function renderSanitizedMarkdown(value: unknown): string {
  const markdown = escapeHtmlText(value);
  const rendered = markdown
    .replace(/^### (.*$)/gm, '<h3>$1</h3>')
    .replace(/^## (.*$)/gm, '<h2>$1</h2>')
    .replace(/^# (.*$)/gm, '<h1>$1</h1>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/^- (.*$)/gm, '<li>$1</li>')
    .replace(/((?:<li>.*<\/li>\n?)+)/g, '<ul>$1</ul>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<(?:h[1-6]|ul|li|p|pre|blockquote)\b)(.+)$/gm, '<p>$1</p>');

  return sanitizeHtml(rendered, 'rich-text');
}

type ChartMode = 'plotly' | 'vega-data' | 'vega-spec';

interface ChartWalkState {
  nodes: number;
  seen: WeakSet<object>;
}

function sanitizeChartText(value: string, mode: ChartMode): string {
  const sanitized = sanitizeHtml(value, 'chart');
  if (mode === 'plotly') {
    return sanitized;
  }

  const template = document.createElement('template');
  template.innerHTML = sanitized;
  return template.content.textContent ?? '';
}

function shouldDropChartKey(key: string, mode: ChartMode): boolean {
  const normalized = key.toLowerCase();
  if (FORBIDDEN_OBJECT_KEYS.has(normalized)) {
    return true;
  }
  if (mode === 'vega-spec') {
    return VEGA_RESOURCE_KEYS.has(normalized)
      || VEGA_UNSAFE_KEYS.has(normalized)
      || normalized.endsWith('expr');
  }
  if (mode === 'plotly') {
    return PLOTLY_RESOURCE_KEYS.has(normalized)
      || PLOTLY_UNSAFE_KEYS.has(normalized)
      || normalized.endsWith('src');
  }
  return false;
}

function sanitizeChartNode(
  value: unknown,
  mode: ChartMode,
  depth: number,
  state: ChartWalkState
): unknown {
  state.nodes += 1;
  if (state.nodes > 550_000 || depth > 40) {
    throw new Error('Chart payload exceeds the safe rendering limit');
  }

  if (typeof value === 'string') {
    return sanitizeChartText(value, mode);
  }
  if (typeof value === 'number' && !Number.isFinite(value)) {
    throw new Error('Chart payload numbers must be finite');
  }
  if (value === null || typeof value === 'boolean' || typeof value === 'number') {
    return value;
  }
  if (value instanceof Date) {
    return new Date(value.getTime());
  }
  if (Array.isArray(value)) {
    if (value.length > 5_000) {
      throw new Error('Chart arrays must not exceed 5,000 items');
    }
    return value.map((item) => sanitizeChartNode(item, mode, depth + 1, state));
  }
  if (!value || typeof value !== 'object') {
    return null;
  }
  if (state.seen.has(value)) {
    throw new Error('Chart payload must not contain circular references');
  }

  state.seen.add(value);
  const entries = Object.entries(value);
  if (entries.length > 100) {
    throw new Error('Chart objects must not exceed 100 fields');
  }
  const output: Record<string, unknown> = {};
  for (const [key, child] of entries) {
    if (!shouldDropChartKey(key, mode)) {
      output[key] = sanitizeChartNode(child, mode, depth + 1, state);
    }
  }
  state.seen.delete(value);
  return output;
}

function sanitizeChartObject<T>(value: T, mode: ChartMode): T {
  let serialized: string;
  try {
    serialized = JSON.stringify(value);
  } catch {
    throw new Error('Chart payload must be serializable JSON');
  }
  if (new TextEncoder().encode(serialized ?? '').byteLength > 2 * 1024 * 1024) {
    throw new Error('Chart payload exceeds the 2 MiB rendering limit');
  }
  return sanitizeChartNode(value, mode, 0, { nodes: 0, seen: new WeakSet() }) as T;
}

export function sanitizePlotlyValue<T>(value: T): T {
  return sanitizeChartObject(value, 'plotly');
}

export function sanitizePlotlyData(value: unknown): Array<Record<string, unknown>> {
  const traces = sanitizePlotlyValue(value);
  if (!Array.isArray(traces)) {
    throw new Error('Plotly data must be an array');
  }
  return traces.map((trace) => {
    if (!trace || typeof trace !== 'object' || Array.isArray(trace)) {
      throw new Error('Plotly traces must be objects');
    }
    const normalized = trace as Record<string, unknown>;
    const type = normalized.type ?? 'scatter';
    if (typeof type !== 'string' || !SAFE_PLOTLY_TRACE_TYPES.has(type.toLowerCase())) {
      throw new Error(`Plotly trace type is not allowed: ${String(type)}`);
    }
    return normalized;
  });
}

export function sanitizeVegaSpec(value: Record<string, unknown>): Record<string, unknown> {
  return sanitizeChartObject(value, 'vega-spec');
}

export function sanitizeVegaData<T>(value: T): T {
  return sanitizeChartObject(value, 'vega-data');
}

export const SAFE_PLOTLY_CONFIG = Object.freeze({
  displayModeBar: false,
  mapboxAccessToken: '',
  plotlyServerURL: '',
  responsive: true,
  showLink: false,
  showSendToCloud: false,
});

export function buildSafePlotlyConfig(value: unknown): Record<string, unknown> {
  const requested = sanitizePlotlyValue(
    value && typeof value === 'object' ? value as Record<string, unknown> : {}
  );
  return { ...requested, ...SAFE_PLOTLY_CONFIG };
}

export function isJavaScriptArtifactType(type: unknown): boolean {
  const normalized = asString(type).trim().toLowerCase();
  return JAVASCRIPT_ARTIFACT_TYPES.has(normalized) || /(?:java|type)script/.test(normalized);
}

export function sanitizeArtifactContent(content: unknown, type: unknown): string {
  if (isJavaScriptArtifactType(type)) {
    return `<pre class="artifact-source"><code>${escapeHtmlText(content)}</code></pre>`;
  }
  return sanitizeHtml(content, 'artifact');
}

export function buildStaticArtifactDocument(
  content: unknown,
  type: unknown,
  title: unknown = 'Artifact'
): string {
  const safeTitle = escapeHtmlText(title || 'Artifact');
  const safeContent = sanitizeArtifactContent(content, type);

  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="${STATIC_ARTIFACT_CSP}">
  <meta name="referrer" content="no-referrer">
  <title>${safeTitle}</title>
  <style>
    html, body { margin: 0; min-height: 100%; }
    body { box-sizing: border-box; padding: 20px; font-family: sans-serif; }
    *, *::before, *::after { box-sizing: inherit; }
    .artifact-source { margin: 0; overflow: auto; white-space: pre-wrap; }
  </style>
</head>
<body><main class="artifact-container">${safeContent}</main></body>
</html>`;
}
