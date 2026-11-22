export function captionPosition(x: number, headY: number, width: number, height: number, viewportWidth: number, viewportHeight: number) {
  return {
    left: Math.max(8, Math.min(Math.max(8, viewportWidth-width-8), x-width/2)),
    top: Math.max(8, Math.min(Math.max(8, viewportHeight-height-8), headY-height-12)),
  };
}

/** Subtitles, task status and errors share one flow; never overlay each other. */
export class CaptionLayout {
  private width = 320;
  private height = 0;
  private observer: ResizeObserver;
  private root: HTMLElement;
  constructor(root: HTMLElement) {
    this.root = root;
    this.observer = new ResizeObserver(entries => {
      const entry = entries[0];
      if (entry) { this.width=entry.contentRect.width; this.height=entry.contentRect.height; }
    });
    this.observer.observe(root);
  }
  place(x: number, headY: number) {
    const p=captionPosition(x,headY,this.width,this.height,innerWidth,innerHeight);
    this.root.style.left=`${Math.round(p.left)}px`;
    this.root.style.top=`${Math.round(p.top)}px`;
  }
  dispose() { this.observer.disconnect(); }
}
