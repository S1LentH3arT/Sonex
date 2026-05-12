import json

from src.agent.action import Action
from src.agent.memory import MemoryStore
from src.config.thinking import ThinkingConfig
from src.tools.registry import registry

PLANNER_SYSTEM_PROMPT = """You are an agent planner.
Read the following guidelines, include plan, findings and process three parts
Based on the guidelines, decide if you need to call a tool to assist your thinking. 
If so, choose the most appropriate tool and call it with the correct arguments.
If not, directly output your thoughts and conclusions.
"""

def llm_plan(
    memory: MemoryStore,
) -> Action:
    mem = memory.load_memory()
    client = ThinkingConfig.get_client()
    model = ThinkingConfig.get_model()

    messages = [
        {
            "role": "system",
            "content": PLANNER_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": f"[plan.md]\n{mem['plan'][-2000:]}"
        },
        {
            "role": "user",
            "content": f"[findings.md]\n{mem['findings'][-6000:]}"
        },
        {
            "role": "user",
            "content": f"[process.md]\n{mem['process'][-2000:]}"
        }
    ]

    response = client.responses.create(
        model=model,
        messages=messages,
        tools=registry.schemas(),
        tool_choice="auto",
    )

    # 获取每次调用的token数
    usage = getattr(response, "usage", None)
    total_tokens = getattr(response, "total_tokens", 0) if usage else 0

    # 先找是否调用function
    for item in getattr(response, "output", []):
        item_type = item["type"]
        if item_type == "function_call":
            name = item.get("name")
            arguments = item.get("arguments")
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                args = {}
            if name:
                return Action(tool=name, args=args, usage=total_tokens)
    # 没有tool-call就输出文本
    text = getattr(response, "output_text", None)
    if not text:
        chunks = []
        for item in getattr(response, "output", []):
            item_type = item.get("type")
            if item_type != "message":
                continue
            content = item.get("content")
            for c in content:
                c_type = c.get("type")
                if c_type == "output_text":
                    chunks.append(c.get("text"))
        text = "\n".join([x for x in chunks if x]).strip()
    return Action(output=text, usage=total_tokens)