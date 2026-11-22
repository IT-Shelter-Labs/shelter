import { recipes } from './recipes.mjs';

const smelting = {
  stone: 'cobblestone', smooth_stone: 'stone', glass: 'sand', brick: 'clay_ball',
  iron_ingot: 'raw_iron', copper_ingot: 'raw_copper', gold_ingot: 'raw_gold',
  baked_potato: 'potato', dried_kelp: 'kelp', terracotta: 'clay',
  cooked_beef: 'beef', cooked_chicken: 'chicken', cooked_porkchop: 'porkchop',
  cooked_mutton: 'mutton', cooked_rabbit: 'rabbit', cooked_cod: 'cod', cooked_salmon: 'salmon',
};

// Build the entire dependency chain on a simulated inventory before changing the world.
export function acquisitionPlan(bot, goal, count, nearby) {
  const reg = bot.registry;
  const stock = new Map();
  for (const it of bot.inventory.items()) stock.set(it.name, (stock.get(it.name) || 0) + it.count);
  const drops = new Map();
  for (const [name, n] of nearby) {
    const block = reg.blocksByName[name];
    if (!block?.diggable || block.drops?.length !== 1 || name === 'furnace' || name === 'crafting_table') continue;
    const item = reg.items[block.drops[0]]?.name;
    if (!item) continue;
    if (!drops.has(item)) drops.set(item, []);
    drops.get(item).push({ block, n });
  }
  const initial = { stock, blocks: new Map(nearby), stations: new Set(['crafting_table', 'furnace'].filter(n => nearby.has(n))), steps: [] };
  const copy = s => ({ stock: new Map(s.stock), blocks: new Map(s.blocks), stations: new Set(s.stations), steps: [...s.steps] });
  const held = (s, item) => s.stock.get(item) || 0;
  const add = (s, item, n) => s.stock.set(item, held(s, item) + n);
  let budget = 4800;
  function station(s, name, path) {
    if (s.stations.has(name)) return s;
    s = ensure(s, name, 1, path);
    if (!s) return null;
    add(s, name, -1);
    s.steps.push({ op: 'place_station', item: name });
    s.stations.add(name);
    return s;
  }
  function ensure(s, item, wanted, path) {
    const missing = wanted - held(s, item);
    if (missing <= 0) return s;
    if (--budget < 0 || path.has(item) || path.size >= 10 || s.steps.length >= 100) return null;
    const next = new Set([...path, item]);
    for (const { block } of drops.get(item) || []) {
      if (s.blocks.get(block.name) < missing) continue;
      let trial = copy(s);
      if (block.harvestTools) {
        const tools = Object.keys(block.harvestTools).map(id => reg.items[id]?.name).filter(Boolean);
        if (!tools.some(tool => held(trial, tool))) {
          const rank = tool => ['wooden','stone','iron','diamond','netherite','golden'].indexOf(tool.split('_')[0]);
          trial = tools.sort((a, b) => rank(a) - rank(b)).reduce((ok, tool) => ok || ensure(copy(s), tool, 1, next), null);
          if (!trial) continue;
        }
      }
      trial.blocks.set(block.name, trial.blocks.get(block.name) - missing);
      trial.steps.push({ op: 'mine', item: block.name, drop: item, count: missing });
      add(trial, item, missing);
      return trial;
    }
    if (smelting[item]) {
      let trial = station(copy(s), 'furnace', next);
      if (trial) trial = ensure(trial, smelting[item], missing, next);
      if (trial) {
        add(trial, smelting[item], -missing);
        const fuels = [['coal', 8], ['charcoal', 8], ...Object.keys(reg.itemsByName).filter(n => n.endsWith('_planks')).map(n => [n, 1.5])];
        fuels.sort(([a, ca], [b, cb]) =>
          Number(held(trial, b) >= Math.ceil(missing / cb)) - Number(held(trial, a) >= Math.ceil(missing / ca)));
        for (const [fuel, capacity] of fuels) {
          const units = Math.ceil(missing / capacity);
          const fueled = ensure(copy(trial), fuel, units, next);
          if (!fueled) continue;
          add(fueled, fuel, -units);
          fueled.steps.push({ op: 'smelt', item, input: smelting[item], count: missing, fuel, units });
          add(fueled, item, missing);
          return fueled;
        }
      }
    }
    const id = reg.itemsByName[item]?.id;
    if (id == null) return null;
    const estimate = name => held(s, name) ? 0 : drops.has(name) ? 1 :
      name.endsWith('_planks') && [name.replace('_planks', '_log'), name.replace('_planks', '_wood')].some(n => held(s,n) || drops.has(n)) ? 2 : 8;
    const candidates = recipes(bot, id, true).map(recipe => {
      const ingredients = recipe.delta.filter(d => d.count < 0).map(d => [reg.items[d.id].name, -d.count]);
      return { recipe, ingredients, cost: ingredients.reduce((n, [name]) => n + estimate(name), 0) };
    }).sort((a, b) => a.cost - b.cost);
    for (const { recipe, ingredients } of candidates) {
      let trial = copy(s);
      if (recipe.requiresTable) trial = station(trial, 'crafting_table', next);
      const batches = Math.ceil(missing / recipe.result.count);
      for (const [name, units] of ingredients) {
        if (!trial) break;
        trial = ensure(trial, name, units * batches, next);
        if (trial) add(trial, name, -units * batches);
      }
      if (!trial) continue;
      trial.steps.push({ op: 'craft', item, recipe, batches });
      add(trial, item, recipe.result.count * batches);
      return trial;
    }
    return null;
  }
  return ensure(initial, goal, count, new Set())?.steps ?? null;
}
