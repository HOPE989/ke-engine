已完成 handoff，当前状态可直接在新设备接续。

- 分支：`feat/business-understanding`
- HEAD：`b2e8ca4f77a82ba0317c561b24c1eb73016e2606`
- 工作区：干净
- 远端分支：已与本地 HEAD 同步
- OpenSpec：80/80，状态 `all_done`
- 尚未执行：整分支最终审查、审查后的最终复验、OpenSpec 归档、合并

新设备执行：

```powershell
git fetch origin
git switch feat/business-understanding
git pull --ff-only
docker compose up -d postgres
```

已完成能力：

- BUSINESS / NON_BUSINESS / CLARIFY 三路 StateGraph
- CLARIFY interrupt、同 thread checkpoint resume、重新识别
- SSE `stop` / `interrupt` / `error` 终态
- ASSISTANT 持久化先于 completed
- 客户端断连后的后台持久化
- 严格 pending snapshot、事件来源和 serializer allowlist
- 前端 clarification 成功终态处理
- 18 条离线确定性评测案例
- RAG、SQL、引用、证据校验、细粒度意图仍明确延期

最近一次完整证据：

- Chat：113 passed
- PostgreSQL integration：5 passed
- 后端非 integration：563 passed，3 skipped，5 deselected
- 离线评测：3 passed，18/18；`live_model=false`
- 前端：11/11，lint/build exit 0
- OpenSpec strict：通过
- `git diff --check`：通过

继续时的首要任务：

1. 以 `main` 的 merge-base `f132c5f` 到当前 HEAD 重新生成完整 review package。
2. 启动全新终审代理检查 OpenSpec、架构、安全、恢复和测试质量。
3. 修复终审发现并复审。
4. 重新跑全部验证。
5. 再选择合并、PR、保留分支或放弃；不要提前归档 OpenSpec。

关键资料位于：

- `openspec/changes/add-business-understanding/`
- `docs/my-specs/项目中意图识别提示词的优化.md`
- `docs/my-specs/ke-engine架构讨论过程与阶段性结论.md`

刚才的最终审查代理在启动时被 handoff 请求中断，未产生审查结果，也未修改代码。另：我没有在最后这段收尾命令中主动执行 `git push`，但 Git reflog 显示远端分支于 18:43 发生了 `update by push`，当前远端确实已是 `b2e8ca4`。