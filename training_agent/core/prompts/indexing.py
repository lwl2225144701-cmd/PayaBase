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

# 合并调用：一次 LLM 同时产出【摘要】与【问题】，减少一半 API 请求
COMBINED_SYSTEM_PROMPT = "你是文本处理助手，擅长用中文提炼要点并生成检索增强用的假设性问题。"

COMBINED_USER_PROMPT = """请处理以下内容，严格按以下格式输出（不要添加任何额外说明）：

【摘要】
用 {max_length} 字以内的中文概括内容的主题和核心要点。直接输出摘要正文，不要带“摘要：”“本文”等前缀。

【问题】
生成 {num_questions} 个该内容能回答的用户问题（用于检索增强，中英文皆可），每行一个，不要编号。

内容：
{text}

【摘要】
"""
