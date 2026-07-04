# Training Agent Web Deployment Guide

## 1. 部署目标

面向生产部署 `web` 前端（Next.js），覆盖：

- Node 运行模式部署
- Nginx 反向代理
- 环境变量管理
- 灰度发布与回滚

## 2. 架构建议

- `Nginx`：统一域名入口、TLS、缓存静态资源
- `Next.js`：`next start` 方式运行
- `Backend API`：独立域名或同域 `/api` 转发

## 3. 环境变量矩阵（建议）

最少配置：

- `NEXT_PUBLIC_API_BASE_URL=https://your-api.example.com`

按环境拆分：

- `.env.development`
- `.env.staging`
- `.env.production`

## 4. 构建与启动

1. 安装依赖

```bash
npm ci
```

2. 构建

```bash
npm run build
```

3. 启动

```bash
npm run start
```

默认端口 `3000`，可通过 `PORT=3000` 显式指定。

## 5. Nginx 参考配置（Web）

```nginx
server {
    listen 80;
    server_name your-web.example.com;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

如要同域转发后端 API，可增加：

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
}
```

## 6. 灰度发布建议

1. `staging` 先验证关键链路：
   - 登录
   - 会话创建与消息收发
   - 附件上传
   - 飞书/Drive 导入
   - PPT/PDF 任务进度展示
2. 生产通过权重路由切流量：
   - 10% -> 30% -> 100%
3. 关注前端错误日志和接口失败率

## 7. 回滚策略

推荐保留最近两版构建产物目录（如 `releases/yyyymmdd-hhmm`）：

- 回滚时直接切换软链接并重启 `next start` 进程

示例（概念）：

```bash
ln -sfn /srv/web/releases/<last_stable> /srv/web/current
pm2 restart training-agent-web
```

## 8. 进程管理建议

可使用 `pm2` 或 `systemd`。

关键点：

- 自动拉起
- 启动前校验 `.env.production`
- 标准输出与错误日志分流

## 9. 发布检查清单（建议）

- `NEXT_PUBLIC_API_BASE_URL` 指向正确环境
- 与后端版本接口一致
- 浏览器缓存策略正确（静态资源 hash）
- 新增页面和弹窗在移动端/桌面端可用
