import json
import urllib.request

queries = [
    ('ஆவடி', 'ta'),
    ('போரூரில் இருந்து கிண்டி போகணும்', 'ta'),
    ('Avadi to Poonamallee', 'en'),
]

for q, lang in queries:
    payload = json.dumps({'query': q, 'language': lang}).encode('utf-8')
    req = urllib.request.Request(
        'http://192.168.137.171:8000/api/mobility/simulate',
        data=payload,
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        resp = json.loads(r.read().decode('utf-8'))
        print(f"QUERY: {q} [{lang}]")
        print(f"STATUS: {resp.get('status')}")
        print(f"SPEECH: {resp.get('speech_text')}")
        print("-" * 50)

