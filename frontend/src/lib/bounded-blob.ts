/** Read at most the viewer limit even when the server's size metadata is wrong. */
export async function boundedBlob(response: Response, maxBytes: number): Promise<Blob> {
  const reader = response.body?.getReader();
  if (!reader) {
    const blob = await response.blob();
    if (blob.size > maxBytes) throw new Error("file is too large to view");
    return blob;
  }
  const chunks: Uint8Array<ArrayBuffer>[] = [];
  let size = 0;
  let part = await reader.read();
  while (!part.done) {
    size += part.value.byteLength;
    if (size > maxBytes) {
      await reader.cancel();
      throw new Error("file is too large to view");
    }
    chunks.push(part.value);
    part = await reader.read();
  }
  return new Blob(chunks);
}
