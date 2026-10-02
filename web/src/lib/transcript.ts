/** Persisted transcript after a stream error. Drops the in-flight placeholder. */
export function transcriptAfterFailedStream<T extends { id: string }>(persisted: T[]): T[] {
  return persisted.filter(
    (message) => message.id !== "streaming" && !message.id.startsWith("unsaved-")
  );
}
