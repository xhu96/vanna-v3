/** API client for V2 compatibility and the typed V3 event contract. */

import { SseParser, type ParsedSseEvent } from './sse-parser';
import {
  normalizeV3Event,
  parseV3Event,
  parseV3PollResponse,
  V3EventSequenceValidator,
  V3ProtocolError,
  type V3ChatEvent,
  type V3PollResponse,
} from '../types/events-v3';

export type ApiProtocol = 'v2' | 'v3';

export interface ChatMessage {
  id: string;
  content: string;
  type: 'user' | 'assistant';
  timestamp: number;
}

export interface ChatRequest {
  message: string;
  conversation_id?: string;
  user_id?: string;
  request_id?: string;
  metadata?: Record<string, unknown>;
}

export interface ChatStreamChunk {
  rich: Record<string, any>;
  simple?: Record<string, any>;
  conversation_id: string;
  request_id: string;
  timestamp: number;
}

export interface ChatResponse {
  chunks: ChatStreamChunk[];
  conversation_id: string;
  request_id: string;
  total_chunks: number;
}

export interface ApiClientConfig {
  protocol?: ApiProtocol;
  baseUrl?: string;
  sseEndpoint?: string;
  wsEndpoint?: string;
  pollEndpoint?: string;
  timeout?: number;
  customHeaders?: Record<string, string>;
}

export interface RequestOptions {
  signal?: AbortSignal;
}

interface LocationLike {
  protocol: string;
  host: string;
}

interface LinkedAbort {
  signal: AbortSignal;
  abort: (reason?: unknown) => void;
  cleanup: () => void;
}

const ENDPOINTS = {
  v2: {
    sse: '/api/vanna/v2/chat_sse',
    websocket: '/api/vanna/v2/chat_websocket',
    poll: '/api/vanna/v2/chat_poll',
  },
  v3: {
    sse: '/api/vanna/v3/chat/events',
    websocket: '',
    poll: '/api/vanna/v3/chat/poll',
  },
} as const;

export class VannaHttpError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId?: string;
  readonly retryable: boolean;

  constructor(
    status: number,
    message: string,
    code = 'http_error',
    correlationId?: string,
    retryable = false,
  ) {
    super(message);
    this.name = 'VannaHttpError';
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
    this.retryable = retryable;
  }
}

export function resolveHttpUrl(baseUrl: string, endpoint: string): string {
  return endpoint.startsWith('http') ? endpoint : `${baseUrl}${endpoint}`;
}

export function resolveWebSocketUrl(
  baseUrl: string,
  endpoint: string,
  location?: LocationLike,
): string {
  if (endpoint.startsWith('ws://') || endpoint.startsWith('wss://')) {
    return endpoint;
  }

  if (baseUrl) {
    const baseUrlObject = new URL(baseUrl);
    const protocol = baseUrlObject.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${baseUrlObject.host}${endpoint}`;
  }

  const currentLocation = location ?? window.location;
  const protocol = currentLocation.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${currentLocation.host}${endpoint}`;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function publicControlError(value: Record<string, unknown>): Error {
  const data = isObject(value.data) ? value.data : {};
  const message =
    typeof data.message === 'string' && data.message.length <= 2000
      ? data.message
      : 'The server could not complete the request.';
  return new Error(message);
}

function isChatChunk(value: unknown): value is ChatStreamChunk {
  if (!isObject(value) || !isObject(value.rich)) return false;
  return (
    typeof value.conversation_id === 'string' &&
    typeof value.request_id === 'string' &&
    typeof value.timestamp === 'number' &&
    Number.isFinite(value.timestamp)
  );
}

async function responseError(response: Response): Promise<VannaHttpError> {
  let code = 'http_error';
  let message = `Request failed with HTTP ${response.status}.`;
  let correlationId: string | undefined;
  let retryable = response.status >= 500;
  try {
    const body: unknown = await response.json();
    if (isObject(body) && isObject(body.error)) {
      const error = body.error;
      if (typeof error.code === 'string' && /^[a-z][a-z0-9_]{0,127}$/.test(error.code)) {
        code = error.code;
      }
      if (typeof error.message === 'string' && error.message.length <= 2000) {
        message = error.message;
      }
      if (typeof error.correlation_id === 'string' && error.correlation_id.length <= 160) {
        correlationId = error.correlation_id;
      }
      if (typeof error.retryable === 'boolean') retryable = error.retryable;
    }
  } catch {
    // Never expose or log a malformed response body.
  }
  return new VannaHttpError(response.status, message, code, correlationId, retryable);
}

function linkedAbort(signal: AbortSignal | undefined, timeoutMs: number): LinkedAbort {
  const controller = new AbortController();
  const abort = () => controller.abort(signal?.reason);
  if (signal?.aborted) abort();
  else signal?.addEventListener('abort', abort, { once: true });

  let timer: ReturnType<typeof setTimeout> | undefined;
  if (timeoutMs > 0) {
    timer = setTimeout(() => {
      controller.abort(new DOMException('Connection timed out', 'TimeoutError'));
    }, timeoutMs);
  }

  return {
    signal: controller.signal,
    abort: (reason?: unknown) => controller.abort(reason),
    cleanup: () => {
      if (timer !== undefined) clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    },
  };
}

export class VannaApiClient {
  public readonly baseUrl: string;
  public readonly protocol: ApiProtocol;
  private readonly sseEndpoint: string;
  private readonly wsEndpoint: string;
  private readonly pollEndpoint: string;
  private readonly timeout: number;
  private customHeaders: Record<string, string>;

  constructor(config: ApiClientConfig = {}) {
    this.protocol = config.protocol ?? 'v2';
    if (this.protocol !== 'v2' && this.protocol !== 'v3') {
      throw new Error('Unsupported Vanna API protocol');
    }
    this.baseUrl = config.baseUrl ?? '';
    this.sseEndpoint = config.sseEndpoint ?? ENDPOINTS[this.protocol].sse;
    this.wsEndpoint = config.wsEndpoint ?? ENDPOINTS[this.protocol].websocket;
    this.pollEndpoint = config.pollEndpoint ?? ENDPOINTS[this.protocol].poll;
    const timeout = config.timeout ?? (this.protocol === 'v3' ? 30_000 : 0);
    if (!Number.isFinite(timeout) || timeout < 0) {
      throw new Error('timeout must be a finite non-negative number');
    }
    this.timeout = timeout;
    this.customHeaders = config.customHeaders ?? {};
  }

  setCustomHeaders(headers: Record<string, string>): void {
    this.customHeaders = { ...headers };
  }

  getCustomHeaders(): Record<string, string> {
    return { ...this.customHeaders };
  }

  getEndpoints(): { sse: string; websocket: string; poll: string } {
    return {
      sse: this.sseEndpoint,
      websocket: this.wsEndpoint,
      poll: this.pollEndpoint,
    };
  }

  async *streamChat(
    request: ChatRequest,
    options: RequestOptions = {},
  ): AsyncGenerator<ChatStreamChunk, void, unknown> {
    if (this.protocol === 'v2') {
      yield* this.streamV2Chat(request, options);
      return;
    }
    for await (const event of this.streamV3Events(request, options)) {
      const chunk = normalizeV3Event(event);
      if (chunk) yield chunk;
    }
  }

  async *streamV3Events(
    request: ChatRequest,
    options: RequestOptions = {},
  ): AsyncGenerator<V3ChatEvent, void, unknown> {
    if (this.protocol !== 'v3') {
      throw new V3ProtocolError('Typed V3 events require protocol="v3".');
    }
    const sequence = new V3EventSequenceValidator();
    for await (const frame of this.readSseFrames(request, options)) {
      let decoded: unknown;
      try {
        decoded = JSON.parse(frame.data);
      } catch {
        throw new V3ProtocolError('The server returned malformed V3 event JSON.');
      }
      const event = parseV3Event(decoded);
      if (frame.event !== event.event_type || frame.id !== event.event_id) {
        throw new V3ProtocolError('The SSE frame metadata does not match its V3 event.');
      }
      sequence.accept(event);
      yield event;
    }
    sequence.assertTerminal();
  }

  private async *streamV2Chat(
    request: ChatRequest,
    options: RequestOptions,
  ): AsyncGenerator<ChatStreamChunk, void, unknown> {
    for await (const frame of this.readSseFrames(request, options)) {
      if (frame.data.trim() === '[DONE]') return;
      let decoded: unknown;
      try {
        decoded = JSON.parse(frame.data);
      } catch {
        // Preserve V2's historical tolerance for malformed non-terminal frames.
        continue;
      }
      if (isObject(decoded) && decoded.type === 'error') {
        throw publicControlError(decoded);
      }
      if (isChatChunk(decoded)) yield decoded;
    }
  }

  private async *readSseFrames(
    request: ChatRequest,
    options: RequestOptions,
  ): AsyncGenerator<ParsedSseEvent, void, unknown> {
    const url = resolveHttpUrl(this.baseUrl, this.sseEndpoint);
    const abort = linkedAbort(options.signal, this.timeout);
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let bodyComplete = false;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
          ...this.customHeaders,
        },
        body: JSON.stringify(request),
        signal: abort.signal,
      });
      if (!response.ok) throw await responseError(response);
      reader = response.body?.getReader();
      if (!reader) throw new Error('The server returned no response body.');

      const parser = new SseParser();
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          bodyComplete = true;
          break;
        }
        for (const frame of parser.push(value)) yield frame;
      }
      for (const frame of parser.finish()) yield frame;
    } finally {
      if (reader && !bodyComplete) {
        abort.abort(new DOMException('Stream consumer cancelled', 'AbortError'));
        try {
          await reader.cancel('stream_consumer_cancelled');
        } catch {
          // The linked abort can reject the reader before cancel() settles.
        }
      }
      reader?.releaseLock();
      abort.cleanup();
    }
  }

  createWebSocketConnection(options: RequestOptions = {}): Promise<WebSocket> {
    if (this.protocol !== 'v2') {
      return Promise.reject(new Error('V3 does not define a WebSocket transport.'));
    }
    return new Promise((resolve, reject) => {
      const wsUrl = resolveWebSocketUrl(this.baseUrl, this.wsEndpoint);
      const ws = new WebSocket(wsUrl);
      let settled = false;
      let timer: ReturnType<typeof setTimeout> | undefined;
      const finish = (callback: () => void) => {
        if (settled) return;
        settled = true;
        if (timer !== undefined) clearTimeout(timer);
        options.signal?.removeEventListener('abort', onAbort);
        callback();
      };
      const onAbort = () => finish(() => {
        ws.close(1000, 'client_cancelled');
        reject(options.signal?.reason ?? new DOMException('Request cancelled', 'AbortError'));
      });
      if (this.timeout > 0) {
        timer = setTimeout(() => finish(() => {
          ws.close();
          reject(new Error('WebSocket connection timeout'));
        }), this.timeout);
      }

      ws.onopen = () => finish(() => resolve(ws));
      ws.onerror = () => finish(() => reject(new Error('WebSocket connection failed')));
      if (options.signal?.aborted) onAbort();
      else options.signal?.addEventListener('abort', onAbort, { once: true });
    });
  }

  async sendWebSocketMessage(
    ws: WebSocket,
    request: ChatRequest,
  ): Promise<AsyncGenerator<ChatStreamChunk, void, unknown>> {
    if (this.protocol !== 'v2') throw new Error('V3 does not define a WebSocket transport.');
    if (ws.readyState !== WebSocket.OPEN) throw new Error('WebSocket not connected');

    const queue: ChatStreamChunk[] = [];
    let completed = false;
    let failure: Error | undefined;
    let wake: (() => void) | undefined;
    const notify = () => {
      wake?.();
      wake = undefined;
    };
    const messageHandler = (event: MessageEvent) => {
      if (typeof event.data !== 'string') return;
      let decoded: unknown;
      try {
        decoded = JSON.parse(event.data);
      } catch {
        return;
      }
      if (isObject(decoded) && decoded.type === 'completion') {
        completed = true;
        notify();
      } else if (isObject(decoded) && decoded.type === 'error') {
        failure = publicControlError(decoded);
        completed = true;
        notify();
      } else if (isChatChunk(decoded)) {
        queue.push(decoded);
        notify();
      }
    };
    const closeHandler = () => {
      if (!completed) failure = new Error('WebSocket closed before completion');
      completed = true;
      notify();
    };
    const errorHandler = () => {
      failure = new Error('WebSocket transport failed');
      completed = true;
      notify();
    };
    ws.addEventListener('message', messageHandler);
    ws.addEventListener('close', closeHandler);
    ws.addEventListener('error', errorHandler);

    try {
      ws.send(JSON.stringify(request));
    } catch (error) {
      ws.removeEventListener('message', messageHandler);
      ws.removeEventListener('close', closeHandler);
      ws.removeEventListener('error', errorHandler);
      throw error;
    }

    async function* messages(): AsyncGenerator<ChatStreamChunk, void, unknown> {
      try {
        while (true) {
          if (queue.length > 0) {
            yield queue.shift() as ChatStreamChunk;
          } else if (failure) {
            throw failure;
          } else if (completed) {
            return;
          } else {
            await new Promise<void>((resolve) => {
              wake = resolve;
            });
          }
        }
      } finally {
        ws.removeEventListener('message', messageHandler);
        ws.removeEventListener('close', closeHandler);
        ws.removeEventListener('error', errorHandler);
        if (!completed && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
          ws.close(1000, 'client_cancelled');
        }
      }
    }
    return messages();
  }

  async sendPollMessage(
    request: ChatRequest,
    options: RequestOptions = {},
  ): Promise<ChatResponse> {
    if (this.protocol === 'v2') {
      const value = await this.sendPollRequest(request, options);
      if (!isObject(value) || !Array.isArray(value.chunks)) {
        throw new Error('The server returned an invalid V2 poll response.');
      }
      return value as unknown as ChatResponse;
    }

    const response = await this.sendV3Poll(request, options);
    const chunks: ChatStreamChunk[] = [];
    for (const event of [...response.events, response.terminal_event]) {
      const chunk = normalizeV3Event(event);
      if (chunk) chunks.push(chunk);
    }
    return {
      chunks,
      conversation_id: response.conversation_id,
      request_id: response.request_id,
      total_chunks: chunks.length,
    };
  }

  async sendV3Poll(
    request: ChatRequest,
    options: RequestOptions = {},
  ): Promise<V3PollResponse> {
    if (this.protocol !== 'v3') {
      throw new V3ProtocolError('Typed V3 polling requires protocol="v3".');
    }
    return parseV3PollResponse(await this.sendPollRequest(request, options));
  }

  private async sendPollRequest(request: ChatRequest, options: RequestOptions): Promise<unknown> {
    const url = resolveHttpUrl(this.baseUrl, this.pollEndpoint);
    const abort = linkedAbort(options.signal, this.timeout);
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...this.customHeaders,
        },
        body: JSON.stringify(request),
        signal: abort.signal,
      });
      if (!response.ok) throw await responseError(response);
      return await response.json() as unknown;
    } finally {
      abort.cleanup();
    }
  }

  generateId(): string {
    return `${Date.now()}-${Math.random().toString(36).substring(2, 11)}`;
  }
}

export const apiClient = new VannaApiClient();
