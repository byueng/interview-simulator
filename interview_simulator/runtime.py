from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

from interview_simulator.api import create_app
from interview_simulator.config import AppConfig
from interview_simulator.logging_config import configure_logging, get_logger
from interview_simulator.llm import ModelSettings, OpenAICompatibleInterviewer
from interview_simulator.question_bank import QuestionBank
from interview_simulator.service import InterviewService
from interview_simulator.storage import SQLiteStorage


@dataclass(frozen=True, slots=True)
class Runtime:
    config: AppConfig
    bank: QuestionBank
    storage: SQLiteStorage
    service: InterviewService
    app: FastAPI


@dataclass(slots=True)
class RunningServer:
    base_url: str
    _server: uvicorn.Server
    _thread: threading.Thread
    _socket: socket.socket

    def stop(self) -> None:
        get_logger().info("local_server stopping")
        self._server.should_exit = True
        self._thread.join(timeout=5.0)
        try:
            self._socket.close()
        except OSError:
            pass
        get_logger().info("local_server stopped")


def build_runtime(
    *, config_path: Path, env_path: Path, database_path: Path, log_directory: Path = Path("logs")
) -> Runtime:
    logger = configure_logging(log_directory)
    config = AppConfig.load(config_path)
    bank = QuestionBank.scan(config.question_bank_path)
    storage = SQLiteStorage(database_path)
    model_settings = ModelSettings.from_env_file(env_path)
    interviewer = OpenAICompatibleInterviewer(
        model_settings,
        temperature=config.scoring.temperature,
        feedback_style=config.scoring.feedback_style,
    )
    service = InterviewService(bank, storage, interviewer)
    logger.info("runtime_initialized questions=%s", len(bank.questions))
    return Runtime(config, bank, storage, service, create_app(service, bank, storage))


def start_local_server(app: FastAPI, *, port: int = 0) -> RunningServer:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    port = listener.getsockname()[1]
    config = uvicorn.Config(app, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    running = RunningServer(f"http://127.0.0.1:{port}", server, thread, listener)
    _wait_until_healthy(running)
    get_logger().info("local_server started address=%s", running.base_url)
    return running


def _wait_until_healthy(server: RunningServer) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not server._thread.is_alive():
            server.stop()
            raise RuntimeError("本机面试服务启动失败")
        try:
            response = httpx.get(f"{server.base_url}/health", timeout=0.2)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.05)
    server.stop()
    raise RuntimeError("本机面试服务启动超时")
