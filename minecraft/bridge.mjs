import readline from 'node:readline';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { acquisitionPlan } from './acquire.mjs';
import { planCraft, matchingItems, itemGroups } from './recipes.mjs';
import { command, itemCount, Jobs, ownerChat, registryItem } from './game.mjs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

const emit = value => process.stdout.write(`${JSON.stringify(value)}\n`);
console.log = console.info = console.warn = console.error = () => {};
delete process.env.DEBUG;

const { default: mineflayer } = await import('mineflayer');
const { pathfinder, Movements, goals } = (await import('mineflayer-pathfinder')).default;
const { GoalNear, GoalFollow, GoalLookAtBlock } = goals;
const RANGE = 24;
const errors = new Set(['busy', 'bad_command', 'not_ready', 'owner_far', 'owner_absent', 'not_found', 'need_tool',
  'no_recipe', 'not_enough', 'no_space', 'blocked', 'unconfirmed', 'unsafe', 'stopped', 'timeout', 'owner_left', 'respawn',
  'need_logs', 'craft_unconfirmed', 'give_unconfirmed', 'teleport_denied', 'mode_denied', 'place_unconfirmed',
  'no_plan', 'furnace_busy', 'missing_drop', 'no_food', 'eat_unconfirmed', 'fish_unconfirmed', 'mod_item_unavailable']);
let bot, options, ready = false, follow = null, cancelTeleport = null, lastChat = 0, lastSay = 0;
let cancelFishing = null;
let warnedChat = false;

function stopMotion() {
  const endFollowing = follow;
  follow = null;
  if (bot?.entity && bot.pathfinder) bot.pathfinder.setGoal(null);
  if (bot?.targetDigBlock) bot.stopDigging();
  if (jobs.active?.op === 'eat') bot.deactivateItem();
  if (bot?.entity) bot.clearControlStates();
  cancelTeleport?.();
  cancelFishing?.();
  endFollowing?.();
}

const jobs = new Jobs(stopMotion, result => emit({ event: 'job', ...result,
  result: typeof result.result !== 'string' || errors.has(result.result) ? result.result : 'blocked' }));

function ownerInfo() {
  return Object.values(bot.players).find(value => value.username.toLowerCase() === options.owner.toLowerCase());
}

function owner(max = RANGE) {
  const player = ownerInfo()?.entity;
  if (!player || player === bot.entity) throw Error('owner_absent');
  if (player.position.distanceTo(bot.entity.position) > max) throw Error('owner_far');
  return player;
}

function location() {
  const position = bot.entity.position;
  return { position: [Math.floor(position.x), Math.floor(position.y), Math.floor(position.z)], dimension: bot.game.dimension };
}

function state() {
  const player = ownerInfo()?.entity;
  const position = entity => entity.position.toArray().map(Math.floor);
  const nearby = Object.values(bot.entities).filter(entity => entity !== bot.entity && entity.name &&
    entity.position.distanceTo(bot.entity.position) <= 16)
    .sort((a, b) => a.position.distanceTo(bot.entity.position) - b.position.distanceTo(bot.entity.position))
    .slice(0, 12).map(entity => ({ name: entity.name, position: position(entity) }));
  return { name: bot.username, version: bot.version, health: bot.health, food: bot.food, ...location(),
    gameMode: bot.game.gameMode, heldItem: bot.heldItem?.name || '',
    ownerPosition: player ? position(player) : null, nearby, timeOfDay: bot.time.timeOfDay, raining: bot.isRaining,
    items: [...new Set(bot.inventory.items().map(item => item.name))].slice(0, 36).map(name => [name, itemCount(bot, name)]),
    progress: jobs.active?.progress || '', active: jobs.active?.op || '', step: jobs.active?.step || '',
    task: jobs.active ? taskInfo(jobs.active) : null, queue: jobs.queue.map(taskInfo) };
}

function taskInfo(job) {
  const { op, item, count, mode } = job.request;
  return { id: job.id, op, item, count, mode };
}

async function goto(goal, check) {
  check();
  await bot.pathfinder.goto(goal);
  check();
}

async function digConfirmed(block, check) {
  let confirm;
  const confirmed = new Promise(resolve => { confirm = resolve; });
  const onBlock = packet => {
    if (block.position.equals(packet.location) && bot.blockAt(block.position)?.type === 0) confirm(true);
  };
  const onSection = packet => {
    const section = packet.chunkCoordinates;
    if (!section || !bot.supportFeature('usesMultiblockSingleLong')) return;
    const { x, y, z } = block.position;
    if (section.x !== (x >> 4) || section.y !== (y >> 4) || section.z !== (z >> 4)) return;
    const packed = ((x & 15) << 8) | ((z & 15) << 4) | (y & 15);
    if (packet.records.some(entry => (Number(entry) & 4095) === packed) && bot.blockAt(block.position)?.type === 0) confirm(true);
  };
  let timer;
  bot._client.on('block_change', onBlock);
  bot._client.on('multi_block_change', onSection);
  try {
    await bot.dig(block, true, 'raycast');
    check();
    const changed = await Promise.race([confirmed, new Promise(resolve => { timer = setTimeout(() => resolve(false), 1250); })]);
    check();
    if (!changed || bot.blockAt(block.position)?.type === block.type) throw Error('unconfirmed');
  } finally {
    clearTimeout(timer);
    bot._client.off('block_change', onBlock);
    bot._client.off('multi_block_change', onSection);
  }
}

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function safeToDig(target) {
  if (target.equals(bot.entity.position.floored().offset(0, -1, 0))) return false;
  const above = bot.blockAt(target.offset(0, 1, 0));
  const offsets = [[1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1], [0, 1, 0]];
  return !/sand|gravel|concrete_powder|anvil/.test(above?.name || '') &&
    !offsets.some(offset => /^(water|lava)$/.test(bot.blockAt(target.offset(...offset))?.name || ''));
}

async function collectDrop(target, drop, before, check) {
  for (let tick = 0; tick < 10; tick++) {
    check();
    if (itemCount(bot, drop) > before) return;
    const entity = Object.values(bot.entities).find(candidate => candidate.name === 'item' &&
      candidate.position.distanceTo(target) < 2.5 && candidate.getDroppedItem?.()?.name === drop);
    if (entity && entity.position.distanceTo(bot.entity.position) > 0.9) {
      try { await goto(new GoalNear(entity.position.x, entity.position.y, entity.position.z, 0), check); }
      catch { check(); return; }
    }
    await delay(100);
  }
}

async function mine({ item, count, drop: expected }, check) {
  const type = registryItem(bot.registry.blocksByName, item);
  const drop = expected || bot.registry.items[type.drops?.[0]]?.name || item;
  const startCount = itemCount(bot, drop);
  const origin = bot.entity.position.clone();
  let broken = 0;
  let warning = '';
  try {
    for (let index = 0; index < count; index++) {
      check();
      owner();
      if (!bot.inventory.emptySlotCount() && !bot.inventory.items().some(stack => stack.name === drop && stack.count < stack.stackSize)) throw Error('no_space');
      const targets = bot.findBlocks({ matching: type.id, maxDistance: 12, count: 24,
        useExtraInfo: block => block.position.distanceTo(origin) <= 12 &&
          block.position.distanceTo(bot.entity.position) <= 12 });
      if (!targets.length) throw Error('not_found');
      let error;
      for (const target of targets.slice(0, 6)) {
        check();
        try {
          if (!safeToDig(target)) throw Error('unsafe');
          await goto(new GoalLookAtBlock(target, bot.world, { reach: 4 }), check);
          owner();
          const block = bot.blockAt(target);
          if (!block || block.type !== type.id || !bot.canDigBlock(block)) throw Error('blocked');
          if (!safeToDig(target)) throw Error('unsafe');
          const tool = bot.pathfinder.bestHarvestTool(block);
          if (block.harvestTools && (!tool || !block.harvestTools[tool.type])) throw Error('need_tool');
          if (tool) await bot.equip(tool, 'hand');
          check();
          const before = itemCount(bot, drop);
          await digConfirmed(block, check);
          broken++;
          await collectDrop(target, drop, before, check);
          error = null;
          break;
        } catch (failure) {
          check();
          if (['need_tool', 'unconfirmed', 'owner_absent', 'owner_far'].includes(failure.message)) throw failure;
          error = failure;
        }
      }
      if (error) throw error;
    }
  } catch (error) {
    check();
    if (!broken) throw error;
    warning = errors.has(error.message) ? error.message : 'blocked';
  }
  return { broken, collected: Math.max(0, itemCount(bot, drop) - startCount), item: drop, warning };
}

async function craft({ item, count }, check) {
  const product = registryItem(bot.registry.itemsByName, item);
  const before = itemCount(bot, item);
  const table = nearbyTable();
  const plan = planCraft(bot, product, count, table);
  if (!plan) throw Error('no_recipe');
  for (const { recipe, batches } of plan) {
    const station = recipe.requiresTable ? table : null;
    if (station && station.position.distanceTo(bot.entity.position) > 4)
      await goto(new GoalLookAtBlock(station.position, bot.world, { reach: 4 }), check);
    for (let i = 0; i < batches; i++) {
      check();
      owner();
      await bot.craft(recipe, 1, station);
    }
    check();
    await confirmInventory(check, 'craft_unconfirmed');
  }
  const made = itemCount(bot, item) - before;
  if (made < count) throw Error('craft_unconfirmed');
  return { count: made, item };
}

async function confirmInventory(check, failure) {
  if (!bot.supportFeature('stateIdUsed')) return;
  let timer;
  try {
    const synced = await Promise.race([
      bot._syncWindow(bot.inventory).then(() => true),
      new Promise(resolve => { timer = setTimeout(() => resolve(false), 2500); })
    ]);
    check();
    if (!synced) throw Error(failure);
  } finally { clearTimeout(timer); }
}

function nearbyTable() {
  return bot.findBlock({ matching: bot.registry.blocksByName.crafting_table.id, maxDistance: 6 });
}

function resolveGroup(request) {
  const candidates = matchingItems(bot, request.item);
  const stock = name => itemCount(bot, name);
  candidates.sort((a, b) => stock(b.name) - stock(a.name));
  if (!candidates.length) throw Error('not_found');
  if (request.op !== 'craft' && stock(candidates[0].name) >= request.count) return candidates[0].name;
  const table = nearbyTable();
  for (const product of candidates) {
    const needed = request.count - (request.op === 'craft' ? 0 : stock(product.name));
    if (bot.recipesFor(product.id, null, needed, table).length) return product.name;
  }
  for (const product of candidates)
    if (planCraft(bot, product, request.count - (request.op === 'craft' ? 0 : stock(product.name)), table)) return product.name;
  if (request.item === 'planks' && ['obtain', 'deliver', 'give', 'build'].includes(request.op)) {
    const logs = Object.values(bot.registry.blocksByName).filter(block => block.name.endsWith('_log'));
    const nearby = bot.findBlock({ matching: logs.map(block => block.id), maxDistance: 12 });
    if (nearby) return nearby.name.replace(/_log$/, '_planks');
  }
  throw Error('no_recipe');
}

async function obtain({ item, count }, check) {
  if (itemCount(bot, item) >= count) return { count: itemCount(bot, item), item };
  const product = registryItem(bot.registry.itemsByName, item);
  if (bot.game.gameMode === 'creative' && bot.supportFeature('stateIdUsed')) {
    const Item = require('prismarine-item')(bot.registry);
    const missing = count - itemCount(bot, item);
    jobs.active.step = 'creative_inventory';
    for (let remaining = missing; remaining > 0;) {
      check();
      const slot = bot.inventory.firstEmptyInventorySlot();
      if (slot == null) throw Error('no_space');
      const quantity = Math.min(remaining, product.stackSize);
      await bot.creative.setInventorySlot(slot, new Item(product.id, quantity));
      remaining -= quantity;
    }
    await confirmInventory(check, 'craft_unconfirmed');
    if (itemCount(bot, item) < count) throw Error('craft_unconfirmed');
    return { count: itemCount(bot, item), item };
  }
  const area = new Map();
  const origin = bot.entity.position.floored();
  for (let x = -12; x <= 12; x++) for (let z = -12; z <= 12; z++) for (let y = -8; y <= 9; y++) {
    if (x*x + y*y + z*z > 144) continue;
    const block = bot.blockAt(origin.offset(x, y, z), false);
    if (block?.diggable) area.set(block.name, 1 + (area.get(block.name) || 0));
  }
  const steps = acquisitionPlan(bot, item, count, area);
  if (!steps) throw Error(item.endsWith('_planks') ? 'need_logs' : 'no_plan');
  for (const [i, step] of steps.entries()) {
    check();
    owner();
    jobs.active.step = step.op;
    jobs.active.progress = (i + 1) + '/' + steps.length + ' · ' + step.item;
    if (step.op === 'mine') {
      const result = await mine(step, check);
      if (result.collected < step.count) throw Error('missing_drop');
    } else if (step.op === 'place_station') {
      await placeStation(step.item, check);
    } else if (step.op === 'smelt') {
      await smelt(step, check);
    } else {
      const table = step.recipe.requiresTable ? await reachStation('crafting_table', check) : null;
      const before = itemCount(bot, step.item);
      for (let n = 0; n < step.batches; n++) { check(); await bot.craft(step.recipe, 1, table); }
      check();
      await confirmInventory(check, 'craft_unconfirmed');
      if (itemCount(bot, step.item) < before + step.recipe.result.count * step.batches) throw Error('craft_unconfirmed');
    }
  }
  if (itemCount(bot, item) < count) throw Error('not_enough');
  return { count: itemCount(bot, item), item };
}

async function reachStation(item, check) {
  const block = bot.findBlock({ matching: bot.registry.blocksByName[item].id, maxDistance: RANGE });
  if (!block) throw Error('not_found');
  if (bot.entity.position.distanceTo(block.position) > 4) await goto(new GoalLookAtBlock(block.position, bot.world, { reach: 4 }), check);
  check();
  return block;
}

async function placeStation(item, check) {
  const origin = bot.entity.position.floored();
  const stack = bot.inventory.items().find(s => s.name === item);
  if (!stack) throw Error('not_enough');
  for (const [x, z] of [[1,0],[-1,0],[0,1],[0,-1],[1,1],[-1,-1],[2,0],[0,2]]) {
    const target = origin.offset(x, 0, z);
    const support = bot.blockAt(target.offset(0, -1, 0));
    if (bot.blockAt(target)?.name !== 'air' || support?.boundingBox !== 'block' ||
        owner().position.floored().equals(target)) continue;
    await bot.equip(stack, 'hand');
    check();
    await bot.placeBlock(support, target.minus(support.position));
    check();
    if (bot.blockAt(target)?.name === item) return;
    throw Error('place_unconfirmed');
  }
  throw Error('blocked');
}

async function smelt(step, check) {
  const block = await reachStation('furnace', check);
  const furnace = await bot.openFurnace(block);
  try {
    check();
    if (furnace.inputItem() || furnace.outputItem() || furnace.fuelItem()) throw Error('furnace_busy');
    await furnace.putFuel(bot.registry.itemsByName[step.fuel].id, null, step.units);
    check();
    await furnace.putInput(bot.registry.itemsByName[step.input].id, null, step.count);
    const deadline = Date.now() + (step.count * 14 + 12) * 1000;
    while ((furnace.outputItem()?.count || 0) < step.count) {
      await delay(250);
      check();
      if (Date.now() > deadline || (furnace.outputItem() && furnace.outputItem().name !== step.item)) throw Error('unconfirmed');
    }
    if (furnace.outputItem().name !== step.item) throw Error('unconfirmed');
    await furnace.takeOutput();
  } finally { furnace.close(); }
  check();
  await confirmInventory(check, 'craft_unconfirmed');
}

async function teleport(check) {
  const target = ownerInfo()?.username;
  if (!target || !/^[A-Za-z0-9_]{3,16}$/.test(target)) throw Error('owner_absent');
  let finish, timer, moved, acknowledged = false;
  const start = bot.entity.position.clone();
  const done = new Promise(resolve => { finish = resolve; });
  const onMove = () => {
    moved = location();
    const near = ownerInfo()?.entity?.position.distanceTo(bot.entity.position) <= 3;
    if (acknowledged || (near && start.distanceTo(bot.entity.position) > 0.25)) finish(moved);
  };
  const onMessage = (message, position) => {
    if (position !== 'system') return;
    if (message.translate === 'commands.teleport.success.entity.single') {
      const [source, destination] = (message.with || []).map(part => part.toString().toLowerCase());
      if (source !== bot.username.toLowerCase() || destination !== target.toLowerCase()) return;
      acknowledged = true;
      if (moved) finish(moved);
    } else if (message.translate === 'command.unknown.command') finish(null);
  };
  cancelTeleport = () => finish(null);
  bot.on('forcedMove', onMove);
  bot.on('message', onMessage);
  try {
    check();
    // The server checks teleport permission.
    bot.chat('/tp @s ' + target);
    timer = setTimeout(() => finish(null), 4200);
    const result = await done;
    check();
    if (!result) throw Error('teleport_denied');
    return result;
  } finally {
    clearTimeout(timer);
    bot.off('forcedMove', onMove);
    bot.off('message', onMessage);
    cancelTeleport = null;
  }
}

// Weapon preference adapted from Mindcraft's equipHighestAttack (MIT, see MINDCRAFT-LICENSE).
function guardWeapon() {
  const rank = name => {
    const [material, kind] = name.split('_');
    const tier = ['wooden', 'golden', 'stone', 'iron', 'diamond', 'netherite'].indexOf(material);
    return ({ sword: 30, axe: 20, pickaxe: 10, shovel: 5 }[kind] || -100) + tier;
  };
  return bot.inventory.items().filter(item => rank(item.name) > 0).sort((a, b) => rank(b.name) - rank(a.name))[0];
}

async function guard(check) {
  let following, lastHit = 0;
  try {
    while (true) {
      check();
      const player = owner();
      const enemies = Object.values(bot.entities).filter(e => e.isValid !== false &&
        bot.registry.entitiesByName[e.name]?.type === 'hostile' && e.position.distanceTo(player.position) <= 9);
      enemies.sort((a, b) => a.position.distanceTo(player.position) - b.position.distanceTo(player.position));
      const enemy = enemies[0];
      const target = enemy || player;
      jobs.active.step = enemy ? 'defend' : 'watch';
      if (following !== target) {
        bot.pathfinder.setGoal(new GoalFollow(target, 2), true);
        following = target;
      }
      if (enemy && enemy.position.distanceTo(bot.entity.position) <= 3 && Date.now() - lastHit >= 1000) {
        const weapon = guardWeapon();
        if (weapon && bot.heldItem?.type !== weapon.type) await bot.equip(weapon, 'hand');
        await bot.lookAt(enemy.position.offset(0, enemy.height * 0.6, 0));
        check();
        if (enemy.isValid !== false && enemy.position.distanceTo(bot.entity.position) <= 3) {
          bot.attack(enemy);
          lastHit = Date.now();
        }
      }
      await delay(200);
    }
  } finally {
    if (jobs.active?.op === 'guard' && !jobs.active.reason) bot.pathfinder.setGoal(null);
  }
}

async function build({ item, count, shape }, check) {
  const type = registryItem(bot.registry.blocksByName, item);
  const origin = bot.entity.position.floored();
  if (itemCount(bot, item) < count) await obtain({ item, count }, check);
  const width = shape === 'line' ? count : Math.ceil(Math.sqrt(count));
  let placed = 0;
  try {
    for (; placed < count; placed++) {
      check();
      owner();
      const row = Math.floor(placed / width);
      const target = origin.offset(placed % width, shape === 'wall' ? row : 0, 2 + (shape === 'floor' ? row : 0));
      const support = bot.blockAt(target.offset(0, -1, 0));
      if (bot.blockAt(target)?.name !== 'air' || support?.boundingBox !== 'block') throw Error('blocked');
      if (target.distanceTo(bot.entity.position) > 4) await goto(new GoalLookAtBlock(support.position, bot.world, { reach: 4 }), check);
      const stack = bot.inventory.items().find(s => s.name === item);
      if (!stack) throw Error('not_enough');
      await bot.equip(stack, 'hand');
      check();
      await bot.placeBlock(support, target.minus(support.position));
      check();
      if (bot.blockAt(target)?.type !== type.id) throw Error('place_unconfirmed');
    }
  } catch (error) {
    check();
    return { placed, count, item, warning: errors.has(error.message) ? error.message : 'place_unconfirmed' };
  }
  return { placed, count, item };
}

// Water selection and fishing flow adapted from the MIT MinePal fork (MINEPAL-LICENSE).
async function fish(check) {
  const rod = bot.inventory.items().find(item => item.name === 'fishing_rod');
  if (!rod) throw Error('need_tool');
  const waters = bot.findBlocks({ matching: bot.registry.blocksByName.water.id, maxDistance: 12, count: 40 });
  let water;
  for (const pos of waters.filter(p => bot.blockAt(p.offset(0, 1, 0))?.name === 'air').slice(0, 5)) {
    try {
      await goto(new GoalNear(pos.x, pos.y, pos.z, 3), check);
      water = pos;
      break;
    } catch { check(); }
  }
  if (!water) throw Error('not_found');
  const before = new Map(bot.inventory.items().map(item => [item.name, itemCount(bot, item.name)]));
  await bot.equip(rod, 'hand');
  await bot.lookAt(water.offset(0.5, 0.5, 0.5));
  check();
  let timer;
  const stopped = new Promise(resolve => {
    timer = setTimeout(() => cancelFishing?.(), 75_000);
    cancelFishing = () => {
      if (ready && bot.heldItem?.name === 'fishing_rod') bot.activateItem();
      resolve(false);
    };
  });
  try {
    const caught = await Promise.race([bot.fish().then(() => true), stopped]);
    clearTimeout(timer);
    cancelFishing = null;
    check();
    if (!caught) throw Error('fish_unconfirmed');
    for (let tick = 0; tick < 30; tick++) {
      check();
      const item = bot.inventory.items().find(i => itemCount(bot, i.name) > (before.get(i.name) || 0));
      if (item) return { item: item.name, count: itemCount(bot, item.name) - (before.get(item.name) || 0) };
      await delay(100);
    }
    throw Error('fish_unconfirmed');
  } finally { clearTimeout(timer); cancelFishing = null; }
}

async function act(request, check) {
  if (request.op === 'sequence') {
    const done = [];
    for (const [index, action] of request.actions.entries()) {
      check();
      jobs.active.step = action.op;
      jobs.active.progress = (index + 1) + '/' + request.actions.length;
      try {
        const result = await act(action, check);
        done.push({ op: action.op, result });
        if (result.warning) return { done, total: request.actions.length, warning: result.warning };
      } catch (error) {
        check();
        return { done, total: request.actions.length, warning: errors.has(error.message) ? error.message : 'blocked' };
      }
    }
    return { done, total: request.actions.length };
  }
  if (itemGroups.has(request.item)) {
    if (['give', 'deliver'].includes(request.op)) {
      const stacks = matchingItems(bot, request.item).map(({ name }) => [name, itemCount(bot, name)]).filter(([, n]) => n);
      if (stacks.reduce((sum, [, n]) => sum + n, 0) >= request.count) {
        let remaining = request.count;
        for (const [item, n] of stacks) {
          const count = Math.min(remaining, n);
          await act({ op: 'give', item, count }, check);
          remaining -= count;
          if (!remaining) break;
        }
        return { item: request.item, count: request.count };
      }
    }
    request = { ...request, item: resolveGroup(request) };
  }
  if (request.op === 'set_mode') {
    if (bot.game.gameMode !== request.mode) {
      bot.chat('/gamemode ' + request.mode + ' @s');
      for (let i = 0; i < 32 && bot.game.gameMode !== request.mode; i++) { await delay(100); check(); }
    }
    if (bot.game.gameMode !== request.mode) throw Error('mode_denied');
    return { mode: bot.game.gameMode };
  }
  if (request.op === 'guard') return guard(check);
  if (request.op === 'fish') return fish(check);
  if (request.op === 'navigate') {
    const target = bot.entity.position.offset(request.x - bot.entity.position.x, request.y - bot.entity.position.y, request.z - bot.entity.position.z);
    if (target.distanceTo(owner().position) > RANGE) throw Error('owner_far');
    await goto(new GoalNear(request.x, request.y, request.z, 1), check);
    return location();
  }
  if (request.op === 'eat') {
    if (bot.food >= 20) return { full: true };
    const foods = bot.registry.foodsByName;
    const food = bot.inventory.items().filter(i => foods[i.name] && !/poison|pufferfish|rotten|spider_eye|raw|^chicken$/.test(i.name))
      .sort((a, b) => foods[b.name].foodPoints - foods[a.name].foodPoints)[0];
    if (!food) throw Error('no_food');
    const hunger = bot.food;
    await bot.equip(food, 'hand');
    check();
    await bot.consume();
    check();
    for (let i = 0; i < 10 && bot.food <= hunger; i++) { await delay(100); check(); }
    if (bot.food <= hunger) throw Error('eat_unconfirmed');
    return { item: food.name, food: bot.food };
  }
  if (request.op === 'build') return build(request, check);
  if (request.op === 'equip') {
    const product = registryItem(bot.registry.itemsByName, request.item);
    const stack = bot.inventory.items().find(item => item.type === product.id);
    if (!stack) throw Error('not_enough');
    await bot.equip(stack, 'hand');
    check();
    await confirmInventory(check, 'unconfirmed');
    if (bot.heldItem?.type !== product.id) throw Error('unconfirmed');
    return { item: product.name };
  }
  if (request.op === 'mine') return mine(request, check);
  if (request.op === 'teleport') return teleport(check);
  if (request.op === 'obtain') return obtain(request, check);
  if (request.op === 'craft') {
    try { return await craft(request, check); }
    catch (error) {
      if (error.message !== 'no_recipe') throw error;
      const before = itemCount(bot, request.item);
      const result = await obtain({ ...request, count: before + request.count }, check);
      return { item: result.item, count: result.count - before };
    }
  }
  if (request.op === 'deliver') {
    jobs.active.step = 'prepare';
    await obtain(request, check);
    check();
    jobs.active.step = 'approach';
    await act({ op: 'come' }, check);
    check();
    jobs.active.step = 'transfer';
    return act({ ...request, op: 'give' }, check);
  }
  const player = owner();
  if (request.op === 'follow') {
    bot.pathfinder.setGoal(new GoalFollow(player, 2), true);
    await new Promise(resolve => { follow = resolve; });
    check();
  }
  if (request.op === 'come') {
    if (player.position.distanceTo(bot.entity.position) <= 2) return {};
    const { x, y, z } = player.position;
    await goto(new GoalNear(x, y, z, 2), check);
    owner(4);
    return {};
  }
  if (request.op === 'give' || request.op === 'give_stock') {
    const item = registryItem(bot.registry.itemsByName, request.item);
    const missing = request.count - itemCount(bot, request.item);
    if (missing > 0) {
      if (request.op === 'give_stock') throw Error('not_enough');
      jobs.active.step = 'craft_for_give';
      await obtain(request, check);
    }
    jobs.active.step = 'approach';
    await act({ op: 'come' }, check);
    const before = itemCount(bot, request.item);
    if (before < request.count) throw Error('not_enough');
    jobs.active.step = 'transfer';
    await bot.lookAt(owner(3).position.offset(0, 0.6, 0));
    check();
    owner(3);
    await bot.toss(item.id, null, request.count);
    check();
    await confirmInventory(check, 'give_unconfirmed');
    const count = before - itemCount(bot, request.item);
    if (count !== request.count) throw Error('give_unconfirmed');
    return { count, item: request.item };
  }
  throw Error('bad_command');
}

function connect(settings) {
  options = settings;
  const auth = settings.auth;
  bot = mineflayer.createBot({ host: settings.host, port: settings.port, auth, username: settings.account,
    version: false, hideErrors: true, logErrors: false, viewDistance: 'tiny', closeTimeout: 12000,
    connect: client => {
      if (client.username?.toLowerCase() === settings.owner.toLowerCase()) {
        emit({ event: 'error', error: 'same_account' });
        emit({ event: 'end' });
        input.close();
        process.stdin.destroy();
        return;
      }
      const socket = net.createConnection({ host: settings.host, port: settings.port, timeout: 10_000 });
      socket.once('timeout', () => socket.destroy(Error('Connection timed out')));
      socket.once('connect', () => socket.setTimeout(0));
      client.setSocket(socket);
    },
    ...(auth === 'microsoft' ? { profilesFolder: path.resolve(fileURLToPath(new URL('../data/minecraft-auth', import.meta.url))),
      onMsaCode: code => { if (/^[A-Z0-9-]{4,14}$/i.test(code.user_code || '')) emit({ event: 'auth', code: code.user_code }); }
    } : {}) });
  bot.loadPlugin(pathfinder);
  bot.once('spawn', () => {
    const movements = new Movements(bot);
    Object.assign(movements, { canDig: false, canOpenDoors: false, allow1by1towers: false,
      allowParkour: false, allowSprinting: false, scaffoldingBlocks: [], maxDropDown: 2, infiniteLiquidDropdownDistance: false });
    movements.exclusionAreasStep.push(block => /^(lava|water)$/.test(block.name) ? 100 : 0);
    bot.pathfinder.thinkTimeout = 1500;
    bot.pathfinder.tickTimeout = 20;
    bot.pathfinder.searchRadius = 20;
    bot.pathfinder.setMovements(movements);
    ready = true;
    emit({ event: 'ready', ...state() });
  });
  bot.on('death', () => jobs.stopAll('respawn'));
  bot.on('respawn', () => { if (jobs.active?.op !== 'teleport') jobs.stopAll('respawn'); });
  bot.on('physicsTick', () => {
    if (!ready || !jobs.active || jobs.active.reason || jobs.active.op === 'teleport') return;
    try { owner(); } catch { jobs.stopAll('owner_left'); }
  });
  bot._client.on('playerChat', packet => {
    if (!ready || !options.chat) return;
    const player = ownerInfo();
    if (player?.username === bot.username) return;
    const localTrust = settings.trust_local_chat === true && ['127.0.0.1', '::1'].includes(settings.host);
    const text = ownerChat(packet, options.owner, player, auth === 'microsoft' && !localTrust);
    if (!text && !warnedChat && ownerChat(packet, options.owner, player, false)) {
      warnedChat = true;
      emit({ event: 'chat_signature' });
    }
    if (text && (/^(?:стоп|стой|остановись|stop|stay)[.!?]?$/iu.test(text) || Date.now() - lastChat >= 500)) {
      lastChat = Date.now();
      emit({ event: 'chat', text });
    }
  });
  bot.on('kicked', () => emit({ event: 'error', error: 'kicked' }));
  bot.on('error', error => {
    const text = String(error.message || '');
    const code = /unsupported|not supported|version/i.test(text) ? 'version' :
      /profile|entitlement|auth|token|xbox/i.test(text) ? 'auth_failed' : 'connection_failed';
    emit({ event: 'error', error: code });
  });
  bot.on('end', () => { ready = false; jobs.stopAll(); emit({ event: 'end' }); process.exitCode = 0; input.close(); process.stdin.destroy(); });
}

function receive(value) {
  const { id } = value;
  if (!Number.isSafeInteger(id)) return;
  try {
    let result = {};
    if (value.op === 'connect' && !bot) connect(value.settings);
    else {
      const request = command(value);
      if (request.op === 'quit') { jobs.stopAll(); bot?.quit(); return; }
      if (!ready) throw Error('not_ready');
      if (request.op === 'status' || request.op === 'nearby') result = state();
      else if (request.op === 'position') result = location();
      else if (request.op === 'stop') result = { stopped: jobs.stopAll() };
      else if (request.op === 'cancel_job') result = { stopped: jobs.cancel(request.jobId) };
      else if (request.op === 'say') {
        if (Date.now() - lastSay < 700) throw Error('busy');
        lastSay = Date.now();
        bot.chat(request.text);
      } else {
        if (request.op !== 'follow') jobs.replaceFollow();
        const timeout = request.op === 'guard' ? 0 :
          ['follow', 'give', 'craft', 'obtain', 'deliver', 'build', 'sequence', 'fish'].includes(request.op) ? 600_000 : 45_000;
        result = { queued: jobs.enqueue(id, request, check => act(request, check), timeout) };
      }
    }
    emit({ id, ok: true, result });
  } catch (error) { emit({ id, ok: false, error: errors.has(error.message) ? error.message : 'connection_failed' }); }
}

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on('line', line => {
  if (line.length > 8192) return;
  try { receive(JSON.parse(line)); } catch {}
});
input.on('close', () => { jobs.stopAll(); bot?.end(); });
emit({ event: 'hello', protocol: 1 });
