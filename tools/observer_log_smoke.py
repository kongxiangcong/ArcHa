"""Real HTTP/UI and append code with a deterministic stand-in for model generation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright, expect
from opc.log import update
from opc.observer.api import create_app
from opc.tests.test_observer_canvas import source
from opc.tests.test_research_log import prose
from tools.observer_canvas_smoke import serve

with tempfile.TemporaryDirectory() as temp:
    root = Path(temp);case = source(root)
    app = create_app(root, topics=case['topic'])
    run = app.state.adapter._id('run', 'run-dma-r1')
    failed = [False]; calls = []
    def launch(argv, **kwargs):
        assert argv[1:3] == ['-m', 'opc.log']
        calls.append(argv)
        if failed[0]:
            return subprocess.CompletedProcess(argv, 1, json.dumps({'error': '模拟整理失败'}), '')
        return subprocess.CompletedProcess(argv, 0, json.dumps(update(root, 'run-dma-r1', generator=prose)), '')
    server, thread, origin = serve(app)
    try:
        with patch('subprocess.run', launch), sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            page = browser.new_page(viewport=dict(width=1440, height=1000))
            page.goto(origin + '/?run=' + run)
            page.get_by_role('button', name='研究日志', exact=True).click()
            dialog = page.get_by_role('dialog', name='研究日志')
            expect(dialog).to_be_visible()
            expect(dialog).to_contain_text('已追加')
            expect(dialog.get_by_role('heading', name='当时的问题').first).to_be_visible()
            assert 'archa-log {' not in dialog.inner_text()
            first = (case['topic']/'tasks/r01-dma/PROGRESS_LOG.md').read_bytes()
            page.get_by_role('button',name='更新日志',exact=True).click()
            expect(dialog).to_contain_text('没有新的研究进展')
            assert first == (case['topic']/'tasks/r01-dma/PROGRESS_LOG.md').read_bytes()
            failed[0] = True
            page.get_by_role('button',name='更新日志',exact=True).click()
            expect(dialog).to_contain_text('模拟整理失败')
            expect(dialog).to_contain_text('已有记录表明完成局部检查')
            assert first == (case['topic']/'tasks/r01-dma/PROGRESS_LOG.md').read_bytes()
            page.set_viewport_size(dict(width=390,height=600))
            assert dialog.bounding_box()['width'] <= 390
            page.keyboard.press('Escape');expect(dialog).to_have_count(0)
            expect(page.get_by_role('button',name='研究日志',exact=True)).to_be_focused()
            assert not app.state.adapter.control_enabled
            app.state.adapter.demo = True
            count = len(calls)
            page.get_by_role('button',name='研究日志',exact=True).click()
            expect(dialog).to_contain_text('只读模式')
            expect(dialog.get_by_role('button',name='更新日志',exact=True)).to_be_disabled()
            assert len(calls) == count
            print('PASS explicit update / Markdown display / no duplicate append / failure retains old log / narrow dialog / Escape focus / default log updates without run control / demo read-only mode')
            browser.close()
    finally:
        server.should_exit = True;thread.join(timeout=5)
