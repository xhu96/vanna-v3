import type { ChatStreamChunk } from '../services/api-client';

export type JsonScalar = string | number | boolean | null;
export type V3EventType =
  | 'status'
  | 'assistant_text'
  | 'table_result'
  | 'chart_spec'
  | 'component'
  | 'warning'
  | 'lineage'
  | 'error'
  | 'done';

export interface StatusPayload {
  stage: 'accepted' | 'planning' | 'semantic' | 'sql' | 'validating' | 'rendering';
  message: string;
}

export interface AssistantTextPayload {
  text: string;
  delta: boolean;
}

export interface TableResultPayload {
  columns: string[];
  rows: Array<Record<string, JsonScalar>>;
  row_count: number;
  truncated: boolean;
}

export interface ChartSpec {
  format: 'vega-lite' | 'plotly-json';
  schema_version: 'v5-safe-1' | 'plotly-safe-1';
  spec: Record<string, unknown>;
  dataset: Array<Record<string, JsonScalar>>;
  metadata: {
    row_count: number;
    columns: string[];
    truncated?: boolean;
  };
}

export interface ChartSpecPayload {
  chart_spec: ChartSpec;
}

export type ComponentPayload =
  | { component_kind: 'card'; data: { title: string; body: string } }
  | { component_kind: 'code'; data: { language: string; text: string } }
  | {
      component_kind: 'artifact';
      data: {
        title?: string;
        representation: 'text' | 'sanitized_html';
        content: string;
      };
    };

export interface WarningPayload {
  code: string;
  message: string;
  fallback?: 'sql' | 'none';
}

export interface LineagePayload {
  evidence: {
    schema_version: number | null;
    schema_snapshot_id: string | null;
    schema_hash: string | null;
    schema_drifted: boolean;
    semantic: {
      coverage: 'full' | 'partial' | 'missing' | 'not_applicable';
      metric_names: string[];
      fallback_reason?: string;
    };
    retrieved_sources: Array<{
      id: string;
      kind: 'memory' | 'document';
      score?: number;
    }>;
    tool_calls: Array<{ name: string; success: boolean; runtime_ms?: number }>;
    sql_executions: Array<{
      sql?: string;
      dialect?: string;
      row_count: number;
      runtime_ms?: number;
    }>;
    validation_checks: Array<{ name: string; passed: boolean }>;
    confidence: { tier: 'High' | 'Medium' | 'Low'; signals: string[] };
  };
}

export interface ErrorPayload {
  code: string;
  message: string;
  correlation_id: string;
  retryable: boolean;
}

export interface DonePayload {
  status: 'completed';
  event_count: number;
}

export interface V3PayloadByType {
  status: StatusPayload;
  assistant_text: AssistantTextPayload;
  table_result: TableResultPayload;
  chart_spec: ChartSpecPayload;
  component: ComponentPayload;
  warning: WarningPayload;
  lineage: LineagePayload;
  error: ErrorPayload;
  done: DonePayload;
}

export interface V3EventEnvelope<T extends V3EventType> {
  event_version: 'v3';
  event_type: T;
  event_id: string;
  sequence: number;
  conversation_id: string;
  request_id: string;
  timestamp: string;
  payload: V3PayloadByType[T];
}

export type V3ChatEvent = {
  [T in V3EventType]: V3EventEnvelope<T>;
}[V3EventType];

export interface V3PollResponse {
  event_version: 'v3';
  conversation_id: string;
  request_id: string;
  events: V3ChatEvent[];
  terminal_event: V3ChatEvent;
}

export class V3ProtocolError extends Error {
  constructor(message = 'The server returned an invalid V3 event stream.') {
    super(message);
    this.name = 'V3ProtocolError';
  }
}

export class V3RemoteError extends Error {
  readonly code: string;
  readonly correlationId: string;
  readonly retryable: boolean;

  constructor(payload: ErrorPayload) {
    super(payload.message);
    this.name = 'V3RemoteError';
    this.code = payload.code;
    this.correlationId = payload.correlation_id;
    this.retryable = payload.retryable;
  }
}

type JsonObject = Record<string, unknown>;

const EVENT_TYPES = new Set<V3EventType>([
  'status',
  'assistant_text',
  'table_result',
  'chart_spec',
  'component',
  'warning',
  'lineage',
  'error',
  'done',
]);
const TERMINAL_TYPES = new Set<V3EventType>(['done', 'error']);
const ID_PATTERN = /^[^\u0000-\u001f\u007f]{1,160}$/;
const CODE_PATTERN = /^[a-z][a-z0-9_]{0,127}$/;
const UTC_TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype']);
const BLOCKED_CHART_KEYS = new Set([
  'calculate',
  'expr',
  'expression',
  'expressions',
  'filter',
  'href',
  'script',
  'scripts',
  'signal',
  'signals',
  'transform',
  'transforms',
  'url',
  'urls',
]);
const BLOCKED_CHART_TEXT = /(?:https?:\/\/|ftp:\/\/|file:\/\/|javascript\s*:|vbscript\s*:|data\s*:|\burl\s*\(|\bimage-set\s*\(|@import\b|<\s*\/?\s*(?:script|iframe|object|embed|svg)\b|\bon(?:error|load)\s*=|\beval\s*\(|\bfunction\s*\(|=>)/i;
const VEGA_SCHEMA = 'https://vega.github.io/schema/vega-lite/v5.json';
const MAX_BYTES = 2 * 1024 * 1024;

function invalid(detail: string): never {
  throw new V3ProtocolError(`Invalid V3 payload: ${detail}`);
}

function objectValue(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    invalid(`${label} must be an object`);
  }
  return value as JsonObject;
}

function exactKeys(
  value: JsonObject,
  allowed: readonly string[],
  required: readonly string[],
  label: string,
): void {
  const allowedSet = new Set(allowed);
  for (const key of Object.keys(value)) {
    if (!allowedSet.has(key) || FORBIDDEN_KEYS.has(key)) {
      invalid(`${label} contains an unknown property`);
    }
  }
  for (const key of required) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) {
      invalid(`${label} is missing ${key}`);
    }
  }
}

function stringValue(value: unknown, label: string, max: number, min = 0): string {
  if (typeof value !== 'string' || value.length < min || value.length > max) {
    invalid(`${label} must be a bounded string`);
  }
  return value;
}

function enumValue<T extends string>(
  value: unknown,
  allowed: readonly T[],
  label: string,
): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) {
    invalid(`${label} is not allowed`);
  }
  return value as T;
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== 'boolean') invalid(`${label} must be a boolean`);
  return value;
}

function numberValue(
  value: unknown,
  label: string,
  minimum = Number.NEGATIVE_INFINITY,
  maximum = Number.POSITIVE_INFINITY,
): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < minimum || value > maximum) {
    invalid(`${label} must be a finite number in range`);
  }
  return value;
}

function integerValue(value: unknown, label: string, minimum = 0, maximum?: number): number {
  const numeric = numberValue(value, label, minimum, maximum);
  if (!Number.isInteger(numeric)) invalid(`${label} must be an integer`);
  return numeric;
}

function arrayValue(value: unknown, label: string, max: number, min = 0): unknown[] {
  if (!Array.isArray(value) || value.length < min || value.length > max) {
    invalid(`${label} must be a bounded array`);
  }
  return value;
}

function optionalString(value: unknown, label: string, max: number): void {
  if (value !== undefined) stringValue(value, label, max);
}

function optionalNumber(
  value: unknown,
  label: string,
  minimum = 0,
  maximum = Number.POSITIVE_INFINITY,
): void {
  if (value !== undefined) numberValue(value, label, minimum, maximum);
}

function jsonScalar(value: unknown, label: string): asserts value is JsonScalar {
  if (
    value !== null &&
    typeof value !== 'string' &&
    typeof value !== 'boolean' &&
    (typeof value !== 'number' || !Number.isFinite(value))
  ) {
    invalid(`${label} must be a finite JSON scalar`);
  }
}

function boundedUniqueStrings(value: unknown, label: string, maxItems: number, maxLength: number): string[] {
  const items = arrayValue(value, label, maxItems).map((item, index) =>
    stringValue(item, `${label}[${index}]`, maxLength),
  );
  if (new Set(items).size !== items.length) invalid(`${label} must be unique`);
  return items;
}

function walkSafeChart(value: unknown, path: string[] = [], depth = 0): void {
  if (depth > 32) invalid('chart nesting is too deep');
  if (typeof value === 'string') {
    if (!(path.length === 1 && path[0] === '$schema' && value === VEGA_SCHEMA) && BLOCKED_CHART_TEXT.test(value)) {
      invalid('chart text contains active content');
    }
    return;
  }
  if (typeof value === 'number' && !Number.isFinite(value)) invalid('chart number is not finite');
  if (Array.isArray(value)) {
    for (const child of value) walkSafeChart(child, path, depth + 1);
    return;
  }
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (BLOCKED_CHART_KEYS.has(key.toLowerCase()) || FORBIDDEN_KEYS.has(key.toLowerCase())) {
        invalid('chart contains an active-content property');
      }
      walkSafeChart(child, [...path, key], depth + 1);
    }
  }
}

function validateVegaField(value: unknown, label: string): void {
  const field = objectValue(value, label);
  exactKeys(
    field,
    ['field', 'type', 'title', 'aggregate', 'bin', 'timeUnit', 'sort'],
    ['field', 'type'],
    label,
  );
  stringValue(field.field, `${label}.field`, 512, 1);
  enumValue(field.type, ['quantitative', 'temporal', 'ordinal', 'nominal'], `${label}.type`);
  optionalString(field.title, `${label}.title`, 500);
  if (field.aggregate !== undefined) {
    enumValue(field.aggregate, ['count', 'sum', 'mean', 'median', 'min', 'max', 'distinct'], `${label}.aggregate`);
  }
  if (field.bin !== undefined) booleanValue(field.bin, `${label}.bin`);
  if (field.timeUnit !== undefined) {
    enumValue(field.timeUnit, ['year', 'quarter', 'month', 'week', 'day', 'date', 'hours', 'minutes', 'seconds'], `${label}.timeUnit`);
  }
  if (field.sort !== undefined) enumValue(field.sort, ['ascending', 'descending'], `${label}.sort`);
}

function validateVegaSpec(value: unknown): void {
  const spec = objectValue(value, 'chart.spec');
  exactKeys(spec, ['$schema', 'title', 'description', 'mark', 'encoding', 'width', 'height'], ['$schema', 'mark', 'encoding'], 'chart.spec');
  if (spec.$schema !== VEGA_SCHEMA) invalid('chart.spec.$schema is not the safe Vega-Lite profile');
  optionalString(spec.title, 'chart.spec.title', 500);
  optionalString(spec.description, 'chart.spec.description', 2000);

  if (typeof spec.mark === 'string') {
    enumValue(spec.mark, ['bar', 'line', 'point', 'area', 'arc', 'tick', 'rule'], 'chart.spec.mark');
  } else {
    const mark = objectValue(spec.mark, 'chart.spec.mark');
    exactKeys(mark, ['type', 'point', 'filled', 'opacity', 'color'], ['type'], 'chart.spec.mark');
    enumValue(mark.type, ['bar', 'line', 'point', 'area', 'arc', 'tick', 'rule'], 'chart.spec.mark.type');
    if (mark.point !== undefined) booleanValue(mark.point, 'chart.spec.mark.point');
    if (mark.filled !== undefined) booleanValue(mark.filled, 'chart.spec.mark.filled');
    optionalNumber(mark.opacity, 'chart.spec.mark.opacity', 0, 1);
    optionalString(mark.color, 'chart.spec.mark.color', 128);
  }

  const encoding = objectValue(spec.encoding, 'chart.spec.encoding');
  const channels = ['x', 'y', 'color', 'size', 'theta', 'detail', 'tooltip'] as const;
  exactKeys(encoding, channels, [], 'chart.spec.encoding');
  if (Object.keys(encoding).length === 0) invalid('chart.spec.encoding must not be empty');
  for (const channel of channels) {
    const value = encoding[channel];
    if (value === undefined) continue;
    if (channel === 'tooltip' && Array.isArray(value)) {
      for (const [index, field] of arrayValue(value, 'chart.spec.encoding.tooltip', 20).entries()) {
        validateVegaField(field, `chart.spec.encoding.tooltip[${index}]`);
      }
    } else {
      validateVegaField(value, `chart.spec.encoding.${channel}`);
    }
  }
  if (spec.width !== undefined && spec.width !== 'container') integerValue(spec.width, 'chart.spec.width', 100, 4000);
  if (spec.height !== undefined) integerValue(spec.height, 'chart.spec.height', 100, 2400);
}

function validatePlotlyMarker(value: unknown, label: string): void {
  const marker = objectValue(value, label);
  exactKeys(marker, ['color', 'opacity', 'size'], [], label);
  if (marker.color !== undefined) {
    if (Array.isArray(marker.color)) {
      for (const [index, item] of arrayValue(marker.color, `${label}.color`, 5000).entries()) {
        stringValue(item, `${label}.color[${index}]`, 128);
      }
    } else {
      stringValue(marker.color, `${label}.color`, 128);
    }
  }
  optionalNumber(marker.opacity, `${label}.opacity`, 0, 1);
  if (marker.size !== undefined) {
    if (Array.isArray(marker.size)) {
      for (const [index, item] of arrayValue(marker.size, `${label}.size`, 5000).entries()) {
        numberValue(item, `${label}.size[${index}]`, 0, 500);
      }
    } else {
      numberValue(marker.size, `${label}.size`, 0, 500);
    }
  }
}

function validatePlotlySpec(value: unknown): void {
  const spec = objectValue(value, 'chart.spec');
  exactKeys(spec, ['data', 'layout'], ['data'], 'chart.spec');
  const traces = arrayValue(spec.data, 'chart.spec.data', 20, 1);
  for (const [index, value] of traces.entries()) {
    const label = `chart.spec.data[${index}]`;
    const trace = objectValue(value, label);
    exactKeys(trace, ['type', 'name', 'mode', 'x', 'y', 'labels', 'values', 'orientation', 'marker'], ['type'], label);
    enumValue(trace.type, ['bar', 'scatter', 'pie'], `${label}.type`);
    optionalString(trace.name, `${label}.name`, 500);
    if (trace.mode !== undefined) enumValue(trace.mode, ['lines', 'markers', 'lines+markers'], `${label}.mode`);
    for (const key of ['x', 'y'] as const) {
      if (trace[key] === undefined) continue;
      for (const [itemIndex, item] of arrayValue(trace[key], `${label}.${key}`, 5000).entries()) {
        jsonScalar(item, `${label}.${key}[${itemIndex}]`);
      }
    }
    if (trace.labels !== undefined) {
      for (const [itemIndex, item] of arrayValue(trace.labels, `${label}.labels`, 5000).entries()) {
        stringValue(item, `${label}.labels[${itemIndex}]`, 512);
      }
    }
    if (trace.values !== undefined) {
      for (const [itemIndex, item] of arrayValue(trace.values, `${label}.values`, 5000).entries()) {
        numberValue(item, `${label}.values[${itemIndex}]`);
      }
    }
    if (trace.orientation !== undefined) enumValue(trace.orientation, ['h', 'v'], `${label}.orientation`);
    if (trace.marker !== undefined) validatePlotlyMarker(trace.marker, `${label}.marker`);
  }

  if (spec.layout !== undefined) {
    const layout = objectValue(spec.layout, 'chart.spec.layout');
    exactKeys(layout, ['title', 'xaxis', 'yaxis', 'showlegend', 'barmode', 'width', 'height'], [], 'chart.spec.layout');
    optionalString(layout.title, 'chart.spec.layout.title', 500);
    for (const axisName of ['xaxis', 'yaxis'] as const) {
      if (layout[axisName] === undefined) continue;
      const axis = objectValue(layout[axisName], `chart.spec.layout.${axisName}`);
      exactKeys(axis, ['title', 'type', 'autorange', 'showgrid'], [], `chart.spec.layout.${axisName}`);
      optionalString(axis.title, `chart.spec.layout.${axisName}.title`, 500);
      if (axis.type !== undefined) enumValue(axis.type, ['linear', 'log', 'date', 'category'], `chart.spec.layout.${axisName}.type`);
      if (axis.autorange !== undefined) booleanValue(axis.autorange, `chart.spec.layout.${axisName}.autorange`);
      if (axis.showgrid !== undefined) booleanValue(axis.showgrid, `chart.spec.layout.${axisName}.showgrid`);
    }
    if (layout.showlegend !== undefined) booleanValue(layout.showlegend, 'chart.spec.layout.showlegend');
    if (layout.barmode !== undefined) enumValue(layout.barmode, ['group', 'stack', 'relative', 'overlay'], 'chart.spec.layout.barmode');
    if (layout.width !== undefined) integerValue(layout.width, 'chart.spec.layout.width', 100, 4000);
    if (layout.height !== undefined) integerValue(layout.height, 'chart.spec.layout.height', 100, 2400);
  }
}

export function validateChartSpec(value: unknown): asserts value is ChartSpec {
  const chart = objectValue(value, 'chart_spec');
  exactKeys(chart, ['format', 'schema_version', 'spec', 'dataset', 'metadata'], ['format', 'schema_version', 'spec', 'dataset', 'metadata'], 'chart_spec');
  const format = enumValue(chart.format, ['vega-lite', 'plotly-json'], 'chart_spec.format');
  const version = enumValue(chart.schema_version, ['v5-safe-1', 'plotly-safe-1'], 'chart_spec.schema_version');
  if ((format === 'vega-lite' && version !== 'v5-safe-1') || (format === 'plotly-json' && version !== 'plotly-safe-1')) {
    invalid('chart format and schema version do not match');
  }

  const dataset = arrayValue(chart.dataset, 'chart_spec.dataset', 5000);
  for (const [rowIndex, value] of dataset.entries()) {
    const row = objectValue(value, `chart_spec.dataset[${rowIndex}]`);
    if (Object.keys(row).length > 100) invalid('chart dataset row has too many fields');
    for (const [key, item] of Object.entries(row)) {
      if (FORBIDDEN_KEYS.has(key)) invalid('chart dataset contains a forbidden field name');
      jsonScalar(item, `chart_spec.dataset[${rowIndex}].${key}`);
    }
  }

  const metadata = objectValue(chart.metadata, 'chart_spec.metadata');
  exactKeys(metadata, ['row_count', 'columns', 'truncated'], ['row_count', 'columns'], 'chart_spec.metadata');
  const rowCount = integerValue(metadata.row_count, 'chart_spec.metadata.row_count');
  const columns = boundedUniqueStrings(metadata.columns, 'chart_spec.metadata.columns', 100, 512);
  if (metadata.truncated !== undefined) booleanValue(metadata.truncated, 'chart_spec.metadata.truncated');
  if (rowCount < dataset.length) invalid('chart row_count is smaller than its inline dataset');
  if (columns.some((column) => FORBIDDEN_KEYS.has(column))) invalid('chart metadata contains a forbidden column');

  if (format === 'vega-lite') validateVegaSpec(chart.spec);
  else validatePlotlySpec(chart.spec);
  walkSafeChart(chart.spec);

  const serialized = JSON.stringify(chart);
  if (new TextEncoder().encode(serialized).byteLength > MAX_BYTES) invalid('chart exceeds the 2 MiB limit');
}

function validateTable(value: unknown): void {
  const payload = objectValue(value, 'table_result');
  exactKeys(payload, ['columns', 'rows', 'row_count', 'truncated'], ['columns', 'rows', 'row_count', 'truncated'], 'table_result');
  const columns = boundedUniqueStrings(payload.columns, 'table_result.columns', 100, 512);
  const rows = arrayValue(payload.rows, 'table_result.rows', 5000);
  for (const [rowIndex, value] of rows.entries()) {
    const row = objectValue(value, `table_result.rows[${rowIndex}]`);
    if (Object.keys(row).length > 100) invalid('table row has too many fields');
    for (const [key, item] of Object.entries(row)) {
      if (FORBIDDEN_KEYS.has(key) || !columns.includes(key)) invalid('table row contains an unknown field');
      jsonScalar(item, `table_result.rows[${rowIndex}].${key}`);
    }
  }
  const rowCount = integerValue(payload.row_count, 'table_result.row_count');
  if (rowCount < rows.length) invalid('table row_count is smaller than inline rows');
  if (new TextEncoder().encode(JSON.stringify(rows)).byteLength > MAX_BYTES) invalid('table rows exceed the 2 MiB limit');
  booleanValue(payload.truncated, 'table_result.truncated');
}

function validateComponent(value: unknown): void {
  const payload = objectValue(value, 'component');
  exactKeys(payload, ['component_kind', 'data'], ['component_kind', 'data'], 'component');
  const kind = enumValue(payload.component_kind, ['card', 'code', 'artifact'], 'component.component_kind');
  const data = objectValue(payload.data, 'component.data');
  if (kind === 'card') {
    exactKeys(data, ['title', 'body'], ['title', 'body'], 'component.data');
    stringValue(data.title, 'component.data.title', 500);
    stringValue(data.body, 'component.data.body', 100_000);
  } else if (kind === 'code') {
    exactKeys(data, ['language', 'text'], ['language', 'text'], 'component.data');
    stringValue(data.language, 'component.data.language', 64);
    stringValue(data.text, 'component.data.text', 1_000_000);
  } else {
    exactKeys(data, ['title', 'representation', 'content'], ['representation', 'content'], 'component.data');
    optionalString(data.title, 'component.data.title', 500);
    enumValue(data.representation, ['text', 'sanitized_html'], 'component.data.representation');
    stringValue(data.content, 'component.data.content', 1_000_000);
  }
}

function validateLineage(value: unknown): void {
  const payload = objectValue(value, 'lineage');
  exactKeys(payload, ['evidence'], ['evidence'], 'lineage');
  const evidence = objectValue(payload.evidence, 'lineage.evidence');
  exactKeys(
    evidence,
    ['schema_version', 'schema_snapshot_id', 'schema_hash', 'schema_drifted', 'semantic', 'retrieved_sources', 'tool_calls', 'sql_executions', 'validation_checks', 'confidence'],
    ['schema_version', 'schema_snapshot_id', 'schema_hash', 'schema_drifted', 'semantic', 'retrieved_sources', 'tool_calls', 'sql_executions', 'validation_checks', 'confidence'],
    'lineage.evidence',
  );
  if (evidence.schema_version !== null) integerValue(evidence.schema_version, 'lineage.evidence.schema_version', 1);
  if (evidence.schema_snapshot_id !== null) stringValue(evidence.schema_snapshot_id, 'lineage.evidence.schema_snapshot_id', 160);
  if (evidence.schema_hash !== null) stringValue(evidence.schema_hash, 'lineage.evidence.schema_hash', 160);
  booleanValue(evidence.schema_drifted, 'lineage.evidence.schema_drifted');

  const semantic = objectValue(evidence.semantic, 'lineage.evidence.semantic');
  exactKeys(semantic, ['coverage', 'metric_names', 'fallback_reason'], ['coverage', 'metric_names'], 'lineage.evidence.semantic');
  enumValue(semantic.coverage, ['full', 'partial', 'missing', 'not_applicable'], 'lineage.evidence.semantic.coverage');
  boundedUniqueStrings(semantic.metric_names, 'lineage.evidence.semantic.metric_names', 100, 256);
  optionalString(semantic.fallback_reason, 'lineage.evidence.semantic.fallback_reason', 2000);

  for (const [index, item] of arrayValue(evidence.retrieved_sources, 'lineage.evidence.retrieved_sources', 1000).entries()) {
    const source = objectValue(item, `lineage.evidence.retrieved_sources[${index}]`);
    exactKeys(source, ['id', 'kind', 'score'], ['id', 'kind'], 'retrieved source');
    stringValue(source.id, 'retrieved source id', 160);
    enumValue(source.kind, ['memory', 'document'], 'retrieved source kind');
    optionalNumber(source.score, 'retrieved source score', 0, 1);
  }
  for (const item of arrayValue(evidence.tool_calls, 'lineage.evidence.tool_calls', 1000)) {
    const call = objectValue(item, 'lineage tool call');
    exactKeys(call, ['name', 'success', 'runtime_ms'], ['name', 'success'], 'lineage tool call');
    stringValue(call.name, 'lineage tool call name', 160);
    booleanValue(call.success, 'lineage tool call success');
    optionalNumber(call.runtime_ms, 'lineage tool call runtime');
  }
  for (const item of arrayValue(evidence.sql_executions, 'lineage.evidence.sql_executions', 100)) {
    const execution = objectValue(item, 'lineage SQL execution');
    exactKeys(execution, ['sql', 'dialect', 'row_count', 'runtime_ms'], ['row_count'], 'lineage SQL execution');
    optionalString(execution.sql, 'lineage SQL', 100_000);
    optionalString(execution.dialect, 'lineage SQL dialect', 64);
    integerValue(execution.row_count, 'lineage SQL row count');
    optionalNumber(execution.runtime_ms, 'lineage SQL runtime');
  }
  for (const item of arrayValue(evidence.validation_checks, 'lineage.evidence.validation_checks', 1000)) {
    const check = objectValue(item, 'lineage validation check');
    exactKeys(check, ['name', 'passed'], ['name', 'passed'], 'lineage validation check');
    stringValue(check.name, 'lineage validation check name', 160);
    booleanValue(check.passed, 'lineage validation result');
  }
  const confidence = objectValue(evidence.confidence, 'lineage.evidence.confidence');
  exactKeys(confidence, ['tier', 'signals'], ['tier', 'signals'], 'lineage.evidence.confidence');
  enumValue(confidence.tier, ['High', 'Medium', 'Low'], 'lineage confidence tier');
  boundedUniqueStrings(confidence.signals, 'lineage confidence signals', 100, 160);
}

function validatePayload(type: V3EventType, value: unknown): void {
  const payload = objectValue(value, `${type}.payload`);
  if (type === 'status') {
    exactKeys(payload, ['stage', 'message'], ['stage', 'message'], 'status');
    enumValue(payload.stage, ['accepted', 'planning', 'semantic', 'sql', 'validating', 'rendering'], 'status.stage');
    stringValue(payload.message, 'status.message', 2000);
  } else if (type === 'assistant_text') {
    exactKeys(payload, ['text', 'delta'], ['text', 'delta'], 'assistant_text');
    stringValue(payload.text, 'assistant_text.text', 1_000_000);
    booleanValue(payload.delta, 'assistant_text.delta');
  } else if (type === 'table_result') {
    validateTable(payload);
  } else if (type === 'chart_spec') {
    exactKeys(payload, ['chart_spec'], ['chart_spec'], 'chart_spec payload');
    validateChartSpec(payload.chart_spec);
  } else if (type === 'component') {
    validateComponent(payload);
  } else if (type === 'warning') {
    exactKeys(payload, ['code', 'message', 'fallback'], ['code', 'message'], 'warning');
    const code = stringValue(payload.code, 'warning.code', 128, 1);
    if (!CODE_PATTERN.test(code)) invalid('warning.code is invalid');
    stringValue(payload.message, 'warning.message', 2000);
    if (payload.fallback !== undefined) enumValue(payload.fallback, ['sql', 'none'], 'warning.fallback');
  } else if (type === 'lineage') {
    validateLineage(payload);
  } else if (type === 'error') {
    exactKeys(payload, ['code', 'message', 'correlation_id', 'retryable'], ['code', 'message', 'correlation_id', 'retryable'], 'error');
    const code = stringValue(payload.code, 'error.code', 128, 1);
    if (!CODE_PATTERN.test(code)) invalid('error.code is invalid');
    stringValue(payload.message, 'error.message', 2000);
    stringValue(payload.correlation_id, 'error.correlation_id', 160, 1);
    booleanValue(payload.retryable, 'error.retryable');
  } else {
    exactKeys(payload, ['status', 'event_count'], ['status', 'event_count'], 'done');
    if (payload.status !== 'completed') invalid('done.status is invalid');
    integerValue(payload.event_count, 'done.event_count', 1);
  }
}

export function parseV3Event(value: unknown): V3ChatEvent {
  const event = objectValue(value, 'event');
  exactKeys(
    event,
    ['event_version', 'event_type', 'event_id', 'sequence', 'conversation_id', 'request_id', 'timestamp', 'payload'],
    ['event_version', 'event_type', 'event_id', 'sequence', 'conversation_id', 'request_id', 'timestamp', 'payload'],
    'event',
  );
  if (event.event_version !== 'v3') invalid('event_version is unsupported');
  if (typeof event.event_type !== 'string' || !EVENT_TYPES.has(event.event_type as V3EventType)) {
    invalid('event_type is unsupported');
  }
  const type = event.event_type as V3EventType;
  for (const key of ['event_id', 'conversation_id', 'request_id'] as const) {
    const identifier = stringValue(event[key], `event.${key}`, 160, 1);
    if (!ID_PATTERN.test(identifier) || identifier.trim() !== identifier) invalid(`event.${key} is invalid`);
  }
  integerValue(event.sequence, 'event.sequence');
  const timestamp = stringValue(event.timestamp, 'event.timestamp', 64, 1);
  if (!UTC_TIMESTAMP_PATTERN.test(timestamp) || !Number.isFinite(Date.parse(timestamp))) {
    invalid('event.timestamp must be an RFC 3339 UTC timestamp');
  }
  validatePayload(type, event.payload);
  return event as unknown as V3ChatEvent;
}

export class V3EventSequenceValidator {
  private nextSequence = 0;
  private conversationId: string | undefined;
  private requestId: string | undefined;
  private terminal = false;
  private lineage = false;
  private readonly eventIds = new Set<string>();

  accept(event: V3ChatEvent): void {
    if (this.terminal) invalid('an event followed the terminal event');
    if (event.sequence !== this.nextSequence) invalid('event sequence is not contiguous');
    if (this.eventIds.has(event.event_id)) invalid('event_id was reused');
    if (this.conversationId === undefined) {
      this.conversationId = event.conversation_id;
      this.requestId = event.request_id;
    } else if (event.conversation_id !== this.conversationId || event.request_id !== this.requestId) {
      invalid('event identifiers changed during the request');
    }
    if (event.event_type === 'done' && event.payload.event_count !== event.sequence + 1) {
      invalid('done.event_count does not match the sequence');
    }
    if (event.event_type === 'lineage') {
      if (this.lineage) invalid('event stream contains more than one lineage event');
      this.lineage = true;
    } else if (this.lineage && !TERMINAL_TYPES.has(event.event_type)) {
      invalid('lineage must be the final non-terminal event');
    } else if (TERMINAL_TYPES.has(event.event_type) && !this.lineage) {
      invalid('terminal event is missing preceding lineage');
    }
    this.eventIds.add(event.event_id);
    this.nextSequence += 1;
    this.terminal = TERMINAL_TYPES.has(event.event_type);
  }

  assertTerminal(): void {
    if (!this.terminal) invalid('event stream ended without a terminal event');
  }
}

export function parseV3PollResponse(value: unknown): V3PollResponse {
  const response = objectValue(value, 'poll response');
  exactKeys(response, ['event_version', 'conversation_id', 'request_id', 'events', 'terminal_event'], ['event_version', 'conversation_id', 'request_id', 'events', 'terminal_event'], 'poll response');
  if (response.event_version !== 'v3') invalid('poll event_version is unsupported');
  const conversationId = stringValue(response.conversation_id, 'poll conversation_id', 160, 1);
  const requestId = stringValue(response.request_id, 'poll request_id', 160, 1);
  const events = arrayValue(response.events, 'poll events', 100_000).map(parseV3Event);
  const terminal = parseV3Event(response.terminal_event);
  const sequence = new V3EventSequenceValidator();
  for (const event of [...events, terminal]) {
    if (event.conversation_id !== conversationId || event.request_id !== requestId) invalid('poll identifiers do not match its events');
    sequence.accept(event);
  }
  if (events.some((event) => TERMINAL_TYPES.has(event.event_type)) || !TERMINAL_TYPES.has(terminal.event_type)) {
    invalid('poll terminal event placement is invalid');
  }
  sequence.assertTerminal();
  return response as unknown as V3PollResponse;
}

function richComponent(event: V3ChatEvent, type: string, data: Record<string, unknown>): ChatStreamChunk {
  return {
    rich: {
      id: `v3-${event.event_id}`,
      type,
      lifecycle: 'create',
      data,
      children: [],
      timestamp: event.timestamp,
      visible: true,
      interactive: false,
    },
    conversation_id: event.conversation_id,
    request_id: event.request_id,
    timestamp: Date.parse(event.timestamp) / 1000,
  };
}

export function normalizeV3Event(event: V3ChatEvent): ChatStreamChunk | null {
  switch (event.event_type) {
    case 'status':
      return richComponent(event, 'status_bar_update', {
        status: 'working',
        message: event.payload.message,
        detail: event.payload.stage,
      });
    case 'assistant_text':
      return richComponent(event, 'text', {
        content: event.payload.text,
        markdown: false,
      });
    case 'table_result':
      return richComponent(event, 'dataframe', {
        columns: event.payload.columns,
        column_count: event.payload.columns.length,
        data: event.payload.rows,
        row_count: event.payload.row_count,
        truncated: event.payload.truncated,
      });
    case 'chart_spec':
      return richComponent(event, 'chart', { data: event.payload.chart_spec });
    case 'component':
      if (event.payload.component_kind === 'card') {
        return richComponent(event, 'card', {
          title: event.payload.data.title,
          content: event.payload.data.body,
          markdown: false,
        });
      }
      if (event.payload.component_kind === 'code') {
        return richComponent(event, 'text', {
          content: event.payload.data.text,
          code_language: event.payload.data.language,
        });
      }
      if (event.payload.data.representation === 'text') {
        return richComponent(event, 'text', {
          content: event.payload.data.content,
          code_language: 'text',
        });
      }
      return richComponent(event, 'artifact', {
        artifact_id: event.event_id,
        artifact_type: 'html',
        content: event.payload.data.content,
        title: event.payload.data.title ?? 'Static artifact',
        editable: false,
        external_renderable: false,
        fullscreen_capable: false,
      });
    case 'warning':
      return richComponent(event, 'status_bar_update', {
        status: 'warning',
        message: event.payload.message,
        detail: event.payload.code,
      });
    case 'lineage':
      return richComponent(event, 'card', {
        title: 'Evidence & Lineage',
        content: JSON.stringify(event.payload.evidence, null, 2),
        markdown: false,
        collapsible: true,
        collapsed: false,
      });
    case 'error':
      throw new V3RemoteError(event.payload);
    case 'done':
      return null;
  }
}
