import { describe, expect, it } from 'vitest';
import { SseParser } from '../../src/services/sse-parser';

const encoder = new TextEncoder();

function parseFragments(fragments: Uint8Array[]) {
  const parser = new SseParser();
  return [...fragments.flatMap((fragment) => parser.push(fragment)), ...parser.finish()];
}

describe('SseParser', () => {
  it('handles arbitrary byte fragmentation including UTF-8 boundaries', () => {
    const bytes = encoder.encode('id: evt_1\nevent: assistant_text\ndata: {"text":"café"}\n\n');
    const splitAt = bytes.indexOf(0xc3) + 1;

    expect(parseFragments([
      bytes.slice(0, 1),
      bytes.slice(1, splitAt),
      bytes.slice(splitAt),
    ])).toEqual([{
      data: '{"text":"café"}',
      event: 'assistant_text',
      id: 'evt_1',
    }]);
  });

  it.each(['\n', '\r\n', '\r'])('supports %j line endings and multiline data', (eol) => {
    const frame = [
      ': heartbeat',
      'id: evt_2',
      'event: status',
      'data: {"stage":"planning",',
      'data: "message":"Working"}',
      '',
      '',
    ].join(eol);

    expect(parseFragments([encoder.encode(frame)])).toEqual([{
      data: '{"stage":"planning",\n"message":"Working"}',
      event: 'status',
      id: 'evt_2',
    }]);
  });

  it('dispatches multiple complete frames and discards an incomplete final frame', () => {
    const events = parseFragments([
      encoder.encode('data: one\n\ndata: two\n\ndata: incomplete'),
    ]);

    expect(events).toEqual([{ data: 'one' }, { data: 'two' }]);
  });

  it('does not reuse an id omitted by a later Vanna frame', () => {
    expect(parseFragments([
      encoder.encode('id: evt_1\ndata: one\n\ndata: two\n\n'),
    ])).toEqual([{ data: 'one', id: 'evt_1' }, { data: 'two' }]);
  });

  it('preserves a CRLF split across chunks', () => {
    expect(parseFragments([
      encoder.encode('data: first\r'),
      encoder.encode('\n\r'),
      encoder.encode('\ndata: second\r\r'),
    ])).toEqual([{ data: 'first' }, { data: 'second' }]);
  });
});
