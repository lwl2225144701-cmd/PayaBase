# MVP Agent 回归结果

- 生成时间: 2026-05-17 02:58:50

## 路由覆盖

- `content_generation`: 1
- `document_summary`: 1
- `pdf_generation`: 1
- `ppt_generation`: 1
- `rag_qa`: 3

## 用例结果

### Case 1
- Query: `请基于知识库回答：培训管理制度的核心流程是什么？`
- Conversation: `dc465e37-68bf-480a-8527-40792ee57470`
- Run: `43aa8caa-a2bd-4b26-99a4-ba638eee23e1` status=`completed` route=`rag_qa`
- SSE finished: `True` artifacts=0
- Content preview: 根据知识库检索，培训管理制度的核心流程通常遵循一个完整的PDCA（计划-执行-检查-处理）循环，旨在系统化地提升员工能力与组织效能核心流程可概
- Retry step hit: `False`
- Steps: 2
  - `step-1` type=`rag_qa` status=`success` error=``
  - `finalize-1` type=`finalize_response` status=`success` error=``

### Case 2
- Query: `请总结一下培训管理制度的核心内容。`
- Conversation: `16bbda65-9640-4852-b156-bca1398eaab6`
- Run: `c0399c96-b03c-4c34-b8aa-071e935a9cb3` status=`completed` route=`document_summary`
- SSE finished: `True` artifacts=0
- Content preview: ### 核心结论 由于未培训管理制度文本或资料有限**，无法总结。   目前无法提取任何，因为缺少制度的原始文档或描述。  ### 行动建议 1.  **提供请提供
- Retry step hit: `False`
- Steps: 2
  - `step-1` type=`document_summary` status=`success` error=``
  - `finalize-1` type=`finalize_response` status=`success` error=``

### Case 3
- Query: `请输出一份非常完整的方案，如果失败请自动重试并给出可执行结果。`
- Conversation: `9026762f-2617-4fc0-8454-4614333590f6`
- Run: `84fbb9f8-d001-4fa3-bff4-e6fdc5ab1c95` status=`completed` route=`content_generation`
- SSE finished: `True` artifacts=0
- Content preview: **企业新培训方案 (草案)**  **资料有限，以下为保守草案，基于通用企业培训实践生成。**  ---  ### **一、 方案名称** 企业体系化实施方案  ### **二、 培
- Retry step hit: `False`
- Steps: 2
  - `step-1` type=`content_generation` status=`success` error=``
  - `finalize-1` type=`finalize_response` status=`success` error=``

### Case 4
- Query: `请基于已有资料生成一份培训宣讲PPT大纲，并创建PPT任务。`
- Conversation: `2f31bf47-1e48-4376-9977-0ae0d130cf49`
- Run: `629aef76-01b9-41ac-9ff1-25a5e091895f` status=`completed` route=`ppt_generation`
- SSE finished: `True` artifacts=1
- Content preview: PPT「MVP Regression 2026-05-16T18:58:02」正在后台生成，请稍候... 来源：无资料
- Retry step hit: `False`
- Steps: 2
  - `step-1` type=`ppt_generation` status=`success` error=``
  - `finalize-1` type=`finalize_response` status=`success` error=``

### Case 5
- Query: `请基于已有资料生成一份培训总结PDF，并创建PDF任务。`
- Conversation: `86bacbb1-75d3-49c2-b260-e29a33a71cf1`
- Run: `b3810b16-0279-4393-be4a-c03b5ca73ada` status=`completed` route=`pdf_generation`
- SSE finished: `True` artifacts=1
- Content preview: PDF「MVP Regression 2026-05-16T18:58:14」正在后台生成，请稍候... 来源：无资料
- Retry step hit: `False`
- Steps: 2
  - `step-1` type=`pdf_generation` status=`success` error=``
  - `finalize-1` type=`finalize_response` status=`success` error=``

### Case 6
- Query: `如果本次处理失败，请触发重试并给出降级提示。`
- Conversation: `b1d0d98e-451e-4336-b215-17522c1594f4`
- Run: `4b7c9fc7-a339-4be8-a400-a1284129ac34` status=`completed` route=`rag_qa`
- SSE finished: `True` artifacts=0
- Content preview: 基于您提供的“自治执行上下文”，如果本次处理（即`rag_qa`路由下的`step-1`步骤）失败，系统将执行以下操作：  1.  **触发重试**：系统会自动尝试重新
- Retry step hit: `False`
- Steps: 2
  - `step-1` type=`rag_qa` status=`success` error=``
  - `finalize-1` type=`finalize_response` status=`success` error=``

### Case 7
- Query: `[FORCE_AGENT_STEP1_FAIL] 请在失败后自动重试，并输出降级结果。`
- Conversation: `cde06474-5524-4e10-97d3-f9fe5e460a8b`
- Run: `7eb7ef67-3d3e-4e79-a42d-569d65924b42` status=`completed` route=`rag_qa`
- SSE finished: `True` artifacts=0
- Content preview: 您好，我注意到这个请求看起来自动化指令，而非的企业培训问题。  **我无法处理这类系统级指令，因为：** 1. 没场景或培训 不想要问题  **
- Retry step hit: `True`
- Steps: 2
  - `step-1` type=`rag_qa` status=`failed` error=`unknown:forced_step1_failure_for_mvp_regression`
  - `retry-1` type=`retry_decision` status=`success` error=``
