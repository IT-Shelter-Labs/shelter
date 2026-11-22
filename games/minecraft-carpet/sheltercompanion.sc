// Jarvis adapter for Carpet 1.4.193 (Minecraft Java 1.21.11).
// Only this app's data directory is polled. File contents never become commands.
__config() -> {'scope' -> 'global', 'command_permission' -> 'ops',
               'commands' -> {'pair' -> 'pair', 'disconnect' -> 'disconnect'}};

global_owner = null;
global_owner_name = null;
global_token = null;
global_actor_name = 'ShelterJarvis';
global_actor_id = null;
global_spawn_ticks = 0;
global_move_ticks = 0;
global_state = 'idle';
global_pair_ticks = 0;
global_seen = null;

_owner() -> (
    if(global_owner == null, return(null));
    candidate = player(global_owner_name);
    if(candidate != null && query(candidate, 'uuid') == global_owner, candidate, null)
);
_actor() -> (
    if(global_actor_id == null, return(null));
    candidate = player(global_actor_name);
    if(candidate != null && query(candidate, 'uuid') == global_actor_id && query(candidate, 'player_type') == 'fake', candidate, null)
);

_stop(next) -> (
    if(_actor() != null, run('player ' + global_actor_name + ' stop'));
    global_state = next
);

_remove() -> (
    _stop('idle');
    if(_actor() != null, run('player ' + global_actor_name + ' kill'));
    global_actor_id = null
);

pair() -> (
    owner = player();
    if(owner == null || query(owner, 'player_type') == 'fake' || query(owner, 'player_type') == 'shadow', return(0));
    if(global_owner != null && global_owner != query(owner, 'uuid') && _owner() != null, return(0));
    global_owner = query(owner, 'uuid');
    global_owner_name = query(owner, 'name');
    global_token = null;
    global_pair_ticks = 1200;
    delete_file('request', 'json');
    print(owner, 'Shelter: select this world scripts folder in Jarvis within one minute.');
    1
);

disconnect() -> (
    owner = player();
    if(owner == null || query(owner, 'uuid') != global_owner, return(0));
    global_token = null;
    global_owner = null;
    global_owner_name = null;
    global_pair_ticks = 0;
    _remove();
    1
);

_apply(owner, op, speech) -> (
    if(op == 'remove', _remove());
    if(op == 'spawn' && _actor() == null && global_spawn_ticks == 0,
        if(player(global_actor_name) != null,
            global_state = 'name_taken',
            run('execute at ' + query(owner, 'name') + ' run player ' + global_actor_name + ' spawn in survival');
            global_spawn_ticks = 100;
            global_state = 'spawning'
        )
    );
    if(_actor() == null, return(null));
    if(op == 'come' || op == 'follow',
        global_state = op; global_move_ticks = if(op == 'come', 60, 600)
    );
    if(op == 'stop', _stop('stopped'));
    if(op == 'say' && length(speech) > 0, print(owner, 'Shelter: ' + speech));
);

_update(owner) -> (
    if(global_spawn_ticks > 0,
        global_spawn_ticks = global_spawn_ticks - 1;
        candidate = player(global_actor_name);
        if(candidate != null && query(candidate, 'player_type') == 'fake',
            global_actor_id = query(candidate, 'uuid');
            global_spawn_ticks = 0;
            if(global_token == null || owner == null, _remove(), global_state = 'ready'),
            if(global_spawn_ticks == 0, global_state = 'spawn_failed')
        )
    );
    actor = _actor();
    if(actor == null || owner == null,
        if(global_actor_id != null, _remove());
        return(null)
    );
    if(global_state != 'follow' && global_state != 'come', return(null));
    if(query(actor, 'dimension') != query(owner, 'dimension'), _stop('different_world'); return(null));
    [ax, ay, az] = query(actor, 'pos');
    [x, y, z] = query(owner, 'pos');
    distance = sqrt((ax - x)^2 + (ay - y)^2 + (az - z)^2);
    global_move_ticks = global_move_ticks - 1;
    if(distance > 24, _stop('no_path'); return(null));
    if(global_move_ticks <= 0, _stop('timeout'); return(null));
    if(distance <= 3,
        if(global_state == 'come', _stop('arrived'), run('player ' + global_actor_name + ' stop')),
        run(str('player %s look at %f %f %f', global_actor_name, x, y + 1.6, z));
        run('player ' + global_actor_name + ' move forward')
    )
);

__on_tick() -> (
    if(tick_time() % 10 != 0, return(null));
    owner = _owner();
    _update(owner);
    if(global_pair_ticks > 0, global_pair_ticks = global_pair_ticks - 10);
    request = read_file('request', 'json');
    if(request == null || request:'id' == global_seen, return(null));
    global_seen = request:'id';
    op = request:'op'; token = request:'token';
    if(op == 'pair' && owner != null && global_pair_ticks > 0 && length(token) == 64,
        global_token = token;
        global_pair_ticks = 0
    );
    state = if(global_token == null || token != global_token, 'disconnected',
        if(owner == null, 'owner_offline', _apply(owner, op, request:'text'); global_state));
    data = {'id' -> global_seen, 'state' -> state};
    if(state != 'disconnected' && state != 'owner_offline' && _actor() != null,
        [x, y, z] = query(_actor(), 'pos');
        put(data, 'x', x); put(data, 'y', y); put(data, 'z', z);
        put(data, 'gameMode', query(_actor(), 'gamemode'))
    );
    write_file('response', 'json', data);
    if(op == 'remove' && token == global_token, global_token = null)
);

__on_close() -> _remove();
