import { test } from 'node:test';
import assert from 'node:assert/strict';
import { goBack, leaveDraft } from '../src/lib/navigation.ts';

test('canceling Back preserves history; successful Back consumes exactly one entry', async () => {
  const previous = { page: 'persona' };
  const history = [previous];
  assert.equal(await goBack(history, async () => false), false);
  assert.deepEqual(history, [previous]);
  assert.equal(await goBack(history, async () => true), true);
  assert.deepEqual(history, []);
});

test('failed transition preserves history', async () => {
  const history = ['home'];
  await assert.rejects(goBack(history, async () => { throw new Error('save failed'); }));
  assert.deepEqual(history, ['home']);
});

test('dirty persona cannot be lost after cancel or failed save', async () => {
  let discarded = false;
  let saves = 0;
  const options = { dirty: true, busy: false, save: async () => { saves++; return false; },
    discard: () => { discarded = true; } };
  assert.equal(await leaveDraft({ ...options, ask: async () => 'cancel' }), false);
  assert.equal(await leaveDraft({ ...options, ask: async () => 'ok' }), false);
  assert.equal(saves, 1);
  assert.equal(discarded, false);
  assert.equal(await leaveDraft({ ...options, ask: async () => 'extra' }), true);
  assert.equal(discarded, true);
});

test('busy recorder prevents navigation without another prompt', async () => {
  assert.equal(await leaveDraft({ busy: true, dirty: true,
    ask: async () => { throw new Error('must not prompt'); },
    save: async () => true, discard: () => {} }), false);
});
