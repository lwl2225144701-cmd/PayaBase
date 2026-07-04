"""Vision Prompts.

Prompts for image analysis via LLM Vision API.
"""

VISION_PROMPT = """请分析这张图片，完成以下任务：
1. 提取图片中的所有关键文字内容
2. 总结图片的核心信息和主旨
3. 识别图片类型（如：流程图、通知公告、数据报表、截图、表格、PPT页面等）

请用中文回答，格式如下：
【图片类型】xxx
【关键文字】提取的文字内容
【核心信息】图片内容总结"""
