# 地点查询工作台

高德搜索原始地址，DeepSeek 辅助筛选。输入一行一个地点名称，核对候选后复制地址或导出 CSV。

默认使用清晰的浏览器界面：浅灰背景、白色圆角卡片、蓝色强调色，支持小屏幕和浏览器缩放。Python 服务只监听本机地址，不需要部署网站。

## 需要接入哪些 API？

| 功能 | API | 是否必需 |
| --- | --- | --- |
| 搜索地点和原始地址 | 高德地图 **Web 服务 API**，使用自己的高德 Key | 必需 |
| AI 候选筛选 | DeepSeek 或其他兼容 Chat Completions 格式的 AI API | 可选 |

不启用 AI 时也能查询、人工勾选、复制和导出。软件不提供免费共享 Key；请自行在服务提供方申请并填写 API Key，额度和费用按各自账号计算。

## 启动

需要 Python 3.10 或以上版本。查询功能只使用 Python 标准库，无需安装第三方依赖。

- Windows：双击 **启动地址查询.cmd**，浏览器自动打开。使用过程中保留启动窗口，关闭窗口即可退出。
- 其他系统：运行 `python -X utf8 web_app.py`。
- 界面中的「查看示例」使用虚构名称与地址，不发送 API 请求。

## 使用

1. 点击「连接设置」，填写高德 **Web 服务** Key。可在[高德开放平台](https://lbs.amap.com/api/webservice/create-project-and-key)申请。
2. 粘贴地点名称，一行一个；每批最多 500 个，自动去重。填写城市可减少同名地点，留空查全国。
3. 点击「开始查询」。展开候选，勾选需要保留的地址；每个名称可多选。使用筛选标签查看已勾选、待处理或请求失败的名称。
4. 点击「复制勾选地址」或「导出 CSV」。复制按完整地址去重；CSV 每个选中地点一行，未选中的名称地址留空。

停止会保留已取得结果。「重试失败项」仅重查未完成的名称，沿用本批城市，保留成功结果和人工勾选。已经人工勾选的 AI 失败项不会被重试覆盖。

## AI 辅助筛选

默认使用 [DeepSeek API](https://platform.deepseek.com/)。在「连接设置」填写 AI 服务的 **API Key、接口完整地址、模型名称**，然后在查询区域勾选「AI 辅助筛选」。

也可以使用其他 AI 服务，要求兼容 **Chat Completions 请求/响应格式**，支持 `response_format: {"type":"json_object"}` 与 `max_tokens` 参数，并能完整返回 JSON。不是所有 AI API 都兼容；不兼容时工具会显示失败并保留高德候选供人工核对。

默认接口地址是 `https://api.deepseek.com/chat/completions`。其他服务需填写其文档中的完整接口地址（包括 `/chat/completions` 路径）和实际可用模型名称。仅填写网站首页或替换 Key 不能切换服务。接口需使用 HTTPS，且不能在地址中夹带 Key；切换接口后需填写对应服务的 Key。

- AI 只从高德返回的候选中筛选，不新增或改写地址。
- 估计匹配度 ≥90%、无待核对标记且有详细地址时，自动勾选。
- 60–89% 或存在身份歧义的候选留空待人工确认；低分候选不自动选择。
- 分数是 AI 估计，未经正确率校准；自动选择的地点仍需核对。
- 启用后，输入名称、城市及候选名称、地址和类型会发送至你配置的 AI 服务，并按其 API 用量计费。高德的服务权限、额度及费用以自己的控制台为准。

## Key 与数据

- Key 输入框默认隐藏。浏览器不使用 localStorage 或 IndexedDB 保存 Key。
- 不勾选「在本机记住」，Key 只在当前程序会话中使用；勾选后会保存到本机 `config.json` / `ai_config.json`，为明文文件。取消勾选并查询一次，会移除配置文件中的 Key。
- 高德支持环境变量 `AMAP_KEY`；默认 DeepSeek 支持 `DEEPSEEK_API_KEY`。其他服务可使用 `AI_API_KEY`、`AI_ENDPOINT`、`AI_MODEL`。空 Key 输入框可复用相同接口的本机配置或当前会话 Key，服务不会把已保存 Key 返回给浏览器，也不会把旧接口的 Key 自动发送到新接口。
- `.gitignore` 排除了实际配置、环境文件、查询导出、日志和缓存。示例配置只有空 Key。
- 发布版本不包含真实工作清单、历史查询结果、个人本机路径或原项目 Git 历史。
- 本机服务校验访问来源和会话令牌，不开放局域网访问。访问日志不记录查询名称或 Key。页面刷新会清空浏览器中的查询结果，重要结果请先导出。

## 查询边界

高德搜索最多取第一页 25 个候选。「未找到」表示本次搜索未返回候选，可尝试简称或调整城市。地图地点地址与工商注册地址可能不同。

临时网络故障最多尝试 3 次。权限、Key 或额度错误会暂停本批；连续 3 项请求失败也会暂停。AI 出错时保留高德候选供人工选择。重试可能增加 API 调用次数。

网络默认直连高德和所配置的 AI 服务，忽略系统 HTTP/HTTPS 代理设置，不修改系统代理或关闭代理软件。

## 命令行

```powershell
$env:AMAP_KEY = 'YOUR_AMAP_WEB_SERVICE_KEY'
python -X utf8 amap_lookup.py --city 广州 "示例文化创意园"
python -X utf8 amap_lookup.py --city 广州 --input names.txt --output addresses.csv
python -X utf8 amap_lookup.py --ai --city 广州 --input names.txt --output addresses.csv
```

输入文件为 UTF-8 文本，一行一个名称。命令行全部自动匹配时退出码为 0，否则为 1。

备用 Tk 桌面界面可运行 `python app.py --desktop`，需要 tkinter。默认浏览器版直接运行 `web_app.py`，不需要 tkinter。

## 验证

```powershell
python -X utf8 -m unittest discover -s tests -v
```

测试使用模拟响应与虚构地点，不调用真实付费接口。覆盖地址匹配、AI 约束、重试、候选选择、导出以及本机浏览器服务的访问控制与批量查询流程。

API 参考：[高德地点搜索](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch)、[DeepSeek API](https://api-docs.deepseek.com/api/create-chat-completion/)。
