from __future__ import annotations

import argparse
import threading
from pathlib import Path
from typing import Sequence

from interview_simulator.api_client import HttpPracticeApi
from interview_simulator.runtime import build_runtime, start_local_server
from interview_simulator.tui import BankInspectorApp
from interview_simulator.tui import PracticeApp


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查本地技术岗位面试题库是否可正常加载")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="配置文件路径，默认 ./config.json")
    parser.add_argument("--env-file", type=Path, default=Path(".env"), help="模型配置文件路径，默认 ./.env")
    parser.add_argument("--inspect", action="store_true", help="只打开题库检查器，不启动模型和练习服务")
    parser.add_argument("--web", action="store_true", help="启动本地浏览器面试页，不打开 Textual 终端界面")
    parser.add_argument("--port", type=int, help="本地 HTTP 端口；省略时自动选择可用端口")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.inspect and args.web:
        parser_error = "--inspect 与 --web 不能同时使用"
        raise SystemExit(parser_error)
    if args.port is not None and not 1 <= args.port <= 65535:
        raise SystemExit("--port 必须介于 1 和 65535")
    if args.inspect:
        BankInspectorApp(args.config).run()
        return

    runtime = build_runtime(
        config_path=args.config,
        env_path=args.env_file,
        database_path=Path("data/practice.db"),
    )
    server = start_local_server(runtime.app, port=args.port or 0)
    try:
        if args.web:
            print(f"浏览器面试页已启动：{server.base_url}")
            print("按 Ctrl+C 停止服务。")
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                return
        PracticeApp(HttpPracticeApi(server.base_url), page_size=runtime.config.ui.page_size).run()
    finally:
        server.stop()
