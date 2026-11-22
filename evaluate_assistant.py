"""Model routing smoke test. Tools are simulated: no PC or home action executes."""
import argparse
import json
from pathlib import Path
import time

import llm
import tasks

CASES = [
    ("Открой калькулятор", {"app"}),
    ("Поставь таймер на 300 секунд", {"timer"}),
    ("Сначала открой калькулятор, затем поставь таймер на пять минут", {"app", "timer"}),
    ("Какая сейчас погода в Казани?", {"weather"}),
    ("Объясни, что такое оперативная память, ничего не открывай", set()),
]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model",default="gemma4:e4b")
    p.add_argument("--protocol",choices=["auto","native","tags"],default="native")
    p.add_argument("--limit",type=int,default=len(CASES))
    p.add_argument("--output",default="data/assistant-evaluation.json")
    a=p.parse_args()
    config={"llm":{"enabled":True,"provider":"ollama","url":"http://127.0.0.1:11434","model":a.model,"context":8192,"max_tokens":320,"temperature":0,"timeout":45,"tools":["app","timer","weather"],"commands":False,"agent":{"protocol":a.protocol,"max_steps":4,"timeout":90}}}
    results=[]
    for question,expected in CASES[:max(1,a.limit)]:
        calls=[]
        def execute(name,arg):
            calls.append({"name":name,"argument":arg})
            return ("data","Погода: минус пять градусов, ветер два метра в секунду") if name=="weather" else ("done","Имитация: действие успешно")
        llm.reset();start=time.monotonic()
        with tasks.scope(tasks.Token(timeout=95)):
            events=list(llm.respond(question,config,run_tool=execute))
        errors=[v for k,v in events if k=="error"]
        ok={c["name"] for c in calls}==expected and not errors
        results.append({"question":question,"expected":sorted(expected),"calls":calls,"reply":" ".join(v for k,v in events if k=="text"),"errors":errors,"seconds":round(time.monotonic()-start,2),"ok":ok})
        print(json.dumps(results[-1],ensure_ascii=False),flush=True)
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"model":a.model,"protocol":a.protocol,"simulated_tools":True,"passed":sum(r["ok"] for r in results),"total":len(results),"results":results},ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":main()
