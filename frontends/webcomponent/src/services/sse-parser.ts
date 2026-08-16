export interface ParsedSseEvent {
  data: string;
  event?: string;
  id?: string;
}

/** Incremental WHATWG event-stream parser for fetch response bytes. */
export class SseParser {
  private readonly decoder = new TextDecoder('utf-8', { fatal: true });
  private buffer = '';
  private dataLines: string[] = [];
  private eventName: string | undefined;
  private eventId: string | undefined;
  private sawData = false;

  push(bytes: Uint8Array): ParsedSseEvent[] {
    this.buffer += this.decoder.decode(bytes, { stream: true });
    return this.consumeCompleteLines(false);
  }

  finish(): ParsedSseEvent[] {
    this.buffer += this.decoder.decode();
    const events = this.consumeCompleteLines(true);

    // A conforming Vanna frame ends with a blank line. Keep incomplete data
    // undispatched so V3 terminal validation can fail closed.
    this.buffer = '';
    this.resetEvent();
    return events;
  }

  private consumeCompleteLines(final: boolean): ParsedSseEvent[] {
    const events: ParsedSseEvent[] = [];
    let offset = 0;

    while (offset < this.buffer.length) {
      let end = offset;
      while (
        end < this.buffer.length &&
        this.buffer[end] !== '\r' &&
        this.buffer[end] !== '\n'
      ) {
        end += 1;
      }

      if (end === this.buffer.length) {
        break;
      }
      if (
        this.buffer[end] === '\r' &&
        end + 1 === this.buffer.length &&
        !final
      ) {
        break;
      }

      const line = this.buffer.slice(offset, end);
      const lineEndingLength =
        this.buffer[end] === '\r' && this.buffer[end + 1] === '\n' ? 2 : 1;
      offset = end + lineEndingLength;
      const event = this.processLine(line);
      if (event) events.push(event);
    }

    this.buffer = this.buffer.slice(offset);
    return events;
  }

  private processLine(line: string): ParsedSseEvent | undefined {
    if (line === '') {
      if (!this.sawData) {
        this.resetEvent();
        return undefined;
      }
      const event: ParsedSseEvent = { data: this.dataLines.join('\n') };
      if (this.eventName !== undefined) event.event = this.eventName;
      if (this.eventId !== undefined) event.id = this.eventId;
      this.resetEvent();
      return event;
    }
    if (line.startsWith(':')) return undefined;

    const separator = line.indexOf(':');
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? '' : line.slice(separator + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    if (field === 'data') {
      this.sawData = true;
      this.dataLines.push(value);
    } else if (field === 'event') {
      this.eventName = value;
    } else if (field === 'id' && !value.includes('\0')) {
      this.eventId = value;
    }
    return undefined;
  }

  private resetEvent(): void {
    this.dataLines = [];
    this.eventName = undefined;
    this.eventId = undefined;
    this.sawData = false;
  }
}
