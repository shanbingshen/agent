# Deployments 目录

`deployments/` 保存部署相关配置和基础设施片段。

## 规则

- Compose、容器和环境变量变更应同步 README 或 `.env.example`。
- 改动 Compose 后运行 `docker compose config`。
- 不提交真实 token、密码、证书或客户私有配置。
