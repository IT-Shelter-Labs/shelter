"""Maintain human-reviewed UI translations against the frozen extraction inventory."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INVENTORY=ROOT/'reports/ui-i18n-source.json'
TARGET=ROOT/'app/src/lib/locales/en.json'
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8')
    sys.stdin.reconfigure(encoding='utf8')
    keys=list(json.loads(INVENTORY.read_text(encoding='utf8')))
    start=int(sys.argv[2]); count=int(sys.argv[3])
    if sys.argv[1]=='show':
        for i in range(start,min(start+count,len(keys))):print(f'{i}: {keys[i]}')
    elif sys.argv[1]=='put':
        rows=sys.stdin.read().strip().splitlines()
        if len(rows)!=count:raise SystemExit(f'Expected {count} rows, got {len(rows)}')
        data=json.loads(TARGET.read_text(encoding='utf8'))
        for index,text in enumerate(rows,start):
            label,text=text.split('|',1)
            if int(label)!=index:raise SystemExit(f'Index mismatch: expected {index}, got {label}')
            data[keys[index]]=text.strip()
        TARGET.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(f'{len(data)}/{len(keys)} translated')
