import { describe, expect, it, vi } from 'vitest';
import {
  resolveHttpUrl,
  resolveWebSocketUrl,
  VannaApiClient,
} from '../../src/services/api-client';

describe('V2 endpoint URL construction', () => {
  it('never logs authentication headers during client construction', () => {
    const log = vi.spyOn(console, 'log');
    const warn = vi.spyOn(console, 'warn');
    const error = vi.spyOn(console, 'error');

    const client = new VannaApiClient({
      customHeaders: { Authorization: 'Bearer super-secret' },
    });

    expect(client.getCustomHeaders()).toEqual({ Authorization: 'Bearer super-secret' });
    expect(log).not.toHaveBeenCalled();
    expect(warn).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
    vi.restoreAllMocks();
  });

  it.each([
    ['', '/api/vanna/v2/chat_sse', '/api/vanna/v2/chat_sse'],
    [
      'https://api.example.test',
      '/api/vanna/v2/chat_poll',
      'https://api.example.test/api/vanna/v2/chat_poll',
    ],
    [
      'https://ignored.example.test',
      'https://custom.example.test/v2/chat',
      'https://custom.example.test/v2/chat',
    ],
  ])('resolves HTTP URL from base %j and endpoint %j', (baseUrl, endpoint, expected) => {
    expect(resolveHttpUrl(baseUrl, endpoint)).toBe(expected);
  });

  it.each([
    [
      'https://api.example.test/base/path',
      '/api/vanna/v2/chat_websocket',
      undefined,
      'wss://api.example.test/api/vanna/v2/chat_websocket',
    ],
    [
      'http://localhost:8000',
      '/api/vanna/v2/chat_websocket',
      undefined,
      'ws://localhost:8000/api/vanna/v2/chat_websocket',
    ],
    [
      '',
      'wss://custom.example.test/v2/chat',
      undefined,
      'wss://custom.example.test/v2/chat',
    ],
    [
      '',
      '/api/vanna/v2/chat_websocket',
      { protocol: 'https:', host: 'app.example.test' },
      'wss://app.example.test/api/vanna/v2/chat_websocket',
    ],
  ])(
    'resolves WebSocket URL from base %j and endpoint %j',
    (baseUrl, endpoint, location, expected) => {
      expect(resolveWebSocketUrl(baseUrl, endpoint, location)).toBe(expected);
    }
  );
});
