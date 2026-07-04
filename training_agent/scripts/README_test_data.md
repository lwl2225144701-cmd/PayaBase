# 测试数据脚本使用说明

## 目标

这两个脚本用于快速构建和清理权限测试环境。

- `init_test_data.py`：初始化部门、测试账号、知识库
- `reset_test_data.py`：清理这批固定测试数据

## 初始化脚本

```bash
cd training_agent
python scripts/init_test_data.py
```

脚本会创建：

- 3 个部门：研发部、销售部、人事部
- 1 个超管
- 3 个培训管理员
- 4 个普通用户
- 3 个部门知识库

## 清理脚本

```bash
cd training_agent
python scripts/reset_test_data.py
```

清理范围只包含这批固定测试数据：

- 固定 `sso_id` 的测试账号
- 固定部门编码：`RD`、`SALES`、`HR`
- 固定知识库名称：研发知识库、销售知识库、人事知识库

## 推荐使用顺序

1. 先执行清理脚本
2. 再执行初始化脚本
3. 登录并验证权限

## 登录 code

```text
admin
training_admin_rd
training_admin_sales
training_admin_hr
user_rd_01
user_rd_02
user_sales_01
user_hr_01
```

## 注意

当前脚本只初始化组织、账号和知识库，不会自动上传测试文档。  
如果你要做完整回归，还需要再向每个知识库补测试文档。
