# 只读观察工作台修复验收（2026-10-28）

## 基线与范围

基于远端 `codex/observer-workbench` 的最新提交 `5b62cd6cda9d346ce1c18ea410f64a6de88de25a`（PR #7），本地修复分支为 `fix/observer-history`。已通过 Git fetch 复核远端分支头。本文仅记录第一轮观察器修复及验证；后续 onboard 恢复修复另见 `docs/reports/20261028-onboard-accounting-recovery.md`。

本轮修复同目录任务重复发现、历史合同归属与正文校验混淆、普通任务混入全项目历史的问题。API 仍为原有 GET 路由，无执行接口或引擎改动。

## 实际执行结果

| 检查 | 结果 |
| --- | --- |
| 原始基线运行新增重点回归 | 8 failed、1 passed、51 deselected；覆盖双入口去重、四种绑定及多行边界 |
| 修复后的观察器测试 | 60 passed；新增 10 个测试函数、参数化后 16 个用例，并增强两个已有测试 |
| 全仓 pytest | 281 passed、5 skipped、12 subtests passed |
| TypeScript 与生产构建 | `npm --prefix web run build` 通过；包含 `tsc --noEmit`、Vite 和许可声明生成 |
| Chromium 实际浏览器烟测 | 13 组全部通过 |
| `git diff --check` | 通过 |

浏览器覆盖默认未选合同/run、任务总数稳定、todo 无其他任务历史、合同与 run 候选联动、独立历史入口、准备记录关闭状态和原始撤回原因、范围外显式合同/run 深链接、历史冻结目标、调用隔离、增量刷新和失败恢复、Markdown 安全、只读 GET、1440×900 与 390×844、键盘焦点、减少动画及放大字体。

只读验证在临时夹具上执行：后端读取前后文件快照一致，并阻止子进程启动；浏览器读取前后文件集合一致，普通源内容一致。浏览器夹具写入器主动追加的账本事件和替换的大文件被明确排除于内容不变断言，其他来源均须不变。所有合同、brief、SQLite 创建和改写只作用于临时夹具。

## 环境与复验

Linux / Python 3.12.14 / Node 24.19.0 / Chromium 154.0.8037.57 / Playwright 1.62.0。前端使用原锁文件 `npm ci`，未更改 package.json 或 package-lock.json。

全仓及初轮浏览器验证使用环境已有 FastAPI 0.141.1、Uvicorn 0.52.1、Pydantic 2.13.4；另在隔离依赖目录安装 pyproject.toml 声明的 FastAPI 0.119.1、Uvicorn 0.38.0、Pydantic 2.12.3，复验结果同样为观察器 60 passed、浏览器 13 组全部通过。

环境中的 pytest 安装于 `/workspace/work/test-deps`，固定版本观察器依赖安装于 `/workspace/work/observer-deps`，不修改仓库依赖声明。可复验：

```sh
PYTHONPATH=/workspace/work/test-deps python -m pytest -q
npm --prefix web ci
npm --prefix web run build
PYTHONPATH=/workspace/work/observer-deps:/workspace/work/test-deps python -m pytest opc/tests/test_observer.py -q
PYTHONPATH=/workspace/work/observer-deps python tools/observer_browser_smoke.py --chromium /usr/bin/chromium --out work/observer-browser-pinned
```

本机证据位于 `work/full-tests.txt`、`work/observer-tests.txt`、`work/observer-pinned-tests.txt`、`work/observer-browser/results.json` 和 `work/observer-browser-pinned/results.json`。截图与结果目录被 Git 忽略。

## 验证边界

本环境没有真实 `lp5_pim`，没有重新验证上传清单中的 8 个研究任务、11 份合同或 5,286 个文件哈希；这些历史结果不作为本轮证据。未读取或修改该真实项目，没有启用执行、运行研究、恢复归档合同、操作手机或触发 promote/apply。

Vite 仍提示单 chunk 超过 500 kB，构建成功。测试仅有现有依赖的弃用警告，未修改依赖以消除警告。当前实测为 Linux 与 Chromium，不扩展声称 Windows/WSL 或其他浏览器已通过。
