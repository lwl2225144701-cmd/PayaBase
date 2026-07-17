"""应用层：用例服务（编排领域，无业务规则）。

Phase 2 落地：
- chat/SendMessageUseCase（替换 chat_pipeline.handle_chat）
- knowledge_base/ImportDocumentUseCase / IndexDocumentUseCase
- artifact/GenerateArtifactUseCase
- agent/RunAgentUseCase

应用层只做编排，业务规则下沉到领域层。
"""
