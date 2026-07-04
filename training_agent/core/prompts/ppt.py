"""PPT Structure Generation Prompt."""

PPT_STRUCTURE_PROMPT = """你是一个PPT结构生成器。将以下培训方案内容转换为PPT幻灯片结构。

【方案内容】
{content}

【输出要求】
严格输出 JSON，不要有其他文字。格式如下：

{{
  "slides": [
    {{"type": "title", "title": "PPT主标题", "subtitle": "副标题"}},
    {{"type": "content", "title": "页面标题", "points": ["要点1", "要点2", "要点3"]}},
    {{"type": "two_column", "title": "页面标题", "left": ["左侧要点1", "左侧要点2"], "right": ["右侧要点1", "右侧要点2"]}},
    {{"type": "summary", "title": "总结", "points": ["总结要点1", "总结要点2"]}}
  ]
}}

【规则】
1. slides[0] 必须是 title 类型
2. 总页数 6-15 页
3. 每页要点不超过 6 条
4. 内容来自原文，不要编造
5. 最后一页使用 summary 类型
6. 保持语言风格一致"""
