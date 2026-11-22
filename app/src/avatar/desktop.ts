export type Rect = { x: number; y: number; width: number; height: number };
export type Point = { x: number; y: number };

export function destination(rect: Rect, position: string, width: number, height: number): Point {
  if (position === "home") position = "bottom-right";
  const mx = Math.min(rect.width / 2, width / 2 + 24);
  const top = rect.y + Math.min(rect.height, height + 24);
  return {
    x: /left/.test(position) ? rect.x + mx : /right/.test(position) ? rect.x + rect.width - mx : rect.x + rect.width / 2,
    y: /top/.test(position) ? top : position === "center" || position === "left" || position === "right" ?
      rect.y + (rect.height + Math.min(height, rect.height)) / 2 : rect.y + rect.height - 16,
  };
}

export class Travel {
  point: Point;
  private from: Point;
  private to: Point;
  private started = 0;
  private duration = 0;
  private acceleration = 0;
  private distance = 0;
  private cruise = 180;
  direction: Point = { x: 0, y: 0 };
  speed = 0;
  travelled = 0;
  moving = false;
  constructor(point: Point) { this.point = { ...point }; this.from = { ...point }; this.to = { ...point }; }
  start(to: Point, now: number, speed = 180, turnDelay = 0.4) {
    this.from = { ...this.point }; this.to = { ...to }; this.started = now + turnDelay;
    this.distance = Math.hypot(to.x - this.point.x, to.y - this.point.y);
    this.direction = this.distance > 0 ? { x: (to.x - this.point.x) / this.distance, y: (to.y - this.point.y) / this.distance } : { x: 0, y: 0 };
    this.cruise = Math.max(30, speed);
    this.acceleration = Math.min(0.35, this.distance / this.cruise);
    this.duration = this.distance / this.cruise + this.acceleration;
    this.speed = 0; this.travelled = 0;
    this.moving = this.distance > 0.5;
  }
  update(now: number) {
    if (!this.moving) { this.speed = 0; return; }
    const t = Math.max(0, Math.min(this.duration, now - this.started)), a = this.acceleration;
    const ramp = (x: number) => this.cruise * (x / 2 - a / (2 * Math.PI) * Math.sin(Math.PI * x / a));
    const distance = t < a ? ramp(t) : t > this.duration - a ? this.distance - ramp(this.duration - t) : this.cruise * (t - a / 2);
    this.speed = this.cruise * (t < a ? (1 - Math.cos(Math.PI * t / a)) / 2 : t > this.duration - a ? (1 - Math.cos(Math.PI * (this.duration - t) / a)) / 2 : 1);
    this.travelled = Math.max(0, Math.min(this.distance, distance));
    this.point = { x: this.from.x + this.direction.x * this.travelled, y: this.from.y + this.direction.y * this.travelled };
    if (t >= this.duration) { this.point = { ...this.to }; this.moving = false; this.speed = 0; }
  }
  drag(point: Point) { this.point = { ...point }; this.moving = false; this.speed = 0; this.travelled = 0; }
}
