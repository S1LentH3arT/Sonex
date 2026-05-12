import json

from src.config.thinking import sonex_home, ThinkingConfig

SUMMARY_SYSTEM_PROMPT = """
You are a helpful assistant for compressing conversation history.
Given the full conversation history below, generate a concise summary that captures the key points and important details.
Make sure the summary should be no more than 3000 tokens.
"""

def save_history(history: list, session_id: str) -> None:
    transcript_path = sonex_home() / "transcripts" / f"transcript_{session_id}.jsonl"
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    with open(transcript_path, "w", encoding="utf-8") as f:
        for msg in history:
            f.write(json.dumps(msg, default=str) + "\n")

def snip_compact(history: list) -> list:
    compacted = []
    for i, item in enumerate(history):
        pass # Placeholder as before
    return compacted

def auto_compact(history: list, model: str, session_id: str) -> list:
    save_history(history, session_id)
    client = ThinkingConfig.get_client()

    summary = client.responses.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": SUMMARY_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(history, default=str),
            },
        ],
        max_tokens=3000,
    )

    return [
        {
            "role": "user",
            "content": f"[Compressed]\n\n{summary.output_text.strip()}",
        }
    ]
