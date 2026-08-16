import { describe, expect, it } from 'vitest';
import {
  normalizeV3Event,
  parseV3Event,
  parseV3PollResponse,
  V3EventSequenceValidator,
  V3ProtocolError,
  V3RemoteError,
  validateChartSpec,
} from '../../src/types/events-v3';

function envelope(eventType: string, payload: Record<string, unknown>, sequence = 0) {
  return {
    event_version: 'v3',
    event_type: eventType,
    event_id: `evt_${sequence}`,
    sequence,
    conversation_id: 'conv_1',
    request_id: 'req_1',
    timestamp: '2026-08-11T12:00:00.000Z',
    payload,
  };
}

function chartSpec() {
  return {
    format: 'vega-lite',
    schema_version: 'v5-safe-1',
    spec: {
      $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
      mark: 'bar',
      encoding: {
        x: { field: 'month', type: 'nominal' },
        y: { field: 'revenue', type: 'quantitative' },
      },
    },
    dataset: [{ month: '2026-01', revenue: 12.5 }],
    metadata: { row_count: 1, columns: ['month', 'revenue'] },
  };
}

function lineagePayload() {
  return {
    evidence: {
      schema_version: 1,
      schema_snapshot_id: 'snap_1',
      schema_hash: 'sha256:abc',
      schema_drifted: false,
      semantic: { coverage: 'full', metric_names: ['revenue'] },
      retrieved_sources: [{ id: 'memory_1', kind: 'memory', score: 0.9 }],
      tool_calls: [{ name: 'semantic_query', success: true, runtime_ms: 4 }],
      sql_executions: [],
      validation_checks: [{ name: 'row_shape', passed: true }],
      confidence: { tier: 'High', signals: ['semantic_full'] },
    },
  };
}

describe('V3 event validation', () => {
  it.each([
    ['status', { stage: 'planning', message: 'Planning' }],
    ['assistant_text', { text: 'Revenue increased.', delta: false }],
    ['table_result', { columns: ['revenue'], rows: [{ revenue: 12 }], row_count: 1, truncated: false }],
    ['chart_spec', { chart_spec: chartSpec() }],
    ['component', { component_kind: 'code', data: { language: 'sql', text: 'SELECT 1' } }],
    ['warning', { code: 'semantic_coverage_missing', message: 'SQL fallback.', fallback: 'sql' }],
    ['lineage', lineagePayload()],
    ['error', { code: 'internal_error', message: 'Unexpected error.', correlation_id: 'err_1', retryable: false }],
    ['done', { status: 'completed', event_count: 1 }],
  ])('accepts a closed %s payload', (eventType, payload) => {
    expect(parseV3Event(envelope(eventType, payload)).event_type).toBe(eventType);
  });

  it('rejects unknown envelope and payload fields', () => {
    expect(() => parseV3Event({
      ...envelope('assistant_text', { text: 'safe', delta: false }),
      debug: 'secret',
    })).toThrow(V3ProtocolError);
    expect(() => parseV3Event(envelope('assistant_text', {
      text: 'safe',
      delta: false,
      html: '<script>alert(1)</script>',
    }))).toThrow(V3ProtocolError);
  });

  it.each([
    { ...chartSpec(), spec: { ...chartSpec().spec, url: 'https://attacker.invalid/data' } },
    { ...chartSpec(), spec: { ...chartSpec().spec, title: '<img onerror=alert(1)>' } },
    { ...chartSpec(), spec: { ...chartSpec().spec, transform: [{ calculate: 'window.top' }] } },
    { ...chartSpec(), dataset: [{ revenue: Number.POSITIVE_INFINITY }], metadata: { row_count: 1, columns: ['revenue'] } },
    { ...chartSpec(), dataset: { reference: 'ds_unresolved' } },
  ])('rejects dangerous or non-finite ChartSpecs', (spec) => {
    expect(() => validateChartSpec(spec)).toThrow(V3ProtocolError);
  });

  it('rejects malformed timestamps, identifiers, and discriminators', () => {
    expect(() => parseV3Event({
      ...envelope('done', { status: 'completed', event_count: 1 }),
      timestamp: '2026-08-11T12:00:00',
    })).toThrow(V3ProtocolError);
    expect(() => parseV3Event({
      ...envelope('done', { status: 'completed', event_count: 1 }),
      request_id: 'bad\nvalue',
    })).toThrow(V3ProtocolError);
    expect(() => parseV3Event(envelope('unknown', {}))).toThrow(V3ProtocolError);
  });
});

describe('V3 terminal state and normalization', () => {
  it('enforces contiguous sequences, stable IDs, and one terminal', () => {
    const sequence = new V3EventSequenceValidator();
    sequence.accept(parseV3Event(envelope('assistant_text', { text: 'safe', delta: false }, 0)));
    sequence.accept(parseV3Event(envelope('lineage', lineagePayload(), 1)));
    sequence.accept(parseV3Event(envelope('done', { status: 'completed', event_count: 3 }, 2)));
    expect(() => sequence.accept(parseV3Event(envelope('done', { status: 'completed', event_count: 4 }, 3)))).toThrow(V3ProtocolError);
    expect(() => new V3EventSequenceValidator().assertTerminal()).toThrow(V3ProtocolError);

    const missingLineage = new V3EventSequenceValidator();
    expect(() => missingLineage.accept(parseV3Event(envelope('done', { status: 'completed', event_count: 1 })))).toThrow(V3ProtocolError);

    const afterLineage = new V3EventSequenceValidator();
    afterLineage.accept(parseV3Event(envelope('lineage', lineagePayload(), 0)));
    expect(() => afterLineage.accept(parseV3Event(
      envelope('assistant_text', { text: 'too late', delta: false }, 1),
    ))).toThrow(V3ProtocolError);
  });

  it('validates poll terminal placement and root identifiers', () => {
    const parsed = parseV3PollResponse({
      event_version: 'v3',
      conversation_id: 'conv_1',
      request_id: 'req_1',
      events: [
        envelope('assistant_text', { text: 'safe', delta: false }, 0),
        envelope('lineage', lineagePayload(), 1),
      ],
      terminal_event: envelope('done', { status: 'completed', event_count: 3 }, 2),
    });
    expect(parsed.terminal_event.event_type).toBe('done');

    expect(() => parseV3PollResponse({
      event_version: 'v3',
      conversation_id: 'conv_1',
      request_id: 'req_1',
      events: [
        envelope('lineage', lineagePayload(), 0),
        envelope('assistant_text', { text: 'too late', delta: false }, 1),
      ],
      terminal_event: envelope('done', { status: 'completed', event_count: 3 }, 2),
    })).toThrow(V3ProtocolError);

    expect(() => parseV3PollResponse({
      event_version: 'v3',
      conversation_id: 'conv_other',
      request_id: 'req_1',
      events: [],
      terminal_event: envelope('done', { status: 'completed', event_count: 1 }, 0),
    })).toThrow(V3ProtocolError);
  });

  it('normalizes model text and artifact source as inert text components', () => {
    const text = normalizeV3Event(parseV3Event(envelope('assistant_text', {
      text: '<img src=x onerror=alert(1)>',
      delta: false,
    })));
    const artifact = normalizeV3Event(parseV3Event(envelope('component', {
      component_kind: 'artifact',
      data: {
        representation: 'text',
        content: '<script>window.top.pwned=true</script>',
      },
    })));

    expect(text?.rich).toMatchObject({
      type: 'text',
      data: { content: '<img src=x onerror=alert(1)>', markdown: false },
    });
    expect(artifact?.rich).toMatchObject({
      type: 'text',
      data: { content: '<script>window.top.pwned=true</script>', code_language: 'text' },
    });
  });

  it('turns a typed terminal error into a redacted public error', () => {
    const error = parseV3Event(envelope('error', {
      code: 'query_policy_rejected',
      message: 'The query could not be executed safely.',
      correlation_id: 'err_public',
      retryable: false,
    }));

    expect(() => normalizeV3Event(error)).toThrow(V3RemoteError);
    try {
      normalizeV3Event(error);
    } catch (caught) {
      expect(caught).toMatchObject({
        code: 'query_policy_rejected',
        correlationId: 'err_public',
        retryable: false,
      });
    }
  });
});
