"""Inventory application-owned UI metadata and errors, excluding prompts/data files."""
import ast
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=['scenarios.py','packs.py','scenario_api.py','router_check.py','triggers.py','connections_api.py',
       'llm_connections.py','plugins_manager.py','plugin_catalog.py','plugin_extensions.py','personas.py',
       'persona_package.py','demo_recorder.py','mic_check.py','textops.py','desktop_input.py','desktop_access.py',
       'assistant_api.py','setup_tool.py','companion_devices.py','tts_profiles.py','control.py','runtime.py',
       'main.py','agent_runtime.py','desktop_linux.py','avatar_motion.py','avatar.py','neural.py']
FIELDS={'text','label','hint','title','about','description','error','message','advice','note','unavailable'}


def extract():
    found=json.loads((ROOT/'reports/ui-i18n-source.json').read_text(encoding='utf8'))
    def put(text,file):
        value=re.sub(r'\s+',' ',text).strip()
        if len(value)>2 and re.search('[а-яёА-ЯЁ]',value):found.setdefault(value,file)
    for name in FILES:
        path=ROOT/'shelter_core'/name
        if not path.is_file():continue
        tree=ast.parse(path.read_text(encoding='utf8'))
        parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        def visible(node):
            current=node
            while current in parents:
                parent=parents[current]
                if isinstance(parent,ast.Raise):return True
                if isinstance(parent,ast.keyword) and parent.arg in FIELDS:return True
                if isinstance(parent,ast.Dict):
                    for key,value in zip(parent.keys,parent.values):
                        if value is current and isinstance(key,ast.Constant) and (key.value in FIELDS or (name=='packs.py' and key.value=='name')):return True
                if isinstance(parent,ast.Call) and isinstance(parent.func,ast.Attribute) and parent.func.attr=='append':
                    if 'advice' in ast.unparse(parent.func):return True
                if isinstance(parent,(ast.FunctionDef,ast.AsyncFunctionDef,ast.Module)):break
                current=parent
            return False
        for node in ast.walk(tree):
            if not visible(node):continue
            if isinstance(node,ast.JoinedStr):
                index=0;text=''
                for value in node.values:
                    if isinstance(value,ast.Constant):text+=str(value.value)
                    elif isinstance(value,ast.FormattedValue):text+='{'+str(index)+'}';index+=1
                put(text,name)
            elif isinstance(node,ast.Constant) and isinstance(node.value,str) and not isinstance(parents.get(node),ast.JoinedStr):
                put(node.value,name)
    for path in (ROOT/'app/src-tauri/src').glob('*.rs'):
        source=path.read_text(encoding='utf8').split('#[cfg(test)]',1)[0]
        for value in re.findall(r'"([^"\n]*(?:\\.[^"\n]*)*)"',source):
            if not re.search('[а-яёА-ЯЁ]',value):continue
            index=[0]
            def placeholder(match):
                n=index[0];index[0]+=1;return '{'+str(n)+'}'
            put(re.sub(r'\{[^{}]*\}',placeholder,value),str(path.relative_to(ROOT)))
    english=json.loads((ROOT/'app/src/lib/locales/en.json').read_text(encoding='utf8'))
    missing={key:value for key,value in sorted(found.items()) if key not in english}
    (ROOT/'reports/ui-i18n-source.json').write_text(json.dumps(missing,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(f'{len(missing)} additional UI messages need translation')


if __name__=='__main__':extract()
