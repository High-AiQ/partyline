import test from 'node:test';
import assert from 'node:assert/strict';
import { Decoder, packets, MAX_BYTES } from './wire.js';

test('large Unicode AX trees round-trip in bounded native frames', () => {
  const message = { id: 4, result: { nodes: ['💻'.repeat(300000)] } };
  const frames = packets(message), decoder = new Decoder();
  assert.ok(frames.length > 1);
  for (const packet of frames) {
    assert.ok(Buffer.byteLength(JSON.stringify(packet)) < 1024 * 1024);
    const last = packet.chunk.data.charCodeAt(packet.chunk.data.length - 1);
    assert.ok(last < 0xd800 || last > 0xdbff);
  }
  let result;
  for (const packet of frames) result = decoder.accept(packet);
  assert.deepEqual(result, message);
  assert.deepEqual(decoder.accept({ id: 5 }), { id: 5 });
});

test('bounded chunks refuse corruption, interleaving and oversized results', () => {
  assert.throws(() => packets({ value: 'a'.repeat(MAX_BYTES) }));
  for (const chunk of [{ index: 1, total: 2, data: 'a' }, { index: 0, total: 257, data: 'a' },
    { index: 0, total: 2, data: 5 }]) assert.throws(() => new Decoder().accept({ chunk }));
  const decoder = new Decoder();
  decoder.accept({ chunk: { index: 0, total: 2, data: 'a' } });
  assert.throws(() => decoder.accept({ id: 3 }));
  assert.throws(() => decoder.accept({ chunk: { index: 1, total: 3, data: 'b' } }));
  assert.throws(() => new Decoder().accept({ chunk: { index: 0, total: 2, data: 'a'.repeat(MAX_BYTES + 1) } }));
});
