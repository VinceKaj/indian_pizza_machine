import urllib.request
import json

url = "http://localhost:9000/api/graph/ingest?fresh=true"
req = urllib.request.Request(url, method="POST")
try:
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode())
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f"Error: {e}")
