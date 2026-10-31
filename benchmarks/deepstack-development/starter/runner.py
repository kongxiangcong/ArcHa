"""JSON-lines interface; one request and result per line."""
import json
import copy
import sys
from model import estimate

for line in sys.stdin:
    try:
        request = json.loads(line)
        before = copy.deepcopy(request)
        result = estimate(request['config'], request['traffic'])
        if request != before:
            raise RuntimeError('candidate mutated its inputs')
        print(json.dumps({'result': result}, allow_nan=False), flush=True)
    except (ValueError, TypeError, KeyError) as exc:
        print(json.dumps({'error': type(exc).__name__}), flush=True)
