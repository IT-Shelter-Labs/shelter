import json
import unittest
from unittest.mock import patch

from shelter_core import discord_link, factorio_companion, factorio_link, game_assist, hoi4_link, obs


class IntegrationActions(unittest.TestCase):
    def test_factorio_validates_before_connecting(self):
        cfg = {"factorio": {"player": "owner", "rcon_password": "test"}}
        with patch.object(factorio_link.socket, "create_connection") as connect:
            with self.assertRaisesRegex(ValueError, "ID рецепта"):
                factorio_link.request(cfg, "craft", recipe="iron\n/c", count=3)
            connect.assert_not_called()

    def test_factorio_voice_job_uses_game_link_and_guest_cannot_start(self):
        with patch.object(factorio_link, "request", return_value={"ok": True}) as request:
            self.assertIn("iron-gear-wheel", game_assist.answer("Factorio, изготовь 3 iron-gear-wheel", {}))
            request.assert_called_once_with({}, "craft", recipe="iron-gear-wheel", count=3)
            request.reset_mock()
            game_assist.answer("Factorio, изготовь 3 iron-gear-wheel", {}, guest=True)
            request.assert_not_called()

    def test_companion_gather_only_targets_a_known_character(self):
        game = {"connected": True, "snapshot": {"companions": [{"id": 8, "name": "Pippa"}]}}
        with patch.object(factorio_companion, "_state", return_value=(game, {})), \
             patch.object(factorio_companion, "_call", return_value={"success": True}) as call:
            with self.assertRaises(ValueError):
                factorio_companion.action({}, "gather", companion_id=1, text="iron-ore", count=5)
            call.assert_not_called()
            self.assertTrue(factorio_companion.action({}, "gather", companion_id=8, text="iron-ore", count=5)["ok"])
            call.assert_called_once_with({}, "/api/tools/call", {"name": "gather",
                                                                "args": {"companionId": 8, "resource": "iron-ore", "count": 5}})

    def test_hoi_advance_waits_for_player_choice_and_has_a_bound(self):
        with patch.object(hoi4_link.integrations, "execute", return_value=("data", '{"status":"started"}')) as call:
            self.assertIn("started", hoi4_link.action({}, "advance", days=3)["text"])
            data = json.loads(call.call_args.args[1])
            self.assertEqual(data["tool"], "hoi4_advance")
            self.assertEqual(data["arguments"], {"days": 3, "popups": "stop", "background": True, "max_seconds": 90})
            self.assertTrue(call.call_args.kwargs["confirmed"])
            with self.assertRaises(ValueError):
                hoi4_link.action({}, "advance", days=150)
            self.assertEqual(call.call_count, 1)

    def test_obs_switches_scene_and_checks_readback(self):
        self.assertEqual(obs.voice_action("Включи сцену Игра в OBS"), "scene|Игра")
        self.assertIsNone(obs.voice_action("какие настройки записи в OBS"))
        with patch.object(obs, "Client") as factory:
            client = factory.return_value
            client.request.side_effect = [(True, 100, {"scenes": [{"sceneName": "Игра"}]}), (True, 100, {}),
                                          (True, 100, {"currentProgramSceneName": "Игра"})]
            self.assertEqual(obs.act("scene|игра", {}), (False, "Выбрана сцена «Игра»."))
            client.close.assert_called_once()

    def test_obs_status_handles_a_disabled_replay_buffer(self):
        with patch.object(obs, "Client") as factory:
            factory.return_value.request.side_effect = [(True, 100, {"outputActive": False, "outputPaused": False}),
                                                        (False, 604, {}),
                                                        (True, 100, {"currentProgramSceneName": "Игра"})]
            self.assertIn("Буфер повтора отключён в настройках", obs.act("status", {})[1])

    def test_discord_checks_current_state_and_does_not_toggle_if_already_on(self):
        cfg = {"discord": {"guild_id": "1" * 17, "user_id": "2" * 17}}
        state = dict(self_mute=False, self_deaf=False, mute=False, deaf=False)
        with patch.object(discord_link, "voice_state", return_value=state), patch("shelter_core.pc.discord") as hotkey:
            self.assertIn("включён", discord_link.set_audio(cfg, "mute", False))
            hotkey.assert_not_called()

    def test_discord_message_is_restricted_to_server(self):
        cfg = {"channel_id": "1" * 17, "guild_id": "2" * 17}
        with patch.object(discord_link, "_request", return_value={"guild_id": "3" * 17}) as request:
            with self.assertRaisesRegex(ValueError, "не относится"):
                discord_link.notify(cfg, "hello")
            request.assert_called_once()
