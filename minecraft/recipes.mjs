// Plan against this client's versioned recipes and a copy of its inventory.
// Trying an alternative recipe must not consume ingredients for a failed branch.
export function recipes(bot, id, table) {
  const base = bot.recipesAll(id, null, table);
  // minecraft-data expands wood tags to one representative log in some versions.
  const extra = [];
  for (const recipe of base) {
    if (!bot.registry.items[id]?.name.endsWith('_planks') || recipe.ingredients?.length !== 1) continue;
    const input = recipe.ingredients[0];
    const name = bot.registry.items[input.id]?.name;
    if (!name?.endsWith('_log') && !name?.endsWith('_stem')) continue;
    const bark = name.replace(/_log$/, '_wood').replace(/_stem$/, '_hyphae');
    for (const variant of [bark, 'stripped_' + name, 'stripped_' + bark]) {
      const type = bot.registry.itemsByName[variant];
      if (!type) continue;
      const substitute = entry => entry.id === input.id ? { ...entry, id: type.id } : entry;
      extra.push({ ...recipe, ingredients: recipe.ingredients.map(substitute), delta: recipe.delta.map(substitute) });
    }
  }
  return [...base, ...extra];
}

export function planCraft(bot, product, amount, table) {
  const inventory = new Map();
  for (const stack of bot.inventory.items()) inventory.set(stack.type, (inventory.get(stack.type) || 0) + stack.count);
  let budget = 900;
  function produce(id, quantity, stock, path) {
    if (--budget < 0 || path.has(id) || path.size >= 5) return null;
    const candidates = recipes(bot, id, table);
    const missing = (recipe, batches) => recipe.delta.reduce((sum, d) =>
      sum + (d.count < 0 ? Math.max(0, -d.count * batches - (stock.get(d.id) || 0)) : 0), 0);
    const choices = candidates.map(recipe => {
      const batches = Math.ceil(quantity / recipe.result.count);
      return { recipe, batches, cost: missing(recipe, batches) };
    }).sort((a, b) => a.cost - b.cost);
    for (const { recipe, batches } of choices) {
      const available = new Map(stock);
      const steps = [];
      let possible = true;
      for (const ingredient of recipe.delta.filter(d => d.count < 0)) {
        const required = -ingredient.count * batches;
        const shortage = required - (available.get(ingredient.id) || 0);
        if (shortage > 0) {
          const intermediate = produce(ingredient.id, shortage, available, new Set([...path, id]));
          if (!intermediate) { possible = false; break; }
          steps.push(...intermediate);
        }
        available.set(ingredient.id, available.get(ingredient.id) - required);
      }
      if (!possible) continue;
      for (const d of recipe.delta.filter(d => d.count > 0)) available.set(d.id, (available.get(d.id) || 0) + d.count * batches);
      for (const [key, count] of available) stock.set(key, count);
      return [...steps, { recipe, batches }];
    }
    return null;
  }
  return produce(product.id, amount, inventory, new Set());
}

export const itemGroups = new Set(['planks', 'pickaxe', 'axe', 'sword', 'shovel', 'hoe', 'log']);
export function matchingItems(bot, group) {
  return Object.values(bot.registry.itemsByName).filter(item => item.name.endsWith('_' + group));
}
