"""Indexing Prompts.

Prompts used during document indexing pipeline (summary, HyDE).
"""

SUMMARY_SYSTEM_PROMPT = "你是文本摘要专家"

SUMMARY_USER_PROMPT = """请用{max_length}字以内的简短的摘要概括以下内容的主题和核心要点：

{text}

摘要："""

HYDE_SYSTEM_PROMPT = "You are a question generator"

HYDE_USER_PROMPT = """Based on the following content, generate {num_questions} hypothetical questions that this content could answer.
Output ONLY the questions, one per line, no numbering.

Content:
{text}

Questions:"""
