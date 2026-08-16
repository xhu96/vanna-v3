# Vanna Web Component

`@vanna/webcomponent` is the optional, framework-agnostic Vanna analysis
workbench. It defaults to the V2 protocol and supports typed V3 SSE or poll
events when `api-version="v3"` is selected explicitly.

## Interface System

The interactive control layer uses Adobe Spectrum Web Components 1.12.2:

- `sp-theme` with the Spectrum 2 light/dark and medium-scale fragments;
- `sp-textfield` for the accessible multiline question composer;
- `sp-button` and `sp-action-button` for primary and quiet actions;
- `sp-progress-circle` for bounded working states.

Vanna owns the application shell, answer layout, evidence record, tables,
ChartSpec renderers, security states, and responsive composition. IBM Plex Sans
and IBM Plex Mono are packaged with the build. No UI dependency, font, chart
data, or runtime asset is fetched from a third-party CDN.

The dependency licenses are permissive and compatible with the MIT project:
Spectrum component packages are Apache-2.0 (the theme package is ISC), and IBM
Plex font packages are OFL-1.1.

## Usage

```html
<script type="module" src="/assets/vanna-components.js"></script>

<!-- Existing behavior remains the default. -->
<vanna-chat api-version="v2"></vanna-chat>

<!-- Typed V3 SSE/poll support is explicit. -->
<vanna-chat api-version="v3" transport="sse"></vanna-chat>
```

Authentication headers can be supplied with `setCustomHeaders()`. Prefer
same-origin cookies or short-lived gateway-issued tokens and never log the
configured header values.

## Development

Use Node 20.19 and npm 10 as pinned by `.nvmrc` and `package.json`.

```bash
npm ci
npm test
npm run test:e2e
npm run build-storybook
```

The product overview and animated tour are in
`src/components/vanna-product-tour.stories.ts`. `npm run media:tour` records the
current local Storybook build into the repository-level `media/` directory.
