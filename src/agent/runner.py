from __future__ import annotations

import asyncio
import json
import queue
from dataclasses import dataclass, asdict
from typing import Any, Optional

from src.agent.core import agent_loop
from src.agent.memory import MemoryStore
from src.tools.registry import ToolRegistry
from src.ui import UIAdapter
from src.ui.status import UiStatus


def _return_preview(res: Any, max_lines: int = 3) -> str:
    if not res:
        return ""
    if isinstance(res, (dict, list)):
        text = json.dumps(res, ensure_ascii=True, indent=2, default=str)
    else:
        text = res if isinstance(res, str) else str(res)

    lines = text.splitlines()
    preview = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        preview = f"{preview}\n...({len(lines)-max_lines} lines hided)"
    return preview


@dataclass
class RunnerEvent:
    type: str
    data: dict[str, Any]


class SonexRunner:
    """Controller that connect the UI and agent workflow
    Duty:
    - Resolve the user input and call the agent loop
    - write back the running info(e.g. status, tool, context) to the UI
    - Every loop check the agent workflow and update runner, count the usage
    """

    def __init__(
        self,
        ui: UIAdapter,
        tools: ToolRegistry,
        memory_store: Optional[MemoryStore] = None,
        usage_tracker: int = 0
    ) -> None:
        self.ui = ui
        self.tools = tools
        self.memory_store = memory_store or MemoryStore()
        self._running_task: Optional[asyncio.Task[None]] = None
        self.usage_tracker = usage_tracker

    # 异步处理用户输入
    async def handle_user_input(self, user_input: str) -> None:
        """UI 提交一条用户输入后调用这里。

        这个函数通常只做两件事：
        - 先把用户消息显示到界面
        - 再启动后台 agent 处理
        """
        # 先锁定输入框
        self.ui.set_input_enabled(False)
        await self.ui.append_user_message(user_input)

        if self._running_task and not self._running_task.done():
            self.ui.set_status(UiStatus(phase="Busy", message="Remixing"))
            return

        self._running_task = asyncio.create_task(self._run_agent_turn(user_input))

    async def _run_agent_turn(self, user_input: str) -> None:
        """把同步的 agent_loop 放到线程里执行，
        然后将生成的事件逐个回写给 UI。
        """
        event_queue: asyncio.Queue[RunnerEvent] = asyncio.Queue()
        decision_queue: queue.Queue[bool] = queue.Queue()

        try:
            # agent_loop 是同步 generator，这里在后台线程里跑，
            # 避免阻塞 Textual UI 的事件循环

            def producer() -> None:
                try:
                    gen = agent_loop(
                        user_input=user_input,
                        tools=self.tools,
                        memory_store=self.memory_store,
                        session_id=self.memory_store.paths.session_id,
                    )
                    while True:
                        evt = next(gen)
                        asdict(evt)
                        if evt.type == "confirm":
                            event_queue.put_nowait(RunnerEvent(
                                type=evt.type,
                                data={
                                    "tool_name": evt.tool,
                                    "tool_args": evt.args,
                                }
                            ))
                            # 阻塞直到用户完成操作
                            dec = decision_queue.get()
                            gen.send(dec)

                        data = {}
                        if evt.type == "status":
                            data = {"content": evt.content}
                        elif evt.type == "tool":
                            data = {
                                "tool_name": evt.tool,
                                "tool_args": evt.args if evt.args else {},
                                "tool_result": evt.result if evt.result else None
                            }
                        elif evt.type == "error":
                            data = {"content": evt.content, "tool_name": evt.tool if evt.tool else None}
                        elif evt.type == "complete":
                            data = {"content": evt.content}

                        event_queue.put_nowait(RunnerEvent(
                            type=evt.type,
                            data=data,
                        ))
                        if evt.tokens:
                            self.usage_tracker = evt.tokens
                except Exception as exc:
                    event_queue.put_nowait(
                        RunnerEvent(
                            type="error",
                            data={"message": f"fatal: {exc}"},
                        )
                    )
                finally:
                    event_queue.put_nowait(RunnerEvent(type="done", data={}))

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, producer)

            while True:
                event = await event_queue.get()

                if event.type == "status":
                    if event.data.get("content") == "planning":
                        self.ui.set_status(UiStatus(phase="Planning", message="Composing..."))
                    elif event.data.get("content") == "cleaning":
                        self.ui.set_status(UiStatus(phase="Cleaning", message="Jazzing..."))
                    elif event.data.get("content") == "compacting":
                        self.ui.set_status(UiStatus(phase="Compacting", message="Covering..."))
                    continue

                if event.type == "confirm":
                    decision = await self.ui.ask_confirm(
                        {
                            "tool_name": event.data.get("tool_name"),
                            "tool_args": event.data.get("tool_args")
                        }
                    )
                    decision_queue.put(decision)
                    continue

                if event.type == "tool":
                    self.ui.set_status(UiStatus(phase="Tooling", message="Orchestrating..."))
                    tool_name = event.data.get("tool", "")
                    args = event.data.get("tool_args")
                    res = event.data.get("result")
                    if res:
                        preview = _return_preview(res, max_lines=3)
                        await self.ui.append_tool_message(f"Tool execution: {tool_name}\n |--> {preview}")
                    elif args:
                        await self.ui.append_tool_message(f"Calling tool: {tool_name} | args=({args})")
                    continue

                if event.type == "error":
                    await self.ui.append_tool_message(f"fatal: {event.data.get("content", "")}")
                    self.ui.set_status(UiStatus(phase="Retrying", message="Looping..."))
                    continue

                if event.type == "complete":
                    answer = event.data.get("content", "")
                    await self.ui.append_agent_message(answer)
                    break

        finally:
            # LLM执行完成后再解锁输入框
            self.ui.set_input_enabled(True)

    def stop(self) -> None:
        if self._running_task and not self._running_task.done():
            self._running_task.cancel()