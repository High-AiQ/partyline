// Native frames are <=1 MiB; large CDP trees cross as bounded, sequential chunks.
export const MAX_BYTES = 16 * 1024 * 1024;
export function packets(message) {
  const text = JSON.stringify(message);
  if (new TextEncoder().encode(text).length > MAX_BYTES) throw Error('Message too large');
  if (text.length <= 128 * 1024) return [message];
  const parts = [];
  for (let offset = 0; offset < text.length;) {
    let end = Math.min(offset + 128 * 1024, text.length);
    const last = text.charCodeAt(end - 1);
    if (last >= 0xd800 && last <= 0xdbff) end--; // keep a Unicode surrogate pair in one chunk
    parts.push(text.slice(offset, end));
    offset = end;
  }
  return parts.map((data, index) => ({ chunk: { index, total: parts.length, data } }));
}
export class Decoder {
  constructor() { this.parts = []; this.bytes = 0; }
  accept(message) {
    if (!message.chunk) {
      if (this.parts.length) throw Error('Interrupted chunks');
      return message;
    }
    const { index, total, data } = message.chunk;
    if (!Number.isInteger(total) || total < 2 || total > 256 || index !== this.parts.length ||
        typeof data !== 'string' || (this.total && this.total !== total)) throw Error('Invalid chunks');
    this.total = total;
    this.bytes += new TextEncoder().encode(data).length;
    if (this.bytes > MAX_BYTES) throw Error('Message too large');
    this.parts.push(data);
    if (index + 1 !== total) return null;
    const result = JSON.parse(this.parts.join(''));
    this.parts = []; this.bytes = 0; this.total = null;
    return result;
  }
}
