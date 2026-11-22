"""Regressions for context integrity, memory scope and provider boundaries."""
import io
import http.client
import queue
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from shelter_core import agent_runtime
from shelter_core import assistant_api
from shelter_core import assistant_store as store
from shelter_core import context_engine as engine
from shelter_core import llm
from shelter_core import llm_connections as connections
from shelter_core import semantic_memory
from shelter_core import tasks
from shelter_core import companion


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=patch.object(store,'PATH',Path(self.tmp.name)/'state.sqlite3')
        self.db.start()
        self.session=store.session_for()
        self.cfg={'model':'test','context':2048,'max_tokens':200,'memory':{'recent_turns':8}}

    def tearDown(self):
        self.db.stop();self.tmp.cleanup()

    def test_pending_question_not_duplicated_and_repair_history_preserved(self):
        store.add_message(self.session,'user','понял')
        store.add_message(self.session,'assistant','Я учёл ваши пожелания.')
        store.add_message(self.session,'user','Какие пожелания?')
        messages,history,_,diag=engine.build('Система','Какие пожелания?',self.cfg,self.session)
        self.assertEqual([m['content'] for m in history],['понял','Я учёл ваши пожелания.'])
        self.assertEqual(sum('Какие пожелания?' in m['content'] for m in messages),1)
        self.assertEqual(diag['recent_messages'],2)
        self.assertEqual(store.snapshot()['context_diagnostic']['model'],'test')

    def test_long_nearest_exchange_is_shortened_not_dropped(self):
        original='не кофе, а чай. '*800
        store.add_message(self.session,'user',original)
        store.add_message(self.session,'assistant','Вы предпочитаете чай.')
        messages,history,_,diag=engine.build('Система','Повтори предпочтение',self.cfg,self.session)
        self.assertEqual(len(history),2)
        self.assertIn('сокращён',history[0]['content'])
        self.assertEqual(store.dialogue_messages(self.session)[0]['content'],original)
        self.assertLessEqual(sum(map(engine.cost,messages)),engine.input_limit(self.cfg))
        self.assertEqual(diag['shortened_exchanges'],1)

    def test_current_request_cannot_be_silently_truncated(self):
        with self.assertRaises(engine.ContextTooLarge):
            engine.build('Система','Сохранить отрицания. '*2000,self.cfg,self.session)

    def test_output_reservation_matches_requested_limit(self):
        self.assertEqual(engine.input_limit({'context':8192,'max_tokens':4096}),8192-4096-256-engine.tokens('[]'))

    def test_relevant_middle_of_long_exchange_survives_compaction(self):
        original='Обсуждаем рабочие вопросы. '*160+'Регистрационный код проекта — ЛД-47. '+'Прочие детали разговора. '*160
        value=engine.excerpt(original,240,'Какой регистрационный код проекта?')
        self.assertIn('ЛД-47',value)
        self.assertIn('сокращён',value)
        self.assertLessEqual(engine.tokens(value),240)

    def test_scopes_and_no_irrelevant_facts_on_acknowledgement(self):
        other=store.save_project('Другой')
        store.remember('Секретный микроконтроллер Ардуино',other)
        store.remember('Я люблю зелёный чай')
        _,_,materials,_=engine.build('Система','Какой чай я люблю?',self.cfg,self.session)
        self.assertIn('зелёный чай',materials)
        self.assertNotIn('Ардуино',materials)
        _,_,materials,_=engine.build('Система','понял',self.cfg,self.session)
        self.assertNotIn('зелёный чай',materials)

    def test_cloud_materials_are_opt_in_but_dialogue_is_retained(self):
        project=store.save_project('Проект','Приватные инструкции')
        store.activate_project(project);session=store.session_for()
        store.remember('Личный секрет — Ландыш')
        store.add_context(session,'Файл','Приватный файл')
        store.add_message(session,'user','Предыдущая реплика')
        store.add_message(session,'assistant','Ответ')
        messages,history,materials,diag=engine.build('Система','Ландыш',dict(self.cfg,share_context=False),session)
        self.assertFalse(materials)
        self.assertNotIn('Приватные',str(messages))
        self.assertNotIn('Личный секрет',str(messages))
        self.assertEqual(len(history),2)
        self.assertFalse(diag['share_context'])

    def test_vector_is_invalidated_on_edit_and_deleted_with_memory(self):
        ident=store.remember('Люблю чай')
        def insert():
            with store.db() as con:
                con.execute('INSERT INTO memory_vectors VALUES(?,?,?,?,?)',(ident,'test','hash','[1,0]',1))
        def count():
            with store.db() as con:return con.execute('SELECT COUNT(*) FROM memory_vectors').fetchone()[0]
        insert();store.remember('Люблю какао',id=ident);self.assertEqual(count(),0)
        insert();store.delete_memory(ident);self.assertEqual(count(),0)

    def test_guest_has_no_owner_history_or_memory_even_with_named_connection(self):
        store.remember('Секретный адрес')
        store.add_message(self.session,'user','Личный пароль в переписке')
        store.add_message(self.session,'assistant','Понял')
        cfg=connections.resolve({'guest':True,'connections':{'local':{'model':'test','share_context':True}},'routes':{'conversation':'local'}})
        messages,history,materials,_=engine.build('Система','Что знаешь обо мне?',cfg,self.session)
        self.assertFalse(history);self.assertFalse(materials)
        self.assertNotIn('Личный пароль',str(messages))

    def test_native_compaction_keeps_call_result_and_current_task(self):
        messages=[{'role':'system','content':'Система'},
            {'role':'user','content':'Старая история '*1400},{'role':'assistant','content':'Ответ'},
            {'role':'user','content':'Проверь ошибку на снимке'},
            {'role':'assistant','content':'','tool_calls':[{'id':'call_1','function':{'name':'screen','arguments':{}}}]},
            {'role':'tool','content':json.dumps({'status':'data','result':'Ошибка '*1800}), 'tool_call_id':'call_1'},
            {'role':'user','content':'Изображение инструмента','_tool_followup':True}]
        bounded=engine.bound_messages(messages,self.cfg)
        self.assertEqual([m['role'] for m in bounded],['system','user','assistant','tool','user'])
        self.assertEqual(bounded[1]['content'],'Проверь ошибку на снимке')
        self.assertEqual(json.loads(bounded[3]['content'])['status'],'data')
        self.assertEqual(bounded[3]['tool_call_id'],'call_1')

    def test_uncompactable_tool_metadata_fails_without_loop(self):
        messages=[{'role':'user','content':'Вопрос'},{'role':'tool','content':json.dumps({'metadata':'x '*5000,'result':'tiny'})}]
        with self.assertRaises(engine.ContextTooLarge):engine.bound_messages(messages,self.cfg)

    def test_diagnostic_usage_does_not_cross_runs(self):
        store.save_context_diagnostic(self.session,{'run_id':'new'})
        store.record_context_usage(self.session,'old',{'actual_prompt_tokens':100})
        self.assertNotIn('actual_prompt_tokens',store.context_diagnostic(self.session))
        store.record_context_usage(self.session,'new',{'actual_prompt_tokens':42})
        self.assertEqual(store.context_diagnostic(self.session)['actual_prompt_tokens'],42)

    def test_acknowledgement_avoids_tools_even_if_model_emits_a_tag(self):
        run_id,session=store.create_run('понял',self.session)
        called=[]
        config={'llm':dict(self.cfg,tools=['memory','pc'])}
        with tasks.scope(tasks.Token(run_id=run_id,session_id=session)), patch.object(llm,'_stream_ollama',return_value=iter(['[remember: придуманный факт] Понял.'])):
            events=list(llm.respond('понял',config,run_tool=lambda *a:called.append(a)))
        self.assertEqual(called,[])
        self.assertIn(('text','Понял.'),events)

    def test_semantic_failure_preserves_lexical_and_scope(self):
        ident=store.remember('Люблю зелёный чай')
        cfg=dict(self.cfg,memory={'semantic':True})
        with patch.object(semantic_memory,'embed',return_value=[[1.]+[0.]*15]):semantic_memory.reindex(cfg)
        facts=store.memories()
        with patch.object(semantic_memory,'embed',side_effect=OSError('offline')):
            self.assertEqual(semantic_memory.rank(facts,'неповторимый запрос',cfg,facts),facts)
        self.assertEqual(facts[0]['id'],ident)

    def test_mobile_capabilities_require_authentication_and_have_no_keys(self):
        config={'companion':{'enabled':True,'host':'127.0.0.1','port':0}}
        with patch.object(companion,'_token',return_value='fixture-token'):
            server=companion.CompanionServer(config,queue.Queue());server.start()
        try:
            port=server.server.server_port
            client=http.client.HTTPConnection('127.0.0.1',port)
            client.request('GET','/api/capabilities');response=client.getresponse()
            self.assertEqual(response.status,401);response.read();client.close()
            client=http.client.HTTPConnection('127.0.0.1',port)
            client.request('GET','/api/capabilities',headers={'Authorization':'Bearer fixture-token'})
            response=client.getresponse();data=json.loads(response.read());client.close()
            self.assertEqual(response.status,200);self.assertEqual(data['mode'],'paired_pc')
            self.assertEqual(data['limits']['request_characters'],16000)
            self.assertNotIn('fixture-token',str(data));self.assertFalse(data['direct_cloud_credentials'])
        finally:server.stop()


class ConnectionTests(unittest.TestCase):
    def test_normalized_endpoints(self):
        for url in ['https://server.test/v1','https://server.test/v1/chat/completions']:
            self.assertEqual(connections.endpoint({'provider':'openai','url':url}),'https://server.test/v1/chat/completions')
        self.assertEqual(connections.endpoint({'provider':'anthropic'}),'https://api.anthropic.com/v1/messages')
        self.assertEqual(connections.endpoint({'provider':'ollama','url':'http://localhost:11434/api/chat'},'models'),'http://localhost:11434/api/tags')
        with self.assertRaises(ValueError):connections.endpoint({'url':'https://server.test/?api_key=secret'})

    def test_connection_cannot_inherit_another_providers_key(self):
        cfg={'model':'legacy','api_key':'private','api_key_env':'PRIVATE_ENV',
             'connections':{'cloud':{'provider':'openai','url':'https://example.test/v1','model':'chosen'}},
             'routes':{'task':'cloud'}}
        selected=connections.resolve(cfg,'task')
        self.assertEqual(selected['model'],'chosen')
        self.assertNotIn('api_key',selected);self.assertEqual(selected['api_key_env'],'')
        self.assertFalse(selected['share_context'])
        self.assertEqual(connections.resolve(cfg)['model'],'legacy')

    def test_environment_key_is_not_sent_to_an_unrelated_compatible_provider(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':'private-openai-key'}):
            self.assertFalse(connections.headers({'provider':'openai','url':'https://openrouter.ai/api/v1'}))

    def test_probe_does_not_send_a_completion_or_return_provider_error_body(self):
        error=urllib.error.HTTPError('https://example.test',401,'bad',{},io.BytesIO(b'private secret'))
        with patch.object(connections,'open_request',side_effect=error) as opener:
            result=connections.probe({'provider':'openai','url':'https://example.test/v1','api_key':'secret'})
        self.assertFalse(result['ok']);self.assertNotIn('secret',str(result))
        req=opener.call_args[0][0]
        self.assertEqual(req.method if hasattr(req,'method') else req.get_method(),'GET')
        self.assertTrue(req.full_url.endswith('/models'));self.assertIsNone(req.data)

    def test_reasoning_model_parameters_and_native_key(self):
        payload=connections.completion_payload([],{'model':'gpt-6-mini','max_tokens':250},True)
        self.assertEqual(payload['max_completion_tokens'],250);self.assertNotIn('temperature',payload)
        response=io.BytesIO(json.dumps({'choices':[{'message':{'content':'Ответ'}}]}).encode())
        with patch.object(llm,'_open',return_value=response) as request:
            agent_runtime.turn([{'role':'user','content':'Привет'}],[],{'provider':'openai','url':'https://server.test/v1','model':'gpt-6-mini','api_key':'test'},2)
        self.assertEqual(request.call_args.args[2],{'Authorization':'Bearer test'})
        self.assertTrue(request.call_args.args[0].endswith('/chat/completions'))
        self.assertEqual(connections.headers({'provider':'anthropic','workspace_id':'wrkspc_test','api_key':'key'})['anthropic-workspace-id'],'wrkspc_test')

    def test_task_route_and_default_chat_route(self):
        self.assertEqual(engine.route('Спасибо, всё понял'),('conversation',True))
        self.assertEqual(engine.route('Подробно сравни эти документы'),('task',False))
        self.assertEqual(engine.route('Привет, открой Telegram'),('conversation',False))
        self.assertEqual(engine.route('Разбери файл',True),('task',False))

    def test_images_are_translated_for_cloud_protocols(self):
        messages=[{'role':'user','content':'Снимок','images':['iVBORtest'],'_tool_followup':True}]
        openai=connections.completion_payload(messages,{'model':'test'},False)['messages'][0]
        self.assertNotIn('_tool_followup',openai)
        self.assertEqual(openai['content'][1]['image_url']['url'],'data:image/png;base64,iVBORtest')
        claude=connections.multimodal(messages,'anthropic')[0]
        self.assertEqual(claude['content'][1]['source']['media_type'],'image/png')


if __name__=='__main__':unittest.main()
