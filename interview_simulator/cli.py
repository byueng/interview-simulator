from __future__ import annotations

import argparse
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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if args.inspect:
        BankInspectorApp(args.config).run()
        return

    runtime = build_runtime(
        config_path=args.config,
        env_path=args.env_file,
        database_path=Path("data/practice.db"),
    )
    server = start_local_server(runtime.app)
    try:
        PracticeApp(HttpPracticeApi(server.base_url), page_size=runtime.config.ui.page_size).run()
    finally:
        server.stop()
