import copy
import unittest
from unittest.mock import patch


class LiveExtensions(unittest.TestCase):
    def test_lite_profile_updates_avatar_without_overwriting_persona_fps(self):
        from avatar import AvatarController
        config = {"ui": {"mode": "avatar", "lite": True}, "persona": {"id": "demo", "avatar": {"fps": 60}}}
        controller = AvatarController()
        controller._visible = True
        with patch.object(controller, "tick"), patch("bus.publish") as publish:
            controller.refresh_options(config)
            self.assertEqual(publish.call_args.kwargs["options"]["fps"], 24)
            self.assertEqual(config["persona"]["avatar"]["fps"], 60)
            config["ui"]["lite"] = False
            controller.refresh_options(config)
            self.assertEqual(publish.call_args.kwargs["options"]["fps"], 60)

    def test_live_settings_refresh_avatar_options(self):
        import settings_live
        before = {"ui": {"mode": "avatar", "lite": False}}
        fresh = copy.deepcopy(before); fresh["ui"]["lite"] = True
        with patch("main.load_config", return_value=fresh), patch("actions.AVATAR") as controller:
            self.assertIn("ui", settings_live.reload(before)["applied"])
            controller.refresh_options.assert_called_once_with(before)

    def test_action_extension_uses_new_settings_and_retains_legacy_compatibility(self):
        import actions
        import plugins_manager
        for settings in ({"demo": {"api_key": "test"}}, {"settings": {"demo": {"api_key": "test"}}}):
            with patch.object(actions, "_allow_plugins", True), patch.object(actions, "_runtime_config", {"plugins": settings}), patch.object(plugins_manager, "call", return_value={}) as call:
                actions._run_plugin({"name":"demo"})
                self.assertEqual(call.call_args.args[3], {"api_key":"test"})
