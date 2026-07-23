# 迁移运行手册

每个模块迁移后依次运行：受影响的 pytest、完整 pytest、Ruff、前端 lint/build 和本地 smoke test。更新 `AGENTS.md`、`README.md` 与本目录的迁移记录后才能进入下一模块。

发生问题时，Gateway 仍可使用 `arthra.agent` 和 `IndustrialDataService` 的兼容实现；不得通过删除审计、安全或控制测试恢复构建。
