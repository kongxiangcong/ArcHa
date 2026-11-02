"""Standalone optional observer entry point; never initialises project data."""
from __future__ import annotations

import argparse
import ipaddress
import tempfile
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description='ArcHa 工作台（默认只读，--control 显式启用运行控制）')
    parser.add_argument('directory', nargs='?', type=Path, help='topics 集合或单个专题目录，相对当前目录')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--topics', '--topic', dest='topics', type=Path, help='topics 集合或单个专题目录')
    mode.add_argument('--project', type=Path, help='已有项目目录；只读访问')
    mode.add_argument('--demo', action='store_true', help='在临时目录创建明确标记的离线演示材料')
    parser.add_argument('--control', action='store_true', help='为已有项目显式启用运行控制')
    parser.add_argument('--host', default='127.0.0.1', help='只允许 loopback 地址')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args(argv)
    if sum((args.directory is not None, args.topics is not None, args.project is not None, args.demo)) != 1:
        parser.error('请选择一个专题路径、--topics、--project 或 --demo')
    topics = None
    if args.directory is not None or args.topics is not None:
        from .paths import resolve_topics
        try:
            args.project, topics = resolve_topics(args.directory or args.topics)
        except ValueError as exc:
            parser.error(str(exc))
    try:
        loopback = args.host == 'localhost' or ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        parser.error('首版只绑定 loopback；远程访问请使用已有 SSH 隧道')
    try:
        import uvicorn
        from .api import create_app
    except ImportError:
        parser.error("观察模块为可选安装：pip install '.[observer]'")
    if args.demo and args.control:
        parser.error('--demo 不能启用运行控制')
    if args.demo:
        from .demo import create_demo
        with tempfile.TemporaryDirectory(prefix='archa-observer-demo-') as temp:
            root = Path(temp)
            create_demo(root)
            uvicorn.run(create_app(root, demo=True), host=args.host, port=args.port)
    else:
        root = args.project.expanduser().resolve()
        if not root.is_dir():
            parser.error('--project 必须指向已有目录；观察器不会创建项目')
        uvicorn.run(create_app(root, control=args.control, topics=topics), host=args.host, port=args.port)


if __name__ == '__main__':
    main()
