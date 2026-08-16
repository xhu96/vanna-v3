import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  embed: vi.fn().mockResolvedValue({}),
  newPlot: vi.fn().mockResolvedValue(undefined),
  relayout: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('plotly.js-dist-min', () => ({
  default: {
    newPlot: mocks.newPlot,
    relayout: mocks.relayout,
  },
}));

vi.mock('vega-embed', () => ({ default: mocks.embed }));

import { PlotlyChart } from '../../src/components/plotly-chart';
import { VegaLiteChart } from '../../src/components/vega-lite-chart';

beforeEach(() => {
  mocks.embed.mockClear();
  mocks.newPlot.mockClear();
  mocks.relayout.mockClear();
});

afterEach(() => {
  document.body.replaceChildren();
});

describe('chart renderer security config', () => {
  it('passes sanitized Plotly data with non-overridable safe config', async () => {
    const element = new PlotlyChart();
    element.data = [{
      name: '<img src=x onerror=alert(1)>Series',
      x: ['A'],
      y: [1],
    }];
    element.layout = {
      images: [{ source: 'https://attacker.invalid/image.svg' }],
      title: { text: '<script>alert(1)</script>Safe title' },
    };
    element.config = {
      displayModeBar: true,
      plotlyServerURL: 'https://attacker.invalid',
      responsive: false,
      showLink: true,
    };
    document.body.append(element);

    await element.updateComplete;
    const internal = element as unknown as {
      _renderChart: () => Promise<void>;
      plotlyDiv: HTMLElement;
    };
    internal.plotlyDiv = document.createElement('div');
    expect(element.data).toHaveLength(1);
    expect(element.loading).toBe(false);
    expect(element.error).toBe('');
    await internal._renderChart();
    expect(element.error).toBe('');
    await vi.waitFor(() => expect(mocks.newPlot).toHaveBeenCalled());

    const [, data, layout, config] = mocks.newPlot.mock.calls.at(-1)!;
    expect(data[0].name).toBe('Series');
    expect(layout.title.text).toBe('Safe title');
    expect(layout).not.toHaveProperty('images');
    expect(config).toMatchObject({
      displayModeBar: false,
      plotlyServerURL: '',
      responsive: true,
      showLink: false,
    });
  });

  it('uses AST evaluation, rejects external loads, and sanitizes Vega specs', async () => {
    const element = new VegaLiteChart();
    element.spec = {
      data: { url: 'https://attacker.invalid/data.json' },
      encoding: {
        href: { field: 'link' },
        x: { field: 'category', type: 'nominal' },
        y: { field: 'value', type: 'quantitative' },
      },
      mark: 'bar',
      title: '<img src=x onerror=alert(1)>Safe chart',
    };
    element.chartData = [{ category: 'A', link: 'javascript:alert(1)', value: 1 }];
    document.body.append(element);

    await element.updateComplete;
    await vi.waitFor(() => expect(mocks.embed).toHaveBeenCalled());

    const [, spec, options] = mocks.embed.mock.calls.at(-1)!;
    expect(spec.title).toBe('Safe chart');
    expect(spec.data).not.toHaveProperty('url');
    expect(spec.data.values).toEqual([
      { category: 'A', link: 'javascript:alert(1)', value: 1 },
    ]);
    expect(spec.encoding).not.toHaveProperty('href');
    expect(options).toMatchObject({
      actions: false,
      ast: true,
      hover: false,
      renderer: 'svg',
      tooltip: false,
    });
    await expect(options.loader.load('https://attacker.invalid/data.json')).rejects.toThrow(
      'External Vega resource blocked'
    );
  });
});
