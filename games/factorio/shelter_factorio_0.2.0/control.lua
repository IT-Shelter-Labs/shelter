local filename = "shelter-factorio.json"

local function write_snapshot(player)
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
  local snapshot = {
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
  helpers.write_file(filename, helpers.table_to_json(snapshot), false, player.index)
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

local function start_command(command)
  local player = command.player_index and game.get_player(command.player_index)
  if not player then return end
  local recipe, count = (command.parameter or ""):match("^([%w_-]+)%s+(%d+)$")
  count = tonumber(count)
  local available = recipe and player.force.recipes[recipe]
  if not available or not available.enabled or #available.products ~= 1 or not count or count < 1 or count > 100 then
    player.print("Shelter: use /shelter-craft <enabled recipe with one product> <1–100>.")
    return
  end
  storage.jobs = storage.jobs or {}
  if running(storage.jobs[player.index]) then
    player.print("Shelter: finish or stop the active job with /shelter-stop first.")
    return
  end
  storage.jobs[player.index] = {recipe = recipe, total = count, done = 0, state = "waiting",
    deadline = game.tick + 36000}
  player.print("Shelter: job accepted. Use /shelter-stop to stop scheduling crafts.")
end
commands.add_command("shelter-craft", "Queue a hand-crafting job: /shelter-craft recipe count", start_command)

local function stop_command(command)
  local player = command.player_index and game.get_player(command.player_index)
  if not player then return end
  local job = storage.jobs and storage.jobs[player.index]
  if running(job) then
    finish(player, job, "stopped")
    if storage.exporting and storage.exporting[player.index] then write_snapshot(player) end
  end
end
commands.add_command("shelter-stop", "Stop scheduling crafts for your Shelter job.", stop_command)

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
