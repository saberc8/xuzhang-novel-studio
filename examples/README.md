# 合成演示样本

演示小说《雾港来信》定义在 `backend/app/demo.py`，可在本机生成一个8章的 EPUB，供上传和工作流测试：

```bash
uv run python scripts/make_demo.py
```

输出为 `examples/雾港来信.epub`，已被 Git 忽略。该样本和测试用短文本随源码按 MIT License 提供，不依赖第三方小说、个人原著或在线下载。

测试直接从合成夹具生成数据，CI 不需要任何真实小说文件。用户上传或自行改编的作品保留在本机数据目录，其许可由相应来源与授权决定。
