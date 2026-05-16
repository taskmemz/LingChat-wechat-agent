SPLIT_MARKER = "[split]"


def split_message(text: str) -> list[str]:
    if SPLIT_MARKER in text:
        parts = [p.strip() for p in text.split(SPLIT_MARKER) if p.strip()]
        return parts if parts else [text]

    if len(text) > 2000:
        import re

        sentences = re.split(r"(?<=[。！？.!?])\s*", text)
        parts = []
        current = ""
        for s in sentences:
            if len(current) + len(s) > 2000:
                if current:
                    parts.append(current.strip())
                current = s
            else:
                current += s
        if current:
            parts.append(current.strip())
        return parts if parts else [text]

    return [text]
