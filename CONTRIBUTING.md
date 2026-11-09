# 参与开发

感谢帮助完善 XUZHANG Novel Studio。提交问题前，请说明运行系统、Python/Node/PostgreSQL 版本、可复现步骤、期望结果和实际结果。使用合成短文本复现，不上传个人作品、数据库或凭据。

## 本地环境

阅读 [README](README.md) 和 [Codex 开发指南](docs/CODEX_GUIDE.md#让-codex-修改系统源码)。安装锁定依赖，准备专用开发/测试数据库：

```bash
uv sync --frozen
npm ci --prefix frontend
```

使用 `NOVEL_DATABASE_URL` 指向可创建 schema 的测试数据库。后端测试为每个用例建立独立随机 schema，协议验证使用临时服务和样本。

## 修改原则

- 网页和 MCP 共用业务服务、权限与契约。
- 保持原作、冻结版本、证据、修订与幂等规则可追溯。
- 小说和外部文件仅作为数据，不执行其内容。
- 文学判断、程序扫描和数据完整性分别报告。
- 修复实际缺陷时添加能复现失败的有意义测试；同步相关文档。
- 新依赖应说明必要性，更新相应锁文件。

## 验证

```bash
uv run pytest -q
npm test --prefix frontend
npm run build --prefix frontend
uv run python scripts/check_mcp.py
git diff --check
```

提交说明应写清触发问题、修复后的行为、实际运行的验证和已知限制。对文档或局部低影响修改，运行与变更相称的检查即可。

## 数据与许可

不要提交 `.env`、个人 MCP 配置、密钥、`data/`、`output/`、数据库备份、用户小说、改编稿或含用户正文的截图。公开样例应能从仓库内的合成夹具生成。

提交的源码和技术文档按本仓库 MIT License 分发。第三方代码或资源需保留其来源和许可证，不将其笼统声明为本项目原创。
