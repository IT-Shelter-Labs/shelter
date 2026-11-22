import assert from 'node:assert/strict';
import { test } from 'node:test';
import { command, Jobs, ownerChat } from '../game.mjs';
import { acquisitionPlan } from '../acquire.mjs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

test('only declared game skills, resources and quantities cross IPC', () => {
  assert.deepEqual(command({ op: 'mine', item: 'oak_log', count: 4, trail: 'ignored' }), { op: 'mine', item: 'oak_log', count: 4 });
  for (const input of [null, { op: 'exec' }, { op: 'say', text: '\u200b /op fake' },
    { op: 'mine', item: 'bedrock', count: 1 }, { op: 'craft', item: '/give', count: 1 },
    { op: 'set_mode', mode: 'creative @a' },
    { op: 'mine', item: 'oak_log', count: 17 }, { op: 'give', item: 'stone', count: 2.5 }]) {
    assert.throws(() => command(input), /bad_command/);
  }
});

test('stone from a starting inventory requires harvesting tools, a table, a furnace, and smelting', () => {
  for (const version of ['1.20.4', '1.21.5', '1.21.11']) {
    const registry = require('minecraft-data')(version);
    const Recipe = require('prismarine-recipe')(version).Recipe;
    const bot = { registry, inventory: { items: () => [] },
      recipesAll: (id, _, table) => Recipe.find(id, null).filter(r => table || !r.requiresTable) };
    const plan = acquisitionPlan(bot, 'stone', 8, new Map([['spruce_log', 10], ['stone', 30], ['coal_ore', 4]]));
    assert.ok(plan, version);
    const steps = plan.map(({ op, item }) => op + ':' + item);
    assert.ok(steps.indexOf('mine:spruce_log') < steps.indexOf('craft:spruce_planks'));
    assert.ok(steps.indexOf('place_station:crafting_table') < steps.indexOf('craft:wooden_pickaxe'));
    assert.ok(steps.indexOf('craft:wooden_pickaxe') < steps.indexOf('mine:stone'));
    assert.ok(steps.indexOf('mine:stone') < steps.indexOf('place_station:furnace'));
    assert.deepEqual(plan.at(-1), { op: 'smelt', item: 'stone', input: 'cobblestone', count: 8, fuel: 'coal', units: 1 });
    assert.equal(acquisitionPlan(bot, 'stone', 4, new Map([['stone', 30]])), null);
  }
});

test('chat requires the owner UUID and does not parse announcements or unverified online chat', () => {
  const player = { username: 'SomeOwner', uuid: 'example-uuid' };
  const valid = { plainMessage: '!jarvis инвентарь', sender: player.uuid, verified: true };
  assert.equal(ownerChat(valid, 'someowner', player, true), 'инвентарь');
  assert.equal(ownerChat({ ...valid, plainMessage: '!inv' }, 'someowner', player, true), 'open_inventory');
  assert.equal(ownerChat({ ...valid, plainMessage: '!inv', sender: 'another-uuid' }, 'someowner', player, true), null);
  assert.equal(ownerChat({ ...valid, sender: 'another-uuid' }, 'someowner', player, true), null);
  assert.equal(ownerChat({ ...valid, verified: false }, 'someowner', player, true), null);
  assert.equal(ownerChat({ ...valid, plainMessage: 'цитата !jarvis инвентарь' }, 'someowner', player, false), null);
});

test('cancellation wins over late completion and excludes concurrent work', async () => {
  let resume, halted = 0;
  const reports = [];
  const jobs = new Jobs(() => { halted++; resume?.(); }, result => reports.push(result));
  jobs.start(1, 'mine', async check => { await new Promise(resolve => { resume = resolve; }); check(); return { broken: 5 }; });
  assert.throws(() => jobs.start(2, 'come', () => {}), /busy/);
  const completion = jobs.active.done;
  await Promise.resolve();
  assert.equal(jobs.stop(), true);
  assert.equal(jobs.stop(), false);
  await completion;
  assert.equal(halted, 1);
  assert.deepEqual(reports, [{ id: 1, op: 'mine', state: 'stopped', result: 'stopped' }]);
  assert.equal(jobs.active, null);
});

test('queued tasks run in order and can be cancelled independently', async () => {
  const completed = [];
  let release;
  const jobs = new Jobs(() => {}, job => completed.push([job.id, job.state]));
  jobs.enqueue(1, { op: 'craft' }, () => new Promise(resolve => { release = resolve; }), 1000);
  assert.equal(jobs.enqueue(2, { op: 'build' }, () => assert.fail('cancelled task started'), 1000), 1);
  assert.equal(jobs.enqueue(3, { op: 'give' }, () => ({}), 1000), 2);
  assert.equal(jobs.cancel(2), true);
  assert.deepEqual(completed, [[2, 'stopped']]);
  const running = jobs.active.done;
  await Promise.resolve();
  release({});
  await running;
  assert.equal(jobs.active.id, 3);
  await jobs.active.done;
  assert.deepEqual(completed, [[2, 'stopped'], [1, 'done'], [3, 'done']]);
});
