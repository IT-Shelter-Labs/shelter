type Spring = { settings: { stiffness: number; gravityPower: number; hitRadius: number } };

/** three-vrm applies these forces/radii in world units. The desktop renderer
 * uses pixels as world units, so they must follow the actor's uniform scale.
 * Keep immutable originals: repeatedly multiplying would make springs explode.
 */
export class SpringScale {
  private entries: { spring: Spring; stiffness: number; gravityPower: number; hitRadius: number }[];
  private scale = NaN;
  constructor(springs: Iterable<Spring>) {
    this.entries = [...springs].map(spring => ({ spring, stiffness: spring.settings.stiffness,
      gravityPower: spring.settings.gravityPower, hitRadius: spring.settings.hitRadius }));
  }
  apply(scale: number) {
    if (!Number.isFinite(scale) || scale <= 0 || scale === this.scale) return;
    this.scale = scale;
    for (const entry of this.entries) {
      entry.spring.settings.stiffness = entry.stiffness * scale;
      entry.spring.settings.gravityPower = entry.gravityPower * scale;
      entry.spring.settings.hitRadius = entry.hitRadius * scale;
    }
  }
}
