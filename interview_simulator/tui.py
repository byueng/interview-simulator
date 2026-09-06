from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from textual import on
from textual.app import App, ComposeResult, SuspendNotSupported
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static, TextArea

from interview_simulator.config import AppConfig
from interview_simulator.question_bank import QuestionBank


def read_terminal_answer(app: App[Any]) -> str:
    """Suspend Textual temporarily so the terminal can commit CJK IME text."""
    with app.suspend():
        return input("请输入完整回答（回车回填，留空取消）：")


class BankInspectorApp(App[None]):
    """第一阶段的只读题库加载检查界面。"""

    TITLE = "Interview Simulator · Agent 工程师赛道题库检查"
    BINDINGS = [
        ("r", "reload_bank", "重新加载"),
        ("q", "quit", "退出"),
    ]
    CSS = """
    #bank-status { margin: 1 2; }
    #bank-detail { margin: 0 2 1 2; color: $text-muted; }
    #question-table { height: 1fr; margin: 0 2 1 2; }
    """

    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self.config_path = config_path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("正在读取 config.json…", id="bank-status")
        yield Static("", id="bank-detail")
        yield DataTable(id="question-table", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#question-table", DataTable)
        table.add_columns("ID", "模块", "难度", "题目")
        self._load_bank()

    def action_reload_bank(self) -> None:
        self._load_bank()

    def _load_bank(self) -> None:
        status = self.query_one("#bank-status", Static)
        detail = self.query_one("#bank-detail", Static)
        table = self.query_one("#question-table", DataTable)
        try:
            config = AppConfig.load(self.config_path)
            bank = QuestionBank.scan(config.question_bank_path)
        except (OSError, ValueError) as exc:
            table.clear()
            status.update(f"题库加载失败：{exc}")
            detail.update(f"配置文件：{self.config_path}")
            return

        table.clear()
        for question in bank.page(page=1, page_size=config.ui.page_size)[0]:
            table.add_row(question.id, question.module, question.difficulty, question.title, key=question.id)
        status.update(f"题库已加载 {len(bank.questions)} 道题")
        detail.update(
            f"题库路径：{config.question_bank_path}｜当前预览：第 1 页，每页 {config.ui.page_size} 道｜按 r 重新加载"
        )


class PracticeApi(Protocol):
    async def list_questions(self, *, page: int, page_size: int) -> dict[str, object]: ...

    async def create_session(self, *, question_id: str, mode: str) -> dict[str, object]: ...

    async def submit_turn(self, *, session_id: str, answer: str) -> dict[str, object]: ...

    async def stream_turn(self, *, session_id: str, answer: str) -> Any: ...


class PracticeApp(App[None]):
    """正式练习界面；通过 PracticeApi 与本机服务交互。"""

    TITLE = "Interview Simulator · Agent 工程师赛道"
    BINDINGS = [("q", "quit", "退出")]

    def __init__(self, api: PracticeApi, *, page_size: int = 15) -> None:
        super().__init__()
        self.api = api
        self.page_size = page_size

    def on_mount(self) -> None:
        self.push_screen(QuestionListScreen(self.api, self.page_size))


class QuestionListScreen(Screen[None]):
    BINDINGS = [
        ("left,pageup", "previous_page", "上一页"),
        ("right,pagedown", "next_page", "下一页"),
    ]

    def __init__(self, api: PracticeApi, page_size: int) -> None:
        super().__init__()
        self.api = api
        self.page_size = page_size
        self.page = 1
        self.total = 0
        self._items_by_id: dict[str, dict[str, object]] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("正在加载题库…", id="list-status")
        yield DataTable(id="practice-question-table", cursor_type="row")
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one("#practice-question-table", DataTable)
        table.add_columns("ID", "模块", "难度", "练习状态", "题目")
        table.focus()
        await self._load_page()

    async def action_next_page(self) -> None:
        if self.page * self.page_size < self.total:
            self.page += 1
            await self._load_page()

    async def action_previous_page(self) -> None:
        if self.page > 1:
            self.page -= 1
            await self._load_page()

    @on(DataTable.RowSelected, "#practice-question-table")
    def open_selected_question(self, event: DataTable.RowSelected) -> None:
        question_id = str(event.row_key.value)
        item = self._items_by_id.get(question_id)
        if item is not None:
            self.app.push_screen(QuestionDetailScreen(self.api, item))

    async def _load_page(self) -> None:
        status = self.query_one("#list-status", Static)
        table = self.query_one("#practice-question-table", DataTable)
        try:
            payload = await self.api.list_questions(page=self.page, page_size=self.page_size)
        except Exception as exc:  # API errors must be visible to the learner.
            status.update(f"题库加载失败：{exc}")
            return

        items = payload["items"]
        self.total = int(payload["total"])
        self._items_by_id = {str(item["id"]): item for item in items if isinstance(item, dict)}
        table.clear()
        for question_id, item in self._items_by_id.items():
            latest_score = item.get("latest_score")
            practiced = bool(item.get("practiced"))
            practice_status = f"已练习 {latest_score:.1f}" if practiced and isinstance(latest_score, (int, float)) else "未练习"
            table.add_row(
                question_id,
                str(item["module"]),
                str(item["difficulty"]),
                practice_status,
                str(item["title"]),
                key=question_id,
            )
        page_count = max(1, (self.total + self.page_size - 1) // self.page_size)
        status.update(f"题库 {self.total} 题｜第 {self.page}/{page_count} 页｜↑↓ 选择，Enter 进入，←→ 翻页")


class QuestionDetailScreen(Screen[None]):
    BINDINGS = [
        ("enter", "start_deep", "深入面试"),
        ("s", "start_single", "单题评分"),
        ("escape", "app.pop_screen", "返回"),
    ]

    def __init__(self, api: PracticeApi, question: dict[str, object]) -> None:
        super().__init__()
        self.api = api
        self.question = question

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Vertical(
            Static(str(self.question["title"]), id="question-title"),
            Static(f"题号：{self.question['id']}｜模块：{self.question['module']}｜难度：{self.question['difficulty']}"),
            Static("Enter 开始深入面试（最多 10 轮）｜s 单题评分｜Esc 返回", id="detail-hint"),
        )
        yield Footer()

    async def action_start_deep(self) -> None:
        await self._start("deep")

    async def action_start_single(self) -> None:
        await self._start("single")

    async def _start(self, mode: str) -> None:
        session = await self.api.create_session(question_id=str(self.question["id"]), mode=mode)
        self.app.push_screen(InterviewScreen(self.api, session, mode))


class InterviewScreen(Screen[None]):
    BINDINGS = [
        ("ctrl+enter", "submit_answer", "提交回答"),
        ("f2", "terminal_input", "中文输入"),
        ("escape", "app.pop_screen", "返回题目"),
    ]

    def __init__(self, api: PracticeApi, session: dict[str, object], mode: str) -> None:
        super().__init__()
        self.api = api
        self.session = session
        self.mode = mode
        self.current_question = str(session["title"])
        self.transcript_text = f"面试官：{self.current_question}"
        self._submitting = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(self.current_question, id="interview-question")
        yield Static(f"模式：{'深入面试' if self.mode == 'deep' else '单题评分'}", id="interview-status")
        yield Static(self.transcript_text, id="transcript")
        yield TextArea(id="answer-input")
        yield Button("开始中文作答（普通终端）", id="terminal-input")
        yield Button("提交回答（Ctrl+Enter）", id="submit-answer", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#answer-input", TextArea).focus()

    @on(Button.Pressed, "#submit-answer")
    async def submit_from_button(self) -> None:
        await self._submit_answer()

    async def action_submit_answer(self) -> None:
        await self._submit_answer()

    @on(Button.Pressed, "#terminal-input")
    def input_from_terminal_button(self) -> None:
        self.action_terminal_input()

    def action_terminal_input(self) -> None:
        if self._submitting:
            return
        try:
            answer = read_terminal_answer(self.app)
        except SuspendNotSupported:
            self.query_one("#interview-status", Static).update("当前终端不支持普通输入模式，请使用 Cmd+V 粘贴中文回答")
            return

        if not answer.strip():
            self.query_one("#interview-status", Static).update("未输入内容，已保留当前回答")
            return

        answer_input = self.query_one("#answer-input", TextArea)
        answer_input.text = answer
        answer_input.focus()
        self.query_one("#interview-status", Static).update("已回填普通终端输入的回答，按 Ctrl+Enter 提交")

    async def _submit_answer(self) -> None:
        if self._submitting:
            return
        answer_input = self.query_one("#answer-input", TextArea)
        answer = answer_input.text.strip()
        if not answer:
            self.query_one("#interview-status", Static).update("回答不能为空")
            return
        self._submitting = True
        answer_input.disabled = True
        self.query_one("#submit-answer", Button).disabled = True
        self._append_transcript(f"\n\n你：{answer}\n\n面试官：")
        self.query_one("#interview-status", Static).update("面试官正在生成回复…")
        rendered_fields = {"feedback": "", "next_question": "", "interviewer_feedback": ""}
        completed = False
        try:
            async for event in self.api.stream_turn(session_id=str(self.session["id"]), answer=answer):
                event_type = event.get("event")
                if event_type == "delta":
                    field = str(event.get("field", ""))
                    text = str(event.get("text", ""))
                    if not text or field not in rendered_fields:
                        continue
                    if field == "next_question" and not rendered_fields[field]:
                        self._append_transcript("\n追问：")
                    rendered_fields[field] += text
                    self._append_transcript(text)
                    continue
                if event_type == "error":
                    raise RuntimeError(str(event.get("message", "模型流式生成失败")))
                if event_type != "completed":
                    continue

                payload = event.get("payload")
                if not isinstance(payload, dict):
                    raise RuntimeError("本机服务没有返回流式完成结果")
                completed = True
                if bool(payload.get("ended")):
                    evaluation = payload.get("evaluation")
                    if not isinstance(evaluation, dict):
                        raise RuntimeError("本机服务没有返回最终评分")
                    self._append_missing_text(rendered_fields, "interviewer_feedback", str(evaluation.get("interviewer_feedback", "")))
                    self.query_one("#interview-status", Static).update(f"最终得分：{evaluation.get('score', '—')}")
                    break

                self._append_missing_text(rendered_fields, "feedback", str(payload.get("feedback", "")))
                next_question = str(payload.get("next_question", ""))
                if not rendered_fields["next_question"] and next_question:
                    self._append_transcript("\n追问：")
                self._append_missing_text(rendered_fields, "next_question", next_question)
                self.current_question = next_question
                self.query_one("#interview-question", Static).update(self.current_question)
                self.query_one("#interview-status", Static).update("请继续回答下一轮")
                break
            if not completed:
                raise RuntimeError("模型流式响应在完成前中断")
        except Exception as exc:
            self.query_one("#interview-status", Static).update(f"生成失败：{exc}")
        finally:
            if completed:
                answer_input.clear()
            answer_input.disabled = False
            self.query_one("#submit-answer", Button).disabled = False
            self._submitting = False

    def _append_transcript(self, text: str) -> None:
        self.transcript_text += text
        self.query_one("#transcript", Static).update(self.transcript_text)

    def _append_missing_text(self, rendered_fields: dict[str, str], field: str, expected: str) -> None:
        rendered = rendered_fields[field]
        if expected.startswith(rendered):
            missing = expected[len(rendered) :]
            if missing:
                rendered_fields[field] = expected
                self._append_transcript(missing)
