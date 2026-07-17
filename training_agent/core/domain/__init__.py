"""DDD 领域层。

按限界上下文组织子包，每个子包含 aggregates.py（领域实体/聚合根）
与 repository.py（仓储端口 Protocol）。

设计约束：
- 领域层不依赖 api/、不依赖框架、运行时不依赖 models/（ORM）。
- 端口方法返回类型经 TYPE_CHECKING 引用 ORM，运行时零依赖。
- Phase 4 将引入独立领域 dataclass + ORM 映射，使领域层完全脱离 ORM。
"""
