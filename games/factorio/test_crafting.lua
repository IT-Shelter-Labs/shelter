-- Append to the mod's control.lua in a disposable 2.1.24+ test scenario.
-- Use the engine's test player and real queues. Do not ship with the mod ZIP.
script.on_nth_tick(1, function()
  local player = game.get_player(1)
  if game.tick == 10 then
    assert(player and player.character, "Expected the engine's test player")
    storage.baseline = player.get_item_count("iron-gear-wheel")
    assert(player.insert{name = "iron-plate", count = 40} == 40)
    local plan = bridge_action(player, "plan", "iron-gear-wheel", 3)
    assert(plan.ok and plan.craftable >= 3 and plan.ingredients[1].required == 6, "Plan must reflect live recipe and inventory")
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
    local x, y = math.floor(player.position.x + 5), math.floor(player.position.y)
    local world = player.surface
    local position = world.find_non_colliding_position("transport-belt", {x, y}, 10, 1)
    assert(position, "Test needs an empty tile for the belt")
    assert(player.cursor_stack.set_stack{name = "blueprint", count = 1})
    player.cursor_stack.set_blueprint_entities{{entity_number = 1, name = "transport-belt", position = {0, 0}}}
    local built = build_blueprint(player, math.floor(position.x), math.floor(position.y))
    assert(built.ok and built.placed == 1, "The game must return one construction ghost")
    local machine_pos = world.find_non_colliding_position("assembling-machine-1", {x - 3, y + 3}, 6, 1)
    assert(machine_pos, "Test needs an empty area for the assembler")
    local machine = world.create_entity{name = "assembling-machine-1", position = machine_pos, force = player.force}
    assert(machine and player.can_reach_entity(machine))
    local assigned = machine_recipe(player, "iron-gear-wheel", machine.position.x, machine.position.y)
    assert(assigned.ok and machine.get_recipe().name == "iron-gear-wheel", "Read the actual assembler recipe")
    player.force.enable_research()
    local technology = player.force.technologies.automation
    local function prepare(tech)
      for _, prerequisite in pairs(tech.prerequisites) do
        if not prerequisite.researched then prepare(prerequisite); prerequisite.researched = true end
      end
    end
    prepare(technology)
    local research = bridge_action({admin = true, force = player.force}, "research", technology.name)
    assert(research.ok, "Read actual research queue: " .. helpers.table_to_json(research))
    assert(player.force.current_research and player.force.current_research.name == technology.name)
    script.finish_test(true)
  end
end)
