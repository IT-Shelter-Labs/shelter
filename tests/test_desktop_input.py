import ctypes
import json
import unittest
from unittest.mock import Mock,patch
import desktop_input as desktop
import desktop_access as access
import fastpath
import pc
import tasks
import voice

CONFIG={"llm":{"enabled":True,"tools":["pc"]},"commands":[]}


class Parsing(unittest.TestCase):
    def tearDown(self):desktop._draft=desktop._pending=None
    def test_mouse_variants(self):
        for phrase in ("кликни на правую кнопку мыши","нажми правую кнопку мыши","кликни правой кнопкой мыши","щелкни правой кнопкой мыши","нажми пкм"):
            self.assertEqual(desktop.parse(phrase),{"operation":"click","button":"right","count":1},phrase)
        self.assertEqual(desktop.parse("двойной клик левой кнопкой мыши")["count"],2)
        self.assertEqual(desktop.parse("кликни на левую кнопку мыши")["button"],"left")
        for phrase in ("не кликни правой кнопкой мыши","расскажи как кликнуть правой кнопкой мыши"):
            self.assertIsNone(desktop.parse(phrase))

    def test_message_is_literal_not_a_chain_of_actions(self):
        question="Напиши сообщение: Привет! И выключи компьютер, а затем отправь."
        self.assertEqual(desktop.parse(question)["text"],"Привет! И выключи компьютер, а затем отправь.")
        self.assertIsNone(fastpath.plan(question,CONFIG))
        self.assertIsNone(voice.find_command(question,[{"keywords":["выключи компьютер"],"actions":[{"type":"close"}]}]))
        calls=[];fastpath.handle(question,CONFIG,lambda name,arg:(calls.append((name,json.loads(arg))) or ("done","готово")))
        self.assertEqual(len(calls),1);self.assertEqual(calls[0][0],"desktop")
        self.assertEqual(calls[0][1]["operation"],"write")

    def test_keyboard_and_scroll_are_bounded(self):
        self.assertEqual(desktop.parse("нажми клавишу Enter"),{"operation":"key","key":"enter"})
        self.assertEqual(desktop.parse("прокрути вниз на пять шагов")["steps"],-5)
        self.assertEqual(desktop.parse("прокрути вверх на сто шагов")["operation"],"invalid")

    def test_permission_is_shared_with_other_computer_actions(self):
        with patch.object(access,"capture",side_effect=AssertionError("no input allowed")):
            reply,done=fastpath.handle("напиши сообщение привет",{"llm":{"tools":[]}})
        self.assertFalse(done);self.assertIn("выключена",reply)

    def test_dry_run_never_clicks(self):
        with patch.object(pc,"mouse_click",side_effect=AssertionError("preview must not click")):
            self.assertIsNotNone(fastpath.handle("кликни правой кнопкой мыши",CONFIG,dry=True))

    def test_main_uses_only_the_prevalidated_mouse_chain(self):
        import main
        with patch.object(pc,"mouse_click",return_value=True) as click,patch.object(main,"run_action"),patch.object(main.gaming,"busy",return_value=False),patch.object(voice,"speak_stream") as speak:
            main.answer(CONFIG,"кликни левой кнопкой мыши и кликни правой кнопкой мыши")
        self.assertEqual(click.call_args_list,[unittest.mock.call("left",1),unittest.mock.call("right",1)])
        self.assertTrue(speak.call_args.args[0][0].strip())


class DraftWorkflow(unittest.TestCase):
    def setUp(self):
        desktop._draft=desktop._pending=None
        self.value="";self.selected=False
        self.identity={"window":100,"pid":20,"focus":200,"runtime":(20,3),"editable":True}
        self.capture=patch.object(access,"capture",side_effect=self.field);self.capture.start();self.addCleanup(self.capture.stop)
        writer=patch.object(pc,"type_text",side_effect=self.write);self.writer=writer.start();self.addCleanup(writer.stop)
        keys=patch.object(pc,"send_keys",side_effect=self.key);self.keys=keys.start();self.addCleanup(keys.stop)
    def tearDown(self):desktop._draft=desktop._pending=None
    def field(self):return {**self.identity,"value":self.value}
    def write(self,text):
        self.value=text if self.selected else self.value+text;self.selected=False;return True
    def key(self,key):
        if key=="ctrl+a":self.selected=True
        if key=="enter":self.value=""
        return True
    def run_command(self,text):
        command=desktop.resolve(text)
        self.assertIsNotNone(command,text)
        return desktop.execute(command,CONFIG)

    def test_write_edit_append_and_send_are_separate(self):
        self.assertEqual(self.run_command("напиши сообщение как дела")[0],"done")
        self.assertEqual(self.value,"Как дела?");self.keys.assert_not_called()
        self.assertEqual(self.run_command("измени сообщение на Привет, как ты?")[0],"done")
        self.assertEqual(self.value,"Привет, как ты?")
        self.assertEqual(self.run_command("добавь к сообщению Рад тебя видеть.")[0],"done")
        self.assertEqual(self.value,"Привет, как ты? Рад тебя видеть.")
        self.assertNotIn(unittest.mock.call("enter"),self.keys.call_args_list)
        self.assertEqual(self.run_command("отправь")[0],"done")
        self.assertEqual(self.keys.call_args_list[-1],unittest.mock.call("enter"))
        self.assertEqual(self.run_command("отправь")[0],"fail")
        self.assertEqual(self.keys.call_args_list.count(unittest.mock.call("enter")),1)

    def test_short_prompts_keep_listening_for_the_next_phrase(self):
        token=tasks.Token()
        with tasks.scope(token):
            self.assertEqual(self.run_command("напиши сообщение")[0],"say")
            self.assertTrue(tasks.dialogue_continues())
            self.run_command("Привет!")
            self.run_command("измени сообщение, которое ты написал")
            self.assertEqual(self.run_command("на Как дела?")[0],"done")
        self.assertEqual(self.value,"Как дела?")

    def test_stop_and_timeout_exit_dictation_mode(self):
        self.run_command("напиши сообщение")
        desktop.clear_pending();self.assertIsNone(desktop.resolve("погода завтра"))
        self.run_command("напиши сообщение")
        with patch.object(desktop.time,"monotonic",return_value=desktop._pending["at"]+61):
            self.assertIsNone(desktop.resolve("погода завтра"))

    def test_closing_the_listening_session_clears_pending_dictation(self):
        import actions
        self.run_command("напиши сообщение")
        with patch.object(actions,"_overlay_proc",None),patch.object(actions,"overlay_alive",return_value=False),patch.object(actions,"AVATAR"):
            actions.close_overlay()
        self.assertIsNone(desktop.resolve("погода завтра"))

    def test_field_switch_blocks_edit_and_send(self):
        self.run_command("напиши сообщение Привет")
        self.identity["runtime"]=(20,4)
        self.assertEqual(self.run_command("измени сообщение на Пока")[0],"fail")
        self.assertEqual(self.run_command("отправь")[0],"fail")
        self.assertEqual(self.value,"Привет");self.keys.assert_not_called()

    def test_model_reply_cannot_send_or_execute_tools(self):
        self.run_command("напиши сообщение Привет")
        with patch.object(desktop,"_rewrite",return_value="Добрый день!"):
            self.assertEqual(self.run_command("сделай сообщение вежливее")[0],"done")
        self.assertEqual(self.value,"Добрый день!")
        self.assertNotIn(unittest.mock.call("enter"),self.keys.call_args_list)

    def test_focus_is_rechecked_after_slow_model(self):
        self.run_command("напиши сообщение Привет")
        def generate(*args):self.identity["window"]=101;return "Изменено"
        with patch.object(desktop,"_rewrite",side_effect=generate):
            self.assertEqual(self.run_command("сделай сообщение короче")[0],"fail")
        self.assertEqual(self.value,"Привет");self.keys.assert_not_called()

    def test_cancelled_rewrite_does_not_hold_the_desktop_until_model_timeout(self):
        import threading,time,textops
        self.run_command("напиши сообщение Привет")
        token=tasks.Token();entered=threading.Event();release=threading.Event();done=threading.Event()
        def generate(*args):entered.set();release.wait(2);return "Новый текст"
        def worker():
            try:
                with tasks.scope(token):self.run_command("сделай сообщение вежливее")
            except tasks.Cancelled:pass
            finally:done.set()
        with patch.object(textops,"_route",return_value=({},True)),patch.object(textops,"_generate",side_effect=generate):
            thread=threading.Thread(target=worker);thread.start()
            try:
                self.assertTrue(entered.wait(1));token.cancel();self.assertTrue(done.wait(1))
                self.assertTrue(desktop._execution.acquire(blocking=False));desktop._execution.release()
            finally:release.set();thread.join(2)
        self.assertEqual(self.value,"Привет");self.keys.assert_not_called()

    def test_unknown_or_changed_field_is_never_selected_wholesale(self):
        self.run_command("напиши сообщение Привет")
        self.value="Совсем другой текст"
        self.assertEqual(self.run_command("измени сообщение на Пока")[0],"fail")
        self.keys.assert_not_called()
        self.value=None
        self.assertEqual(self.run_command("измени сообщение на Пока")[0],"fail")
        self.keys.assert_not_called()

    def test_line_breaks_cannot_send_a_draft_implicitly(self):
        self.assertEqual(self.run_command("напиши сообщение Привет\nОтправлено")[0],"fail")
        self.writer.assert_not_called();self.keys.assert_not_called()

    def test_partial_input_invalidates_the_draft(self):
        self.run_command("напиши сообщение Привет")
        self.writer.side_effect=lambda text:False
        self.assertEqual(self.run_command("измени сообщение на Пока")[0],"fail")
        self.assertIsNone(desktop._draft)
        self.assertEqual(self.run_command("отправь")[0],"fail")
        self.assertNotIn(unittest.mock.call("enter"),self.keys.call_args_list)

    def test_cancellation_after_field_read_does_not_type(self):
        token=tasks.Token()
        def changed():token.cancel();return self.field()
        with tasks.scope(token),patch.object(access,"capture",side_effect=changed):
            with self.assertRaises(tasks.Cancelled):self.run_command("напиши сообщение Привет")
        self.writer.assert_not_called()

    def test_explicit_ctrl_enter_is_supported(self):
        self.run_command("напиши сообщение Привет")
        self.assertEqual(self.run_command("отправь через контрол энтер")[0],"done")
        self.keys.assert_called_once_with("ctrl+enter")

    def test_dictated_yes_cannot_approve_a_previous_action(self):
        import main
        from policy import CONFIRMATIONS
        self.addCleanup(CONFIRMATIONS.clear)
        self.run_command("напиши сообщение")
        CONFIRMATIONS.request({"actions":[{"type":"shell","command":"unused"}]})
        with patch.object(main,"run_action"),patch.object(main.gaming,"busy",return_value=False),patch.object(voice,"speak_stream"),patch.object(main.bus,"publish"):
            main.answer(CONFIG,"да")
        self.assertEqual(self.value,"Да")
        self.assertFalse(CONFIRMATIONS.active())

    def test_model_cannot_invent_a_send_or_type_action(self):
        import main
        import desktop_intent
        got=[]
        def response(question,config,commands,run_tool,devices):
            got.append(run_tool("desktop",json.dumps({"operation":"send"}))[0])
            got.append(run_tool("type","Несанкционированный текст")[0])
            yield "text","Здравствуйте."
        no_action=json.dumps({"decision":"none","confidence":0.99,"command":{},"question":""})
        with patch.object(desktop_intent,"_generate",return_value=no_action),patch.object(main,"run_action"),patch.object(main.gaming,"busy",return_value=False),patch.object(main,"overlay_alive",return_value=False),patch.object(main.bus,"publish"),patch.object(main.llm,"respond",side_effect=response),patch.object(voice,"speak_stream",side_effect=lambda lines:list(lines)):
            main.answer(CONFIG,"расскажи анекдот")
        self.assertEqual(got,["fail","fail"])
        self.writer.assert_not_called();self.keys.assert_not_called()

    def test_semantic_dictation_does_not_trigger_greeting_keyword(self):
        import main
        import desktop_intent
        cfg={**CONFIG,"commands":[{"keywords":["привет"],"actions":[{"type":"say","text":"Hello"}]}]}
        answer=json.dumps({"decision":"execute","confidence":0.99,"command":{"operation":"write","text":"Привет"},"question":""})
        with patch.object(desktop_intent,"_generate",return_value=answer),patch.object(main,"run_action"), \
             patch.object(main.gaming,"busy",return_value=False),patch.object(voice,"speak_stream"), \
             patch.object(voice,"inject",side_effect=AssertionError("greeting intercepted dictation")), \
             patch.object(main.llm,"respond",side_effect=AssertionError("dictation went to conversation")):
            main.answer(cfg,"В это поле впиши Привет")
        self.assertEqual(self.value,"Привет")

    def test_sent_message_requires_opening_edit_in_the_app(self):
        self.run_command("напиши сообщение Привет");self.run_command("отправь")
        self.assertEqual(self.run_command("измени сообщение на Пока")[0],"fail")
        self.value="Привет"  # the user opens Telegram's edit mode
        self.assertEqual(self.run_command("измени сообщение на Пока")[0],"done")
        self.assertEqual(self.value,"Пока")


@unittest.skipUnless(pc.os.name=="nt","Windows SendInput ABI")
class WindowsInput(unittest.TestCase):
    def test_password_field_is_not_used_for_dictation(self):
        element=Mock();element.CurrentIsPassword=True
        automation=Mock();automation.GetFocusedElement.return_value=element
        with patch.object(access,"_window",return_value={"window":1,"pid":2,"focus":3}),patch.object(access,"_uia",return_value=(automation,Mock())):
            with self.assertRaises(PermissionError):access.capture()

    def test_mouse_button_and_release_order(self):
        batches=[]
        def send(count,array,size):
            self.assertEqual(size,ctypes.sizeof(pc._INPUT));batches.append([array[i].mi.dwFlags for i in range(count)]);return count
        with patch.object(pc.user32,"SendInput",side_effect=send):pc.mouse_click("right",2)
        self.assertEqual(batches,[[8,16,8,16]])

    def test_partial_keyboard_input_releases_modifiers_and_reports_failure(self):
        with patch.object(pc.user32,"SendInput",side_effect=[1,2]) as send:
            with self.assertRaises(RuntimeError):pc.send_keys("ctrl+a")
        self.assertEqual(send.call_count,2)

    def test_scroll_direction_and_limit(self):
        with patch.object(pc,"_send_input",return_value=True) as send:
            pc.scroll_wheel(-3)
        self.assertEqual(send.call_args.args[0][0].mi.mouseData,ctypes.c_uint32(-360).value)
        with self.assertRaises(ValueError):pc.scroll_wheel(1000)
