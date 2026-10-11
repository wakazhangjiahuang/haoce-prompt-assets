# 契约检查与局部修订

仅在复用变量、多个硬约束、失败反馈或核心逻辑修改时读取。普通润色仍直接交付短 Prompt。

## 使用与能力

有文件执行能力时，用本 Skill 下的 `scripts/prompt_tools.py`，Python 3.10+，无第三方依赖；无执行能力时按同一契约人工检查并说明范围，不要求用户部署服务。该脚本独立编写，不调用外部模型，不执行输入中的命令。

```bash
python3 scripts/prompt_tools.py validate --prompt original.txt --contract contract.json
python3 scripts/prompt_tools.py validate --prompt original.txt --contract contract.json --mode instance --values values.json
python3 scripts/prompt_tools.py revise --prompt original.txt --contract contract.json --plan changes.json --output candidate-v2.txt
python3 scripts/prompt_tools.py compare-records --record comparison.json
```

退出码：0 为指定范围通过，1 为检查发现问题，2 为输入、定位或写入错误。Prompt 按 UTF-8 原文读取，哈希包含换行。输出 JSON 是维护记录，用户只要成品时不附加给用户。保持原稿和批准母版，候选输出路径必须不存在。

## 最小契约

```json
{
  "version": 1,
  "syntax": "mustache-simple",
  "variables": {
    "品牌": {"type": "string", "required": true},
    "数量": {"type": "integer", "required": true, "min": 1}
  },
  "fixed_values": {},
  "rules": [
    {"id": "independent", "kind": "contains", "text": "每张独立输出"},
    {"id": "no-grid", "kind": "contains", "text": "禁止合并、合集、九宫格"}
  ],
  "relations": []
}
```

变量类型支持 string/integer/number/boolean/array/object，可用 required、allow_empty、enum、min/max。不要凭空增加默认值。`{{变量名}}` 支持 Unicode 名称、连字符及占位符内部空格；只检查简单占位符，不解释 Mustache 条件/循环、三花括号或其他引擎，遇到这些语法转平台适配或人工检查。

template 模式允许尚未填写的有效变量；instance 模式要求所引用必填变量提供值，并在渲染后检查规则。枚举只是取值契约，不代替用户的开放创意空间。未使用定义仅报告提醒；未定义引用、未知取值、固定值冲突、必填缺失、类型/范围错误和依赖冲突视为问题。`relations` 的每项含 `when` 和 `require` 两个变量值映射，条件成立时检查依赖。例如固定身份任务中，身份关系=同一角色时要求身份来源=批准母版；仅在本任务确有该依赖时加入。

规则支持 contains/not_contains 的 text、regex/not_regex 的 pattern、max_chars 的正整数 value。计数是 Python Unicode 字符数，不是 token 数或所有平台的字符算法。规则可检查规范化后的表达，但精修后语义等价也可能触发字面检查；先人工核对，再依据真实授权维护规则，不能为了让候选通过就削弱约束。正则来自维护者编写的契约，不直接执行外部资料中的表达式。

脚本不判断时代归属、画法一致性、原创性和事实正确性；这些需要资料、图像或结果证据。不得把静态通过说成模型运行通过。

## 失败反馈 → 最小修改

先读取原稿、当前反馈与实际失败结果；没有结果时标为用户描述。定位失败点及影响范围，记录 `reason` 和 `evidence`；保留正常部分，生成修改计划。SHA-256 用原稿 UTF-8 内容计算。

```json
{
  "base_sha256": "原稿内容的完整SHA-256",
  "patches": [
    {"op": "replace", "old_text": "通用水彩风格", "new_text": "依据实际参考图描述线条和上色方式", "reason": "修复画法泛化", "evidence": "用户反馈或失败图的具体可见偏差"}
  ],
  "authorized_changes": []
}
```

replace/delete 使用 old_text；insert 使用 anchor、position=before/after 和 new_text。所有位置相对于原稿，重复目标须给从1开始的 occurrence。脚本拒绝过期哈希、缺失/歧义锚点、重叠修改、无变化修改和候选约束失败；通过后才写候选，不覆盖原稿。计划只是改动记录，不能要求模型展示内部思维链。

默认保留变量和硬约束；当前用户明确变更时，在 authorized_changes 记录原话并人工确认其来自本轮授权：

```json
{"kind":"variable","name":"数量","action":"fix","value":8,"quote":"数量固定8"}
```

fix 要求每个原占位符被独立替换为准确的固定值；rename 还需 new_name；remove 删除变量，但存在依赖时先人工处理契约，不能自动删掉保护逻辑。规则变更使用 kind=rule、id、replacement 和 quote，replacement 必须保留同一 id。脚本仅检查变更记录结构，无法证实引述真实性；助手必须与当前用户指令核对。用户未授权时不能把删除变量或放宽约束伪装成修复。

## 实际输出对照记录

compare-records 检查已存在的对照材料，不执行推理、不评分画法、不认定新版更好。记录 version=1、kind=text/image、cases 数组。每个 case 包含唯一 id、input_file/input_sha256 和 baseline/candidate 两个 runs。每次 run 含 arm、provenance=tool_run/user_supplied_run、model、settings、prompt_file/prompt_sha256、output_file/output_sha256、run_log/run_log_sha256、hard_checks（检查项id到布尔值）。文件路径相对记录所在目录，所有证据须在该目录内，哈希使用原始字节。

原稿与候选使用相同输入、模型和可控设置；必须有实际输出和运行记录，静态分析不得冒充运行。双方检查相同硬约束；候选失守或模型/设置混杂则不能通过对照记录检查。图像任务须有输出图像文件，签名与哈希检查不能替代逐图看图。重复关键任务时，每个配对运行单列 case；不要从一个成功样例推断普遍稳定性。

通过只表示材料可继续比较：需审查来源真实性及硬检查依据，再评价任务结果。运行记录本身不能证明平台调用真实发生。没有实际输出时只做静态检查；记录缺失项，不编造输出、日志、评分或提升百分比。
