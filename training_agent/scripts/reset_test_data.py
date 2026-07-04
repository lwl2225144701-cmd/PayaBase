from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from core.config import settings
from models.tables import (
    Chunk,
    Conversation,
    Department,
    Document,
    KnowledgeBase,
    Message,
    PlatformConversation,
    PlatformMessageReceipt,
    PlatformUser,
    QueryLog,
    User,
)


TEST_SSO_IDS = {
    "admin",
    "training_admin_rd",
    "training_admin_sales",
    "training_admin_hr",
    "user_rd_01",
    "user_rd_02",
    "user_sales_01",
    "user_hr_01",
}

TEST_DEPARTMENT_CODES = {"RD", "SALES", "HR"}
TEST_KB_NAMES = {"研发知识库", "销售知识库", "人事知识库"}


def main() -> None:
    engine = create_engine(settings.sync_database_url)
    with Session(engine) as db:
        users = db.scalars(select(User).where(User.sso_id.in_(TEST_SSO_IDS))).all()
        user_ids = [u.id for u in users]

        if user_ids:
            conversation_ids = list(
                db.scalars(select(Conversation.id).where(Conversation.user_id.in_(user_ids))).all()
            )
            if conversation_ids:
                db.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
                db.execute(delete(PlatformConversation).where(PlatformConversation.conversation_id.in_(conversation_ids)))
                db.execute(
                    delete(PlatformMessageReceipt).where(
                        PlatformMessageReceipt.conversation_id.in_(conversation_ids)
                    )
                )
                db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))

            db.execute(delete(QueryLog).where(QueryLog.user_id.in_(user_ids)))
            db.execute(delete(PlatformUser).where(PlatformUser.user_id.in_(user_ids)))
            db.execute(delete(PlatformMessageReceipt).where(PlatformMessageReceipt.user_id.in_(user_ids)))
            db.execute(delete(User).where(User.id.in_(user_ids)))

        kbs = db.scalars(select(KnowledgeBase).where(KnowledgeBase.name.in_(TEST_KB_NAMES))).all()
        kb_ids = [kb.id for kb in kbs]
        if kb_ids:
            document_ids = list(
                db.scalars(select(Document.id).where(Document.knowledge_base_id.in_(kb_ids))).all()
            )
            if document_ids:
                db.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))
                db.execute(delete(Document).where(Document.id.in_(document_ids)))
            db.execute(delete(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))

        db.execute(delete(Department).where(Department.code.in_(TEST_DEPARTMENT_CODES)))
        db.commit()
        print("测试数据已清理完成")


if __name__ == "__main__":
    main()
