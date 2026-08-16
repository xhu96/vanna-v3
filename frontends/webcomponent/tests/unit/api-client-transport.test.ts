import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  VannaApiClient,
  VannaHttpError,
  type ChatStreamChunk,
} from '../../src/services/api-client';
import { V3ProtocolError, V3RemoteError } from '../../src/types/events-v3';

const encoder = new TextEncoder();

function event(eventType: string, payload: Record<string, unknown>, sequence = 0) {
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

function frame(value: ReturnType<typeof event>, overrides: { event?: string; id?: string } = {}) {
  return [
    `id: ${overrides.id ?? value.event_id}`,
    `event: ${overrides.event ?? value.event_type}`,
    `data: ${JSON.stringify(value)}`,
    '',
    '',
  ].join('\n');
}

function lineagePayload() {
  return {
    evidence: {
      schema_version: null,
      schema_snapshot_id: null,
      schema_hash: null,
      schema_drifted: false,
      semantic: { coverage: 'not_applicable', metric_names: [] },
      retrieved_sources: [],
      tool_calls: [],
      sql_executions: [],
      validation_checks: [{ name: 'agent_lineage_emitted', passed: false }],
      confidence: { tier: 'Low', signals: ['missing_agent_lineage'] },
    },
  };
}

function responseFromFragments(fragments: Uint8Array[]): Response {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      for (const fragment of fragments) controller.enqueue(fragment);
      controller.close();
    },
  }), { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

async function collect<T>(stream: AsyncGenerator<T, void, unknown>): Promise<T[]> {
  const values: T[] = [];
  for await (const value of stream) values.push(value);
  return values;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('VannaApiClient V2/V3 transports', () => {
  it('defaults to V2 and selects V3 endpoints only when explicit', () => {
    const v2 = new VannaApiClient();
    const v3 = new VannaApiClient({ protocol: 'v3' });

    expect(v2.protocol).toBe('v2');
    expect(v2.getEndpoints()).toEqual({
      sse: '/api/vanna/v2/chat_sse',
      websocket: '/api/vanna/v2/chat_websocket',
      poll: '/api/vanna/v2/chat_poll',
    });
    expect(v3.getEndpoints()).toEqual({
      sse: '/api/vanna/v3/chat/events',
      websocket: '',
      poll: '/api/vanna/v3/chat/poll',
    });
  });

  it('validates fragmented V3 SSE and normalizes only non-terminal events', async () => {
    const text = frame(event('assistant_text', { text: 'café', delta: false }, 0))
      + frame(event('lineage', lineagePayload(), 1))
      + frame(event('done', { status: 'completed', event_count: 3 }, 2));
    const bytes = encoder.encode(text);
    const split = bytes.indexOf(0xc3) + 1;
    const fetchMock = vi.fn().mockResolvedValue(responseFromFragments([
      bytes.slice(0, 7),
      bytes.slice(7, split),
      bytes.slice(split),
    ]));
    vi.stubGlobal('fetch', fetchMock);
    const client = new VannaApiClient({ protocol: 'v3', baseUrl: 'https://api.example.test' });

    const chunks = await collect(client.streamChat({ message: 'hello' }));

    expect(chunks).toHaveLength(2);
    expect(chunks[0].rich).toMatchObject({
      type: 'text',
      data: { content: 'café', markdown: false },
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('https://api.example.test/api/vanna/v3/chat/events');
  });

  it.each([
    ['missing terminal', frame(event('assistant_text', { text: 'partial', delta: false }))],
    ['mismatched frame event', frame(event('done', { status: 'completed', event_count: 1 }), { event: 'error' })],
    ['mismatched frame id', frame(event('done', { status: 'completed', event_count: 1 }), { id: 'evt_other' })],
    ['event after terminal', frame(event('done', { status: 'completed', event_count: 1 })) + frame(event('done', { status: 'completed', event_count: 2 }, 1))],
    ['event after lineage', frame(event('lineage', lineagePayload())) + frame(event('assistant_text', { text: 'too late', delta: false }, 1)) + frame(event('done', { status: 'completed', event_count: 3 }, 2))],
  ])('fails closed for %s without replaying the request', async (_name, body) => {
    const fetchMock = vi.fn().mockResolvedValue(responseFromFragments([encoder.encode(body)]));
    vi.stubGlobal('fetch', fetchMock);
    const client = new VannaApiClient({ protocol: 'v3' });

    await expect(collect(client.streamV3Events({ message: 'hello' }))).rejects.toBeInstanceOf(V3ProtocolError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('surfaces typed terminal errors without exposing another response field', async () => {
    const body = frame(event('lineage', lineagePayload())) + frame(event('error', {
      code: 'query_policy_rejected',
      message: 'The query could not be executed safely.',
      correlation_id: 'err_public',
      retryable: false,
    }, 1));
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(responseFromFragments([encoder.encode(body)])));
    const client = new VannaApiClient({ protocol: 'v3' });

    await expect(collect(client.streamChat({ message: 'hello' }))).rejects.toMatchObject({
      name: 'V3RemoteError',
      code: 'query_policy_rejected',
      correlationId: 'err_public',
    } satisfies Partial<V3RemoteError>);
  });

  it('validates V3 poll responses and returns normalized compatibility chunks', async () => {
    const body = {
      event_version: 'v3',
      conversation_id: 'conv_1',
      request_id: 'req_1',
      events: [
        event('assistant_text', { text: 'answer', delta: false }),
        event('lineage', lineagePayload(), 1),
      ],
      terminal_event: event('done', { status: 'completed', event_count: 3 }, 2),
    };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })));
    const client = new VannaApiClient({ protocol: 'v3' });

    const typed = await client.sendV3Poll({ message: 'hello' });
    expect(typed.terminal_event.event_type).toBe('done');

    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify(body), { status: 200 }));
    const normalized = await client.sendPollMessage({ message: 'hello' });
    expect(normalized).toMatchObject({
      conversation_id: 'conv_1',
      request_id: 'req_1',
      total_chunks: 2,
    });
  });

  it('propagates caller cancellation through the response reader', async () => {
    const abortController = new AbortController();
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          init.signal?.addEventListener('abort', () => {
            controller.error(new DOMException('cancelled', 'AbortError'));
          }, { once: true });
        },
      });
      return Promise.resolve(new Response(stream, { status: 200 }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const client = new VannaApiClient({ protocol: 'v3' });
    const pending = collect(client.streamV3Events(
      { message: 'hello' },
      { signal: abortController.signal },
    ));

    await Promise.resolve();
    abortController.abort();

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(['iterator return', 'protocol rejection'] as const)(
    'cancels the HTTP response body on %s',
    async (reason) => {
      const cancel = vi.fn();
      const body = reason === 'iterator return'
        ? frame(event('assistant_text', { text: 'partial', delta: false }))
        : 'event: assistant_text\nid: evt_0\ndata: not-json\n\n';
      const response = new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(body));
        },
        cancel,
      }), { status: 200 });
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response));
      const client = new VannaApiClient({ protocol: 'v3' });

      if (reason === 'iterator return') {
        const iterator = client.streamV3Events({ message: 'hello' });
        expect((await iterator.next()).done).toBe(false);
        await iterator.return(undefined);
      } else {
        await expect(collect(client.streamV3Events({ message: 'hello' })))
          .rejects.toBeInstanceOf(V3ProtocolError);
      }

      expect(cancel).toHaveBeenCalledTimes(1);
    },
  );

  it.each(['sse', 'poll'] as const)('keeps the timeout active through a stalled %s body', async (transport) => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          init.signal?.addEventListener('abort', () => {
            controller.error(init.signal?.reason);
          }, { once: true });
        },
      });
      return Promise.resolve(new Response(stream, {
        status: 200,
        headers: {
          'Content-Type': transport === 'sse' ? 'text/event-stream' : 'application/json',
        },
      }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const client = new VannaApiClient({ protocol: 'v3', timeout: 25 });
    const pending = transport === 'sse'
      ? collect(client.streamV3Events({ message: 'hello' }))
      : client.sendV3Poll({ message: 'hello' });
    const rejection = expect(pending).rejects.toMatchObject({ name: 'TimeoutError' });

    await vi.advanceTimersByTimeAsync(26);

    await rejection;
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each(['sse', 'poll'] as const)(
    'preserves the V2 default without adding a %s body deadline',
    async (transport) => {
      vi.useFakeTimers();
      let requestSignal: AbortSignal | undefined;
      const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
        requestSignal = init.signal ?? undefined;
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            init.signal?.addEventListener('abort', () => {
              controller.error(init.signal?.reason);
            }, { once: true });
          },
        });
        return Promise.resolve(new Response(stream, {
          status: 200,
          headers: {
            'Content-Type': transport === 'sse' ? 'text/event-stream' : 'application/json',
          },
        }));
      });
      vi.stubGlobal('fetch', fetchMock);
      const client = new VannaApiClient({ protocol: 'v2' });
      const externalAbort = new AbortController();
      const pending = transport === 'sse'
        ? collect(client.streamChat({ message: 'hello' }, { signal: externalAbort.signal }))
        : client.sendPollMessage({ message: 'hello' }, { signal: externalAbort.signal });
      const rejection = expect(pending).rejects.toMatchObject({ name: 'AbortError' });

      await vi.advanceTimersByTimeAsync(30_001);
      expect(requestSignal?.aborted).toBe(false);

      externalAbort.abort(new DOMException('cancelled', 'AbortError'));
      await rejection;
      expect(fetchMock).toHaveBeenCalledTimes(1);
    },
  );

  it('uses only the public HTTP error envelope', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: {
        code: 'authentication_required',
        message: 'Authentication is required.',
        correlation_id: 'err_public',
        retryable: false,
      },
      internal_exception: 'password=TOP_SECRET',
    }), { status: 401 }));
    vi.stubGlobal('fetch', fetchMock);
    const client = new VannaApiClient({ protocol: 'v3' });

    await expect(client.sendV3Poll({ message: 'hello' })).rejects.toMatchObject({
      name: 'VannaHttpError',
      status: 401,
      code: 'authentication_required',
      message: 'Authentication is required.',
      correlationId: 'err_public',
    } satisfies Partial<VannaHttpError>);
  });
});

class FakeWebSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;
  readyState = FakeWebSocket.OPEN;
  readonly sent: string[] = [];
  readonly closes: Array<{ code?: number; reason?: string }> = [];

  send(value: string): void {
    this.sent.push(value);
  }

  close(code?: number, reason?: string): void {
    this.closes.push({ code, reason });
    this.readyState = FakeWebSocket.CLOSED;
  }

  message(value: unknown): void {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(value) }));
  }
}

function v2Chunk(): ChatStreamChunk {
  return {
    rich: { type: 'text', data: { content: 'hello' } },
    conversation_id: 'conv_1',
    request_id: 'req_1',
    timestamp: 1,
  };
}

describe('V2 WebSocket compatibility', () => {
  it('delivers queued chunks and recognizes the server top-level completion frame', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const ws = new FakeWebSocket();
    const client = new VannaApiClient();
    const stream = await client.sendWebSocketMessage(ws as unknown as WebSocket, { message: 'hello' });
    const first = stream.next();

    ws.message(v2Chunk());
    expect(await first).toMatchObject({ done: false, value: v2Chunk() });

    const terminal = stream.next();
    ws.message({ type: 'completion', data: { status: 'done' } });
    expect(await terminal).toEqual({ done: true, value: undefined });
    expect(ws.closes).toEqual([]);
  });

  it('propagates top-level public errors and closes an explicitly cancelled stream', async () => {
    vi.stubGlobal('WebSocket', FakeWebSocket);
    const failedSocket = new FakeWebSocket();
    const client = new VannaApiClient();
    const failed = await client.sendWebSocketMessage(
      failedSocket as unknown as WebSocket,
      { message: 'hello' },
    );
    const pending = failed.next();
    failedSocket.message({ type: 'error', data: { message: 'Public failure' } });
    await expect(pending).rejects.toThrow('Public failure');

    const cancelledSocket = new FakeWebSocket();
    const cancelled = await client.sendWebSocketMessage(
      cancelledSocket as unknown as WebSocket,
      { message: 'hello' },
    );
    const first = cancelled.next();
    cancelledSocket.message(v2Chunk());
    await first;
    await cancelled.return(undefined);
    expect(cancelledSocket.closes).toEqual([{ code: 1000, reason: 'client_cancelled' }]);
  });
});
