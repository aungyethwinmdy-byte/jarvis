from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core import moi_index as ix

s = ix.status()
print('=== MOI INDEX STATUS ===')
print('DB Path     :', s['db'])
print('Total rows  :', s['total'])
print('Oldest date :', s['oldest'])
print('Newest date :', s['newest'])
print('Last run    :', s['last_run'])
print('Last new    :', s['last_new'])
print('Last attempt:', s['last_attempt'])
print('Attempt result:', s['last_attempt_result'])
print('Is stale?   :', ix.is_stale())
print()
print('=== SECTIONS ===')
for sec in s['sections']:
    print(f"  {sec['label']:30s} : {sec['count']} articles")
