local filename = "shelter-factorio.json"

local function player_state(player)
  local inventory = {}
  local main = player.get_main_inventory()
  if main then
    for _, stack in pairs(main.get_contents()) do
      inventory[#inventory + 1] = {
        name = stack.name,
        quality = stack.quality,
        count = stack.count
      }
    end
  end
  local research = player.force.current_research
  return {
    format = "shelter-factorio-1",
    player = player.name,
    surface = player.surface.name,
    x = player.position.x,
    y = player.position.y,
    inventory = inventory,
    research = research and research.name or "",
    progress = research and player.force.research_progress or 0,
    job = storage.jobs and storage.jobs[player.index]
  }
end

local function write_snapshot(player)
  helpers.write_file(filename, helpers.table_to_json(player_state(player)), false, player.index)
end

commands.add_command("shelter-export", "Toggle the local Shelter snapshot for your player.", function(command)
  local player = command.player_index and game.get_player(command.player_index)
  if not player then return end
  storage.exporting = storage.exporting or {}
  local enabled = not storage.exporting[player.index]
  storage.exporting[player.index] = enabled or nil
  if enabled then
    write_snapshot(player)
    player.print("Shelter: exporting inventory and research to script-output/" .. filename)
  else
    helpers.write_file(filename, "{}", false, player.index)
    player.print("Shelter: local export stopped.")
  end
end)

local function running(job)
  return job and (job.state == "waiting" or job.state == "crafting")
end

local function finish(player, job, state)
  job.state = state
  player.print(("Shelter: %s (%d / %d %s)."):format(state, job.done, job.total, job.recipe))
end

local function check_recipe(player, recipe, count)
  local available = recipe and player.force.recipes[recipe]
  if not available or not available.enabled or #available.products ~= 1 or not count or count < 1 or count > 100 then
    return nil
  end
  return available
end

local function start_job(player, recipe, count)
  if not check_recipe(player, recipe, count) then return "recipe" end
  storage.jobs = storage.jobs or {}
  if running(storage.jobs[player.index]) then return "busy" end
  storage.jobs[player.index] = {recipe = recipe, total = count, done = 0, state = "waiting",
    deadline = game.tick + 36000}
  player.print("Shelter: job accepted. Use /shelter-stop to stop scheduling crafts.")
end
local function start_command(command)
  local player = command.player_index and game.get_player(command.player_index)
  if not player then return end
  local recipe, count = (command.parameter or ""):match("^([%w_-]+)%s+(%d+)$")
  local error_code = start_job(player, recipe, tonumber(count))
  if error_code == "recipe" then
    player.print("Shelter: use /shelter-craft <enabled recipe with one product> <1–100>.")
  elseif error_code == "busy" then
    player.print("Shelter: finish or stop the active job with /shelter-stop first.")
  end
end
commands.add_command("shelter-craft", "Queue a hand-crafting job: /shelter-craft recipe count", start_command)

local function stop_job(player)
  local job = storage.jobs and storage.jobs[player.index]
  if running(job) then
    finish(player, job, "stopped")
    if storage.exporting and storage.exporting[player.index] then write_snapshot(player) end
  end
end
local function stop_command(command)
  local player = command.player_index and game.get_player(command.player_index)
  if player then stop_job(player) end
end
commands.add_command("shelter-stop", "Stop scheduling crafts for your Shelter job.", stop_command)

commands.add_command("shelter-remote", "Allow or revoke Shelter RCON control of your player.", function(command)
  local player = command.player_index and game.get_player(command.player_index)
  if not player then return end
  storage.remote_players = storage.remote_players or {}
  local enabled = not storage.remote_players[player.index]
  storage.remote_players[player.index] = enabled or nil
  if not enabled then stop_job(player) end
  player.print("Shelter: remote control " .. (enabled and "enabled." or "disabled."))
end)

local function bridge_reply(result)
  rcon.print("SHELTER/1 " .. helpers.table_to_json(result))
end

local function build_blueprint(player, x, y)
  local blueprint = player.cursor_stack
  if not blueprint or not blueprint.valid_for_read or not blueprint.is_blueprint or not blueprint.is_blueprint_setup() then
    return {error = "blueprint"}
  end
  if not player.character or not x or not y or math.abs(x - player.position.x) > 24 or math.abs(y - player.position.y) > 24 then
    return {error = "position"}
  end
  local entities = blueprint.get_blueprint_entities() or {}
  if #entities < 1 or #entities > 120 or #(blueprint.get_blueprint_tiles() or {}) > 0 then
    return {error = "blueprint_size"}
  end
  for _, entity in ipairs(entities) do
    if math.abs(entity.position.x) > 24 or math.abs(entity.position.y) > 24 then
      return {error = "blueprint_size"}
    end
  end
  local ghosts = blueprint.build_blueprint{surface = player.surface, force = player.force,
    position = {x, y}, by_player = player, raise_built = true}
  local placed = 0
  for _, ghost in pairs(ghosts) do
    if ghost.valid and ghost.type == "entity-ghost" then placed = placed + 1 end
  end
  return {ok = true, placed = placed, total = #entities}
end

-- Adapted from building_recipe in Factorio AI Companion (MIT).
-- Work on the player's own reachable assembler and verify the selected recipe.
local function machine_recipe(player, id, x, y)
  local recipe = player.force.recipes[id]
  if not recipe or not recipe.enabled then return {error = "recipe"} end
  local position = {x = x, y = y}
  if not x or not y or math.abs(x - player.position.x) > 24 or math.abs(y - player.position.y) > 24 then
    return {error = "position"}
  end
  local machines = player.surface.find_entities_filtered{
    position = position, radius = 0.6, type = "assembling-machine", force = player.force
  }
  if #machines ~= 1 or not player.can_reach_entity(machines[1]) then return {error = "machine"} end
  local machine = machines[1]
  local current = machine.get_recipe()
  if current and current.name ~= id then return {error = "assigned"} end
  if not current then
    if not pcall(machine.set_recipe, id) then return {error = "machine_recipe"} end
    current = machine.get_recipe()
  end
  if not current or current.name ~= id then return {error = "machine_recipe"} end
  return {ok = true, recipe = current.name, machine = machine.name}
end

local function bridge_action(player, op, id, count)
  if op == "plan" then
    local recipe = check_recipe(player, id, count)
    if not recipe then return {error = "recipe"} end
    local ingredients = {}
    for _, item in pairs(recipe.ingredients) do
      ingredients[#ingredients + 1] = {
        name = item.name, required = item.amount * count, type = item.type,
        carried = item.type == "item" and player.get_item_count(item.name) or 0
      }
    end
    return {ok = true, ingredients = ingredients, craftable = player.get_craftable_count(id)}
  elseif op == "research" then
    if not player.admin then return {error = "admin"} end
    local tech = player.force.technologies[id]
    if not tech or tech.researched or not tech.enabled then return {error = "research"} end
    local function queued()
      local active = player.force.current_research
      if active and active.name == id then return true end
      for _, current in pairs(player.force.research_queue or {}) do
        if current.name == id then return true end
      end
      return false
    end
    if not queued() and (not player.force.add_research(id) or not queued()) then
      return {error = "research"}
    end
    return {ok = true, research = id}
  elseif op == "craft" then
    local error_code = start_job(player, id, count)
    if error_code then return {error = error_code} end
  elseif op == "stop" then
    stop_job(player)
  elseif op ~= "status" then
    return {error = "operation"}
  end
  local state = player_state(player)
  state.ok = true
  -- Keep the RCON reply bounded. Full export is still available in the local file.
  table.sort(state.inventory, function(a, b) return a.count > b.count end)
  for index = #state.inventory, 13, -1 do state.inventory[index] = nil end
  return state
end

commands.add_command("shelter-bridge", "RCON transport for Shelter.", function(command)
  if command.player_index then return end
  local name, op, arguments = (command.parameter or ""):match("^([%w_.-]+) ([a-z]+)%s*(.*)$")
  local player = name and game.get_player(name)
  if not player or not player.connected then return bridge_reply{error = "player"} end
  if not storage.remote_players or not storage.remote_players[player.index] then
    return bridge_reply{error = "disabled"}
  end
  if op == "build" then
    local x, y = arguments:match("^(%-?%d+) (%-?%d+)$")
    return bridge_reply(build_blueprint(player, tonumber(x), tonumber(y)))
  end
  if op == "machine" then
    local id, x, y = arguments:match("^([%w_-]+) (%-?%d+) (%-?%d+)$")
    if not id then return bridge_reply{error = "recipe"} end
    return bridge_reply(machine_recipe(player, id, tonumber(x), tonumber(y)))
  end
  local id, count = arguments:match("^([%w_-]*)%s*(%d*)$")
  if not id then return bridge_reply{error = "operation"} end
  bridge_reply(bridge_action(player, op, id, tonumber(count)))
end)

script.on_event(defines.events.on_player_crafted_item, function(event)
  local job = storage.jobs and storage.jobs[event.player_index]
  if not job or job.state ~= "crafting" or event.recipe.name ~= job.recipe then return end
  local player = game.get_player(event.player_index)
  job.done = job.done + 1
  if job.done >= job.total then finish(player, job, "complete")
  else job.state = "waiting" end
end)

script.on_event(defines.events.on_player_cancelled_crafting, function(event)
  local job = storage.jobs and storage.jobs[event.player_index]
  if job and job.state == "crafting" then
    finish(game.get_player(event.player_index), job, "stopped")
  end
end)

local function advance(player)
  local job = storage.jobs and storage.jobs[player.index]
  if not running(job) then return end
  if game.tick >= job.deadline then finish(player, job, "timeout"); return end
  if job.state ~= "waiting" or not player.character or player.crafting_queue_size > 0 then return end
  if player.begin_crafting{recipe = job.recipe, count = 1, silent = true} ~= 1 then
    finish(player, job, "blocked")
    return
  end
  job.state = "crafting"
end

script.on_nth_tick(120, function()
  for _, player in pairs(game.connected_players) do
    advance(player)
    if storage.exporting and storage.exporting[player.index] then write_snapshot(player) end
  end
end)

script.on_event(defines.events.on_player_left_game, function(event)
  local job = storage.jobs and storage.jobs[event.player_index]
  if running(job) then finish(game.get_player(event.player_index), job, "stopped") end
end)
