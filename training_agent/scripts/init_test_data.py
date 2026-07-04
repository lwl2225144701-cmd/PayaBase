import uuid
from dataclasses import dataclass

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from core.config import settings
from models.tables import Department, KnowledgeBase, Tenant, User


DEFAULT_TENANT_NAME = "Default Tenant"


@dataclass(frozen=True)
class DepartmentSeed:
    name: str
    code: str
    hr_department_id: str


@dataclass(frozen=True)
class UserSeed:
    sso_id: str
    name: str
    email: str
    role: str
    department_code: str | None = None


@dataclass(frozen=True)
class KnowledgeBaseSeed:
    name: str
    description: str
    department_code: str


DEPARTMENTS = [
    DepartmentSeed("研发部", "RD", "dept-rd"),
    DepartmentSeed("销售部", "SALES", "dept-sales"),
    DepartmentSeed("人事部", "HR", "dept-hr"),
]

USERS = [
    UserSeed("admin", "超级管理员", "admin@test.local", "admin"),
    UserSeed("training_admin_rd", "研发培训管理员", "training_admin_rd@test.local", "training_admin", "RD"),
    UserSeed("training_admin_sales", "销售培训管理员", "training_admin_sales@test.local", "training_admin", "SALES"),
    UserSeed("training_admin_hr", "人事培训管理员", "training_admin_hr@test.local", "training_admin", "HR"),
    UserSeed("user_rd_01", "研发普通用户A", "user_rd_01@test.local", "user", "RD"),
    UserSeed("user_rd_02", "研发普通用户B", "user_rd_02@test.local", "user", "RD"),
    UserSeed("user_sales_01", "销售普通用户A", "user_sales_01@test.local", "user", "SALES"),
    UserSeed("user_hr_01", "人事普通用户A", "user_hr_01@test.local", "user", "HR"),
]

KNOWLEDGE_BASES = [
    KnowledgeBaseSeed("研发知识库", "用于研发测试的知识库", "RD"),
    KnowledgeBaseSeed("销售知识库", "用于销售测试的知识库", "SALES"),
    KnowledgeBaseSeed("人事知识库", "用于人事测试的知识库", "HR"),
]


def get_or_create_default_tenant(db: Session) -> Tenant:
    tenant = db.scalar(select(Tenant).where(Tenant.name == DEFAULT_TENANT_NAME))
    if tenant:
        return tenant

    tenant = db.scalar(select(Tenant).order_by(Tenant.created_at.asc()).limit(1))
    if tenant:
        return tenant

    tenant = Tenant(name=DEFAULT_TENANT_NAME, config={"seeded_for_test": True})
    db.add(tenant)
    db.flush()
    return tenant


def seed_departments(db: Session, tenant: Tenant) -> dict[str, Department]:
    result: dict[str, Department] = {}
    for seed in DEPARTMENTS:
        dept = db.scalar(
            select(Department).where(
                Department.tenant_id == tenant.id,
                Department.code == seed.code,
            )
        )
        if not dept:
            dept = Department(
                tenant_id=tenant.id,
                name=seed.name,
                code=seed.code,
                hr_department_id=seed.hr_department_id,
            )
            db.add(dept)
            db.flush()
        else:
            dept.name = seed.name
            dept.hr_department_id = seed.hr_department_id
        result[seed.code] = dept
    return result


def seed_users(db: Session, tenant: Tenant, departments: dict[str, Department]) -> list[User]:
    users: list[User] = []
    for seed in USERS:
        user = db.scalar(select(User).where(User.sso_id == seed.sso_id))
        department_id = departments[seed.department_code].id if seed.department_code else None
        if not user:
            user = User(
                tenant_id=tenant.id,
                department_id=department_id,
                name=seed.name,
                email=seed.email,
                sso_id=seed.sso_id,
                role=seed.role,
            )
            db.add(user)
            db.flush()
        else:
            user.tenant_id = tenant.id
            user.department_id = department_id
            user.name = seed.name
            user.email = seed.email
            user.role = seed.role
        users.append(user)
    return users


def seed_knowledge_bases(db: Session, tenant: Tenant, departments: dict[str, Department]) -> list[KnowledgeBase]:
    items: list[KnowledgeBase] = []
    for seed in KNOWLEDGE_BASES:
        department = departments[seed.department_code]
        kb = db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == tenant.id,
                KnowledgeBase.name == seed.name,
            )
        )
        if not kb:
            kb = KnowledgeBase(
                tenant_id=tenant.id,
                department_id=department.id,
                name=seed.name,
                description=seed.description,
            )
            db.add(kb)
            db.flush()
        else:
            kb.department_id = department.id
            kb.description = seed.description
        items.append(kb)
    return items


def print_summary(tenant: Tenant, departments: dict[str, Department], users: list[User], kbs: list[KnowledgeBase]) -> None:
    print("测试数据初始化完成")
    print(f"tenant: {tenant.id} | {tenant.name}")
    print("departments:")
    for code, dept in departments.items():
        print(f"  - {code}: {dept.id} | {dept.name}")
    print("users:")
    for user in users:
        print(f"  - {user.sso_id}: {user.id} | {user.role} | dept={user.department_id}")
    print("knowledge_bases:")
    for kb in kbs:
        print(f"  - {kb.name}: {kb.id} | dept={kb.department_id}")


def ensure_platform_tables(db: Session) -> None:
    # Defensive creation for environments where migration may not have run yet.
    db.execute(text("SELECT 1"))


def main() -> None:
    engine = create_engine(settings.sync_database_url)
    with Session(engine) as db:
        ensure_platform_tables(db)
        tenant = get_or_create_default_tenant(db)
        departments = seed_departments(db, tenant)
        users = seed_users(db, tenant, departments)
        kbs = seed_knowledge_bases(db, tenant, departments)
        db.commit()
        print_summary(tenant, departments, users, kbs)


if __name__ == "__main__":
    main()
