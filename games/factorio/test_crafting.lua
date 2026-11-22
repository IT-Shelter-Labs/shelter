-- Append to the mod's control.lua in a disposable 2.1.24+ test scenario.
-- Use the engine's test player and real queues. Do not ship with the mod ZIP.
script.on_nth_tick(1, function()
  local player = game.get_player(1)
  if game.tick == 10 then
    assert(player and player.character, "Expected the engine's test player")
    storage.baseline = player.get_item_count("iron-gear-wheel")
    assert(player.insert{name = "iron-plate", count = 40} == 40)
    start_command{player_index = player.index, parameter = "iron-gear-wheel 3"}
    assert(storage.jobs[player.index].state == "waiting")
  elseif game.tick == 490 then
    local job = storage.jobs[player.index]
    assert(job.state == "complete" and job.done == 3, "The engine must finish three recipes")
    assert(player.get_item_count("iron-gear-wheel") == storage.baseline + 3, "Check actual inventory")
    storage.exporting = {[player.index] = true}
    start_command{player_index = player.index, parameter = "iron-gear-wheel 10"}
  elseif game.tick == 610 then
    local job = storage.jobs[player.index]
    assert(job.state == "crafting", "The engine must have queued one recipe")
    stop_command{player_index = player.index}
    storage.after_stop = job.done
  elseif game.tick == 850 then
    local job = storage.jobs[player.index]
    assert(job.state == "stopped" and job.done == storage.after_stop, "Stop must prevent any more scheduled recipes")
    assert(player.get_item_count("iron-gear-wheel") == storage.baseline + 4, "One queued craft may finish")
    script.finish_test(true)
  end
end)
