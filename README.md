# 浩策 Prompt 资产库 · v0.9.0

配合“Prompt 优化器”使用，保存自有模板、变量契约、失败案例、候选版本与验证证据。

## 创建与上传

1. 在 GitHub 账号 `wakazhangjiahuang` 下创建 **Private** 仓库，名称：`haoce-prompt-assets`。
2. 解压交付的 ZIP。进入 `haoce-prompt-assets` 文件夹，把里面的文件和目录上传到仓库根目录；不要多套一层同名文件夹。默认分支建议 `main`。
3. 提交后把仓库地址发给 Prompt 优化器，要求核对 `KB-MANIFEST.json` 及相关入口。确认可读取后，才记录为已接入；此包本身不创建远端仓库、不启用长期记忆或服务。

## 入口

先读 `KB-MANIFEST.json`，按任务读取所需文件。日常优化无需下载或全仓扫描。

| 目录 | 内容 |
| --- | --- |
| templates | 插画系列、无缝系列的自有变量化起始模板 |
| variables | 配套契约；输出规格无固定默认值 |
| cases | 局部画法修订、授权固定数量的原稿与候选示例 |
| evals | 本次实际维护测试及静态修订记录，分清验证范围 |
| sources | 上游固定版本与上传包身份核实记录 |
| scripts / tests | 离线校验、锚点修改、对照记录检查及回归测试 |

## 使用工具

Python 3.10+，无第三方依赖。在仓库根目录运行：

```bash
python3 scripts/prompt_tools.py validate --prompt templates/illustration-series.txt --contract variables/illustration-series.contract.json
python3 scripts/prompt_tools.py validate --prompt templates/seamless-series.txt --contract variables/seamless-series.contract.json
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

template 模式允许动态输入留空；执行实例需按契约填写值，用 `--mode instance --values values.json` 检查。`cases` 内有修改计划示例。已有 candidate 文件受保护；重跑 revise 时使用一个新的 output 路径。更多格式说明见 `scripts/contract-tools.md`。

## 版本与质量

示范模板状态为 `starter_template`，案例候选为 `candidate_static_checked`，不是已批准生产母版。只有真实用户批准或已有明确授权的批准标准满足后，才在入口记录母版；候选与母版分开，保留原稿及修改原因。

工具通过不保证实际模型效果。语义、事实、时代风格、画法及原创性需对应资料和输出证据；图像效果评价必须有生成图。`compare-records` 只检查已有材料的完整性、哈希和对照条件，不调用模型，不宣布效果提升。本次维护记录不含实际出图效果测试。

GitHub 连接的读取和写入能力分别核实；读取成功不等于提交成功。保存需要实际提交证据。未接入或访问失败时，Prompt 优化器仍可使用自身工具完成本次工作。

## 来源

参考项目：<https://github.com/linshenkx/prompt-optimizer>，固定提交见 `sources/upstream-lock.json`。
该上游使用 AGPL-3.0-only。本包脚本、模板和任务规则独立编写，未复制上游源码或模板；本包没有把上游工程重新授权，也不包含部署的 MCP 或模型密钥。
