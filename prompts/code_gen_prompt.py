CODE_GEN_PROMPT = """
You are given the COMPLETE content of a file from a GitHub repository.
Your job is to modify it according to the instruction and return the COMPLETE updated file.

STRICT RULES:
- Return the COMPLETE file content — every single line
- NEVER write TODO comments or placeholders
- NEVER write "Add content here" or "Update this"
- NEVER return partial code or snippets
- Write REAL working Python code only
- If adding docstrings, write the actual description of what the function does
- If adding type hints, use real Python types like str, int, float, list, dict, bool

File path: {file_path}

Current file content:
{file_content}

Instruction: {instruction}

Return ONLY the complete updated file content. No explanations. No markdown. Just the raw code.
"""
