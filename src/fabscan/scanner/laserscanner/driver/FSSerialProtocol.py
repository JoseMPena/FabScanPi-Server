def read_response_until_ready(readline, ready_prompt=b">"):
    response_lines = []

    while True:
        line = readline()
        if line is None or line == b"":
            break

        stripped = line.strip()
        if stripped == ready_prompt:
            break

        if stripped:
            response_lines.append(stripped.decode(errors="replace"))

    return "\n".join(response_lines)
