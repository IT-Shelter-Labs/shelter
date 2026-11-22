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
    progress = research and player.force.research_progress or 0
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

script.on_nth_tick(120, function()
  if not storage.exporting then return end
  for _, player in pairs(game.connected_players) do
    if storage.exporting[player.index] then write_snapshot(player) end
  end
end)
