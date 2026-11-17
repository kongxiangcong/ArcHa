"""Small projections of supported native JSONL; all other output stays raw."""
import json


def text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


class NativeEvents:
    def __init__(self, provider):
        self.provider = provider
        self.calls = {}

    def parse(self, line):
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError):
            return None
        if not isinstance(value, dict):
            return None
        kind = value.get('type')
        if self.provider == 'dsh':
            if kind not in ('tool_call', 'tool_result', 'status', 'error'):
                return None
            if value.get('truncated'):
                raise ValueError(f'DSH {kind}: native event truncated')
            if kind == 'tool_call':
                name = value['tool']
                self.calls[value['callId']] = name
                return ('tool', f'{name} started', 'running', text(value['input']))
            if kind == 'tool_result':
                call = value['callId']
                name = self.calls.pop(call, call)
                status = value['status']
                if status not in ('completed', 'error'):
                    raise ValueError('DSH tool_result: invalid status')
                return ('tool', f'{name} ended', 'error' if status == 'error' else 'ok', text(value.get('error', value['result'])))
            if kind == 'status' and value.get('phase') == 'step_end' and 'usage' in value:
                usage = value['usage']
                if not isinstance(usage, dict) or not {'inputTokens', 'outputTokens'} <= usage.keys():
                    raise ValueError('DSH step_end: malformed usage')
                return ('usage', 'usage', 'info', text(usage))
            if kind == 'error':
                return ('diagnostic', 'provider error', 'error', text(value['message']))
        elif self.provider == 'codex':
            if kind in ('item.started', 'item.completed'):
                item = value['item']
                if item['type'] not in ('command_execution', 'mcp_tool_call', 'web_search', 'file_change'):
                    return None
                started = kind == 'item.started'
                name = item.get('command') or item.get('tool') or item['type']
                return ('tool', f'{name} {"started" if started else "ended"}',
                        'running' if started else ('error' if item.get('status') == 'failed' or item.get('exit_code') not in (None, 0) else 'ok'), text(item))
            if kind == 'turn.completed':
                usage = value['usage']
                if not isinstance(usage, dict) or not {'input_tokens', 'output_tokens'} <= usage.keys():
                    raise ValueError('Codex turn.completed: malformed usage')
                return ('usage', 'usage', 'info', text(usage))
            if kind in ('error', 'turn.failed'):
                return ('diagnostic', 'provider error', 'error', text(value['message'] if kind == 'error' else value['error']))
        return None
