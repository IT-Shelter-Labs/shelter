import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once, EventEmitter } from 'node:events';
import { fileURLToPath } from 'node:url';
import readline from 'node:readline';
import { test } from 'node:test';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const protocol = require('minecraft-protocol');
const data = require('minecraft-data');
const { comp, string, list } = require('prismarine-nbt');
const { Vec3 } = require('vec3');

for (const version of ['1.20.4', '1.21.5', '1.21.11']) test(`Java ${version}: companion over actual game packets`, { timeout: 25_000 }, async context => {
  const server = protocol.createServer({ version, host: '127.0.0.1', port: 0, 'online-mode': false, hideErrors: true });
  const mc = data(version);
  let connection;
  let giveLog;
  let givePlanks;
  let teleportAllowed = false, craftAllowed = true, pickedLogs = 0, planks = 0, teleports = 0, dugLogs = 0;
  let modeAllowed = false;
  let logName = 'oak_log', boardName = 'oak_planks';
  const attacks = [];
  const gameChat = [];
  const packets = [];
  server.on('playerJoin', client => {
    connection = client;
    client.on('error', () => {});
    client.on('position', packet => packets.push(packet));
    client.on('chat_message', packet => gameChat.push(packet.message));
    client.on('use_entity', packet => { if (packet.mouse === 1) attacks.push(packet.target); });
    client.write('login', { ...mc.loginPacket, entityId: client.id, gameMode: 0, previousGameMode: 0,
      maxPlayers: 3, viewDistance: 2, simulationDistance: 2, enforceSecureChat: false });
    const move = (x, y, z, id) => client.write('position', { x, y, z, yaw: 0, pitch: 0, flags: 0, teleportId: id,
      dx: 0, dy: 0, dz: 0, deltaX: 0, deltaY: 0, deltaZ: 0 });
    move(2.5, 64, 3.5, 1);
    if (version === '1.21.5') {
      const Item = require('prismarine-item')(version);
      const stack = (name, count) => Item.toNotch(count ? new Item(mc.itemsByName[name].id, count) : null);
      let stateId = 0, cursor = '', inGrid = false, dropping = 0;
      const slot = (index, item) => client.write('set_slot', { windowId: 0, stateId: ++stateId, slot: index, item });
      giveLog = (name = 'oak_log') => { logName = name; giveBoardsName(); slot(9, stack(logName, ++pickedLogs)); };
      const giveBoardsName = () => { boardName = logName.startsWith('spruce') ? 'spruce_planks' : 'oak_planks'; };
      givePlanks = () => {
        planks = 4;
        cursor = '';
        slot(10, stack(boardName, planks));
      };
      const feedback = (translation, args = []) => client.write('system_chat',
        { content: comp({ translate: string(translation), ...(args.length ? { with: list(args.map(string)) } : {}) }), isActionBar: false });
      client.on('chat_command', packet => {
        if (packet.command === 'gamemode creative @s') {
          if (modeAllowed) client.write('game_state_change', { reason: 'change_game_mode', gameMode: 1 });
          return;
        }
        assert.equal(packet.command, 'tp @s WorldOwner');
        teleports++;
        if (!teleportAllowed) feedback('command.unknown.command');
        else {
          move(7.5, 64, 3.5, 2);
          feedback('commands.teleport.success.entity.single', ['JarvisTest', 'WorldOwner']);
        }
      });
      client.on('window_click', click => {
        if (click.stateId === -1) {
          const items = Array.from({ length: 46 }, () => Item.toNotch(null));
          items[9] = stack(logName, pickedLogs);
          items[10] = stack(boardName, planks);
          client.write('window_items', { windowId: 0, stateId: ++stateId, items, carriedItem: Item.toNotch(null) });
        } else if (click.slot === 9 && pickedLogs && !cursor) {
          pickedLogs--;
          cursor = 'log';
        } else if (click.slot >= 1 && click.slot <= 4 && cursor === 'log') {
          inGrid = true;
          cursor = '';
          slot(0, stack(boardName, craftAllowed ? 4 : 0));
        } else if (click.slot === 0) {
          if (inGrid && craftAllowed) {
            cursor = 'planks';
            inGrid = false;
          }
          slot(0, Item.toNotch(null));
        } else if (click.slot === 10 && !cursor && planks) {
          dropping = planks;
          planks = 0;
          cursor = 'drop';
        } else if (click.slot === -999 && cursor === 'drop') {
          dropping -= click.mouseButton === 0 ? dropping : 1;
          if (!dropping) cursor = '';
        } else if (click.slot >= 9 && cursor === 'planks') {
          planks += 4;
          cursor = '';
        }
      });
      client.on('block_dig', packet => {
        if (packet.status !== 2 || packet.location.x !== 6 || packet.location.y !== 64 || packet.location.z !== 5) return;
        dugLogs++;
        client.write('multi_block_change', { chunkCoordinates: { x: 0, z: 0, y: 4 }, records: [(6 << 8) | (5 << 4)] });
        giveLog();
      });
    }
    if (version !== '1.21.11') {
      const Chunk = require('prismarine-chunk')(version);
      const chunk = new Chunk();
      for (let x = 0; x < 16; x++) for (let z = 0; z < 16; z++) chunk.setBlockStateId(new Vec3(x, 63, z), mc.blocksByName.stone.defaultState);
      chunk.setBlockStateId(new Vec3(6, 64, 5), mc.blocksByName.oak_log.defaultState);
      client.write('map_chunk', { x: 0, z: 0, heightmaps: comp({}), chunkData: chunk.dump(), blockEntities: [], ...chunk.dumpLight() });
      if (version === '1.20.4') client.on('block_dig', packet => {
        if (packet.status === 2 && packet.location.x === 6 && packet.location.y === 64 && packet.location.z === 5) {
          client.write('block_change', { location: packet.location, type: mc.blocksByName.air.defaultState });
        }
      });
    }
    client.write('update_health', { health: 20, food: 20, foodSaturation: 5 });
  });
  context.after(() => {
    Object.values(server.clients).forEach(client => client.socket.destroy());
    server.socketServer.close();
  });
  await once(server, 'listening');
  const child = spawn(process.execPath, [fileURLToPath(new URL('../bridge.mjs', import.meta.url))], { windowsHide: true });
  context.after(() => { child.kill(); });
  const messages = new EventEmitter();
  const observed = [];
  let stderr = '';
  child.stderr.on('data', text => { stderr += text.toString(); });
  const lines = readline.createInterface({ input: child.stdout });
  lines.on('line', line => { const item = JSON.parse(line); observed.push(item); messages.emit('item', item); });
  const wait = check => new Promise((resolve, reject) => {
    const previous = observed.find(check);
    if (previous) { resolve(previous); return; }
    const listener = item => { if (check(item)) { clearTimeout(timer); messages.off('item', listener); resolve(item); } };
    const timer = setTimeout(() => { messages.off('item', listener); reject(Error(JSON.stringify(observed) + '\n' + stderr)); }, 7000);
    messages.on('item', listener);
  });
  const send = request => child.stdin.write(JSON.stringify(request) + '\n');
  assert.equal((await wait(item => item.event === 'hello')).protocol, 1);
  send({ id: 1, op: 'connect', settings: { host: '127.0.0.1', port: server.socketServer.address().port,
    account: 'JarvisTest', owner: 'WorldOwner', auth: 'offline', chat: true } });
  const ready = await wait(item => item.event === 'ready');
  assert.equal(ready.name, 'JarvisTest');
  assert.equal(ready.version, version);
  assert.equal(ready.food ?? 20, 20);
  send({ id: 2, op: 'status' });
  const state = (await wait(item => item.id === 2)).result;
  assert.deepEqual(state.items, []);
  assert.equal(state.health, 20);
  assert.equal(state.gameMode, 'survival');
  send({ id: 20, op: 'position' });
  assert.deepEqual((await wait(item => item.id === 20)).result.position, [2, 64, 3]);
  send({ id: 3, op: 'come' });
  const result = await wait(item => item.event === 'job' && item.id === 3);
  assert.equal(result.state, 'failed');
  assert.equal(result.result, 'owner_absent');
  const owner = 'eee2e079-ab66-4ec5-9a11-3f575aa18d57';
  connection.write('player_info', { action: { add_player: true }, data: [{ uuid: owner, player: { name: 'WorldOwner', properties: [] } }] });
  connection.write('spawn_entity', { entityId: 34, objectUUID: owner, type: mc.entitiesByName.player.id,
    x: 7.5, y: 64, z: 3.5, pitch: 0, yaw: 0, headPitch: 0, objectData: 0, velocity: { x: 0, y: 0, z: 0 } });
  connection.write('player_chat', { globalIndex: 1, senderUuid: owner, index: 0, plainMessage: '!jarvis инвентарь',
    timestamp: BigInt(Date.now()), salt: 0n, previousMessages: [], filterType: 0,
    type: mc.supportFeature('chatTypeIsHolder') ? { chatType: 1 } : 0, networkName: comp({ text: string('WorldOwner') }) });
  assert.equal((await wait(item => item.event === 'chat')).text, 'инвентарь');
  send({ id: 4, op: 'follow' });
  assert.equal((await wait(item => item.id === 4)).ok, true);
  if (version === '1.20.4') {
    for (let tick = 0; tick < 30 && !packets.some(packet => packet.x > 3); tick++) await new Promise(resolve => setTimeout(resolve, 50));
    assert.ok(packets.some(packet => packet.x > 3), 'The companion actually moved towards the owner');
  }
  send({ id: 5, op: 'stop' });
  assert.equal((await wait(item => item.id === 5)).result.stopped, true);
  assert.equal((await wait(item => item.event === 'job' && item.id === 4)).state, 'stopped');
  if (version === '1.20.4') {
    send({ id: 6, op: 'mine', item: 'oak_log', count: 1 });
    const mined = await wait(item => item.event === 'job' && item.id === 6);
    assert.equal(mined.state, 'done');
    assert.deepEqual(mined.result, { broken: 1, collected: 0, item: 'oak_log', warning: '' });
  }
  if (version === '1.21.5') {
    assert.ok((await wait(item => item.id === 20)).result.dimension);
    send({ id: 21, op: 'follow' });
    assert.equal((await wait(item => item.id === 21)).ok, true);
    send({ id: 22, op: 'obtain', item: 'oak_planks', count: 4 });
    assert.equal((await wait(item => item.event === 'job' && item.id === 21)).state, 'replaced');
    const boards = await wait(item => item.event === 'job' && item.id === 22);
    assert.equal(boards.state, 'done', JSON.stringify(boards));
    assert.deepEqual(boards.result, { count: 4, item: 'oak_planks' });
    assert.equal(dugLogs, 1);
    assert.equal(planks, 4);
    send({ id: 23, op: 'obtain', item: 'oak_planks', count: 2 });
    assert.deepEqual((await wait(item => item.event === 'job' && item.id === 23)).result, boards.result);
    assert.equal(dugLogs, 1);
    send({ id: 24, op: 'obtain', item: 'oak_planks', count: 8 });
    assert.equal((await wait(item => item.event === 'job' && item.id === 24)).result, 'need_logs');
    craftAllowed = false;
    giveLog();
    // Use the bridge's view, not an arbitrary pause, before firing the next job.
    for (let index = 0; index < 10; index++) {
      send({ id: 30 + index, op: 'status' });
      const status = (await wait(item => item.id === 30 + index)).result;
      if (status.items.some(([name]) => name === 'oak_log')) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    send({ id: 27, op: 'obtain', item: 'oak_planks', count: 8 });
    assert.equal((await wait(item => item.event === 'job' && item.id === 27)).result, 'craft_unconfirmed');
    send({ id: 25, op: 'teleport', target: 'someone_else' });
    assert.equal((await wait(item => item.event === 'job' && item.id === 25)).result, 'teleport_denied');
    teleportAllowed = true;
    send({ id: 26, op: 'teleport' });
    const teleported = await wait(item => item.event === 'job' && item.id === 26);
    assert.equal(teleported.state, 'done', JSON.stringify(teleported));
    assert.deepEqual(teleported.result.position, [7, 64, 3]);
    assert.equal(teleports, 2);
    givePlanks();
    for (let index = 0; index < 10; index++) {
      send({ id: 60 + index, op: 'status' });
      if ((await wait(item => item.id === 60 + index)).result.items.some(([name, count]) => name === 'oak_planks' && count === 4)) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    send({ id: 50, op: 'deliver', item: 'oak_planks', count: 4 });
    const delivered = await wait(item => item.event === 'job' && item.id === 50);
    assert.equal(delivered.state, 'done', JSON.stringify(delivered));
    assert.deepEqual(delivered.result, { count: 4, item: 'oak_planks' });
    assert.equal(planks, 0);
    craftAllowed = true;
    giveLog();
    send({ id: 51, op: 'give', item: 'oak_planks', count: 4 });
    const craftedAndGiven = await wait(item => item.event === 'job' && item.id === 51);
    assert.deepEqual(craftedAndGiven.result, { count: 4, item: 'oak_planks' });
    assert.equal(planks, 0);
    assert.equal(pickedLogs, 0);
    assert.equal(dugLogs, 1, 'Giving planks should use the existing inventory');
    giveLog('spruce_wood');
    for (let index = 0; index < 10; index++) {
      send({ id: 70 + index, op: 'status' });
      if ((await wait(item => item.id === 70 + index)).result.items.some(([name]) => name === 'spruce_wood')) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    send({ id: 80, op: 'give', item: 'planks', count: 4 });
    const anyBoards = await wait(item => item.event === 'job' && item.id === 80);
    assert.deepEqual(anyBoards.result, { count: 4, item: 'spruce_planks' });
    assert.equal(pickedLogs, 0);
    send({ id: 54, op: 'set_mode', mode: 'creative' });
    assert.equal((await wait(item => item.event === 'job' && item.id === 54)).result, 'mode_denied');
    modeAllowed = true;
    send({ id: 55, op: 'set_mode', mode: 'creative' });
    assert.deepEqual((await wait(item => item.event === 'job' && item.id === 55)).result, { mode: 'creative' });
    send({ id: 52, op: 'status' });
    assert.equal((await wait(item => item.id === 52)).result.gameMode, 'creative');
    const weatherReply = 'Погода в городе: +12.';
    send({ id: 53, op: 'say', text: weatherReply });
    assert.equal((await wait(item => item.id === 53)).ok, true);
    for (let tick = 0; tick < 20 && !gameChat.length; tick++) await new Promise(resolve => setTimeout(resolve, 25));
    assert.deepEqual(gameChat, [weatherReply]);
    const spawnMob = (id, name, x) => connection.write('spawn_entity', { entityId: id,
      objectUUID: 'ddd2e079-ab66-4ec5-9a11-3f575aa18d' + id, type: mc.entitiesByName[name].id,
      x, y: 64, z: 3.5, pitch: 0, yaw: 0, headPitch: 0, objectData: 0, velocity: { x: 0, y: 0, z: 0 } });
    spawnMob(41, 'cow', 7);
    spawnMob(42, 'zombie', 8);
    send({ id: 56, op: 'guard' });
    assert.equal((await wait(item => item.id === 56)).ok, true);
    for (let tick = 0; tick < 40 && !attacks.length; tick++) await new Promise(resolve => setTimeout(resolve, 50));
    assert.deepEqual(attacks, [42]);
    send({ id: 57, op: 'stop' });
    assert.equal((await wait(item => item.event === 'job' && item.id === 56)).state, 'stopped');
  }
  send({ id: 7, op: 'quit' });
  await wait(item => item.event === 'end');
});
