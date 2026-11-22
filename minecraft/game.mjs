export const MAX_COUNT = 16;
const MOD_ITEM = /^[a-z0-9][a-z0-9_.-]{0,31}:[a-z0-9][a-z0-9_./-]{0,63}$/;

export function command(data, nested = false) {
  if (!data || typeof data !== 'object' || Array.isArray(data)) throw Error('bad_command');
  if (!nested && data.op === 'sequence' && Array.isArray(data.actions) && data.actions.length >= 2 && data.actions.length <= 5) {
    const actions = data.actions.map(action => command(action, true));
    if (actions.every(action => ['come', 'navigate', 'give', 'deliver', 'mine', 'craft', 'equip', 'obtain', 'build', 'eat', 'fish'].includes(action.op)))
      return { op: 'sequence', actions };
  }
  if (['status', 'position', 'nearby', 'follow', 'guard', 'come', 'eat', 'fish', 'teleport', 'stop', 'quit'].includes(data.op)) return { op: data.op };
  if (data.op === 'navigate' && [data.x, data.y, data.z].every(n => Number.isSafeInteger(n) && Math.abs(n) <= 30_000_000))
    return { op: data.op, x: data.x, y: data.y, z: data.z };
  if (data.op === 'set_mode' && ['survival', 'creative', 'adventure', 'spectator'].includes(data.mode))
    return { op: data.op, mode: data.mode };
  if (data.op === 'cancel_job' && Number.isSafeInteger(data.jobId) && data.jobId > 0) return { op: data.op, jobId: data.jobId };
  if (data.op === 'say' && typeof data.text === 'string') {
    const text = data.text.replace(/[\p{Cc}\p{Cf}§]/gu, ' ').trim();
    if (text && !text.startsWith('/')) return { op: 'say', text: Array.from(text).slice(0, 180).join('') };
  }
  if (['mine', 'craft', 'obtain', 'give', 'give_stock', 'deliver', 'equip', 'build'].includes(data.op) && typeof data.item === 'string' &&
      (/^[a-z0-9_]{1,48}$/.test(data.item) || MOD_ITEM.test(data.item)) &&
      Number.isInteger(data.count) && data.count >= 1 && data.count <= MAX_COUNT &&
      !(data.op === 'mine' && data.item === 'bedrock')) {
    if (data.op === 'build') {
      if (!['line', 'wall', 'floor'].includes(data.shape)) throw Error('bad_command');
      return { op: data.op, shape: data.shape, item: data.item, count: data.count };
    }
    return { op: data.op, item: data.item, count: data.count };
  }
  throw Error('bad_command');
}

export function ownerChat(packet, owner, player, requireSignature) {
  if (!player || player.username.toLowerCase() !== owner.toLowerCase() || !player.uuid ||
      packet.sender !== player.uuid || (requireSignature && packet.verified !== true)) return null;
  if (typeof packet.plainMessage !== 'string') return null;
  const message = packet.plainMessage.trim();
  if (/^!(?:inv|инвентарь)$/iu.test(message)) return 'open_inventory';
  const text = message.match(/^!(?:jarvis|джарвис)\s+(.{1,200})$/iu)?.[1]?.trim();
  return text || null;
}

export function itemCount(bot, item) {
  const registry = bot.registry?.itemsByName ?? {};
  const id = Object.hasOwn(registry, item) ? registry[item].id : null;
  return bot.inventory.items().filter(stack => id == null ? stack.name === item : stack.type === id)
    .reduce((sum, stack) => sum + stack.count, 0);
}

export function registryItem(registry, name) {
  const entry = Object.hasOwn(registry, name) ? registry[name] : null;
  if (!entry || !Number.isInteger(entry.id)) throw Error(MOD_ITEM.test(name) ? 'mod_item_unavailable' : 'not_found');
  return entry;
}

export class Jobs {
  constructor(halt, finish) {
    this.halt = halt;
    this.finish = finish;
    this.active = null;
    this.queue = [];
  }

  start(id, op, func, timeout = 45_000, request = { op }) {
    if (this.active) throw Error('busy');
    const job = { id, op, request, reason: '' };
    this.active = job;
    const check = () => { if (job.reason || this.active !== job) throw Error(job.reason || 'stopped'); };
    if (timeout > 0) job.timer = setTimeout(() => this.stop('timeout'), timeout);
    job.done = Promise.resolve().then(() => { check(); return func(check); }).then(
      result => { check(); return ['done', result]; }
    ).catch(error => [job.reason || 'failed', error instanceof Error ? error.message : 'failed']).then(([state, result]) => {
      clearTimeout(job.timer);
      if (this.active === job) this.active = null;
      this.finish({ id, op, state, result });
      if (!this.active && this.queue.length) {
        const next = this.queue.shift();
        this.start(next.id, next.request.op, next.run, next.timeout, next.request);
      }
    });
  }

  enqueue(id, request, run, timeout) {
    if (!this.active) {
      this.start(id, request.op, run, timeout, request);
      return 0;
    }
    if (this.queue.length >= 5 || ['guard', 'follow'].includes(request.op)) throw Error('busy');
    this.queue.push({ id, request, run, timeout });
    return this.queue.length;
  }

  cancel(id) {
    if (this.active?.id === id) return this.stop();
    const index = this.queue.findIndex(job => job.id === id);
    if (index < 0) return false;
    const [job] = this.queue.splice(index, 1);
    this.finish({ id, op: job.request.op, state: 'stopped', result: 'stopped' });
    return true;
  }

  stopAll(reason = 'stopped') {
    const queued = this.queue.splice(0);
    for (const job of queued) this.finish({ id: job.id, op: job.request.op, state: 'stopped', result: 'stopped' });
    return this.stop(reason) || queued.length > 0;
  }

  stop(reason = 'stopped') {
    const job = this.active;
    if (!job || job.reason) return false;
    job.reason = reason;
    this.halt();
    return true;
  }

  replaceFollow() {
    if (!['follow', 'guard'].includes(this.active?.op)) return;
    this.stop('replaced');
    // stop() synchronously detaches navigation; the old job's promise may settle later.
    this.active = null;
  }
}
