export const vowels = ["aa", "ih", "ou", "ee", "oh"] as const;
/** A bounded playback clock. Interruption discards all pending cues. */
export class Lips {
  private queue: { at: number; end: number; weights: number[] }[] = [];
  private end = 0;
  clear() { this.queue = []; this.end = 0; }
  push(event: any, now: number) {
    if (event.clear) { this.clear(); return; }
    const frames = event.frames;
    if (!Array.isArray(frames) || !frames.length || frames.length > 3000) return;
    const duration = Number(event.duration);
    if (!Number.isFinite(duration) || duration <= 0 || duration > 60) return;
    const delay = Number.isFinite(event.delay) ? Math.max(0, Math.min(1, event.delay)) : .08;
    const start = Math.max(now + delay, this.end);
    // Never animate a growing backlog after playback has already ended.
    if (start - now > 2) return;
    const step = duration / frames.length;
    frames.forEach((row: unknown, i: number) => {
      if (!Array.isArray(row) || row.length !== 5) return;
      const weights = row.map(x => Number.isFinite(x) ? Math.max(0, Math.min(1, x)) : 0);
      this.queue.push({ at: start + i * step, end: start + (i + 1) * step, weights });
    });
    this.end = start + duration;
    if (this.queue.length > 3200) this.queue.splice(0, this.queue.length - 3200);
  }
  sample(now: number) {
    while (this.queue.length && this.queue[0].end < now) this.queue.shift();
    const cue = this.queue[0];
    return cue && cue.at <= now ? cue.weights : [0, 0, 0, 0, 0];
  }
}
