# A股观察站：可部署项目

## 状态（请先阅读）

这是可部署的网页与发布脚本，**不是已经在用户账号上创建好的仓库或运行中的金融服务**。
初始公开数据为空。此前聊天附件中的行情、宏观和新闻没有在本轮重新核验，所以不复制到新的公开网站。界面明确显示缺少数据，不将旧闻、模拟数字或浏览器刷新时间冒充最新市场信息。

## 一次执行建仓库和发布

需 Python 3.10+ 与官方 GitHub CLI (`gh`)。Windows 可用 `winget install --id GitHub.cli --exact` 安装 CLI；macOS 可用 `brew install gh`。请从官方渠道安装 Python。安装后重新打开终端。

解压后在本目录运行：

```sh
python deploy.py
```

Windows 也可双击 `deploy.cmd`。未登录 CLI 时，程序会使用 `gh auth login --web --scopes workflow` 打开官方浏览器授权；在你的设备上完成，不将密码、设备码或令牌发到聊天中。凭证由 GitHub CLI 管理，本脚本不读取浏览器登录信息，也不输出令牌。CLI 授权范围由 GitHub 官方页面列明，不等于只读 ChatGPT 连接。

脚本将使用 `gh api user` 返回的当前账号，在个人账号下创建 **公开** 的 `a-share-brief` 仓库，上传白名单内的13个文件、设置 GitHub Pages（workflow）、运行发布，再检查网站 HTTP 200 和项目标记。只创建这一项目，不修改个人主页，不删除仓库，不强推，不创建组织或购买服务。

同名仓库已存在时默认停止，不覆盖。只有由同一脚本创建且有本地 `.deploy-state.json` 匹配仓库数字ID的中断部署，才可安全继续。已上传后再次执行只复查，不自动覆盖后续工作。更换名称使用 `python deploy.py --name another-project`。

权限、网络或Actions失败会明确报错；不会把“已上传”当成“已上线”。成功与否写入本地 `deploy-result.json`，该文件不上传。`--dry-run` 仅列出将发布的文件，无需安装gh、不会访问网络。

已有CLI凭证但缺少 workflow scope 时，GitHub会拒绝写入工作流。仅在官方授权流程中通过 `gh auth refresh -h github.com -s workflow` 补充权限后重试；不要把令牌贴进网页或聊天。账号/组织策略也可能要求人工批准Pages或Actions。

## 本版功能和边界

| 已写好代码 | 未接通 / 未在真实账号测试 |
|---|---|
| 手机与桌面网页、日期/09点/14点切换、来源与条件分析模块 | 真正的 GitHub 仓库和外网网址 |
| 浏览器每60秒读取站点JSON（打开网页时） | 可靠A股行情、新闻采集、AI研究生产服务 |
| 部署脚本、Pages工作流、失败状态提示 | ChatGPT定时任务向网站写入 |
| 已生成报告的校验、不可覆盖历史、来源引用格式检查 | 手机或邮件推送、行情触价检测、账户回撤控制 |

每60秒刷新仅重新读取服务器文件，不会生成报告，不是实时行情，不保证成交。

## 接入真实报告后的自动发布（默认关闭）

`.github/workflows/pages.yml` 中已写入 UTC 01:00 / 06:00（北京时间09:00 / 14:00），以及北京时间08:07至22:07每小时检查报告源。
**计划任务默认跳过**，除非仓库 Variable `ENABLE_DATA_UPDATES` 设置为字符串 `true`。没有报告生产服务时不要开启，以免空跑和误解。

已有经过验证并可公开展示的研究报告生产端后，把它的**无账号密码的公开HTTPS JSON地址**设置为仓库Variable `REPORT_BUNDLE_URL`，测试手动运行成功，再开启定时。生产端采用 `site/data/latest.json` 的 schema_version=2。`scripts/update.py`只是导入生产好的结构化报告，**没有实现新闻抓取、行情采购、LLM分析或通知发送**。

校验要求：完整ISO时间含时区，引用ID存在，每个数值行情有来源和时点，新闻有发布时点，信息不得晚于报告截止时间，已有报告/来源ID不得被悄悄改写；修订请用新ID。缺失数据用空数组而不是编造0。真实金融内容、授权和重分发许可由生产端核验，结构检查不能证明消息为真。

导入失败不覆盖原报告；发布“获取失败/覆盖中断”状态，之后将Actions标为失败。`latest.json.updated_at` 不因空跑变新。GitHub计划任务可能延迟或丢弃，长时间无活动可能停用，不适合唯一的紧急风险通道。Push/聊天定时任务不会因网页上线自动接通。

## 公开分享

网站与仓库内容是公开的，未提供登录验证。不要放个人持仓、成本、姓名、邮箱、账户数据、新闻订阅密钥或API密钥。robots noindex仅请求搜索引擎不收录，不是访问控制。
普通静态网站不需要购买服务器或域名；数据、模型与外部通知服务的费用及授权需另外确认，本脚本不购买或开通付费服务。

## 本地测试

```sh
python -m unittest discover -s tests -v
python deploy.py --dry-run
python -m http.server 8000 --directory site
```

随后在浏览器打开 http://localhost:8000 。直接打开HTML也能看空状态，网络读取只在HTTP/HTTPS模式启用。

## 官方参考

- GitHub CLI 登录：https://cli.github.com/manual/gh_auth_login
- CLI安装：https://github.com/cli/cli#installation
- Pages自定义工作流：https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- Pages API：https://docs.github.com/en/rest/pages/pages
- Git仓库API：https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user
- Git树API：https://docs.github.com/en/rest/git/trees
- 定时任务限制：https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- ChatGPT GitHub只读连接：https://help.openai.com/en/articles/11145903-connecting-github-to-chatgpt

## 本轮验证记录

16项本地单元测试通过；已检查手机/桌面空状态、版本切换、转义不可信文本和历史报告提示。GitHub创建/写入仅使用模拟接口测试，未连接真实账号执行。浏览器策略阻止localhost请求，因此未完成真实HTTP读取端到端测试，未尝试绕过。不存在已部署网址或已运行的实时行情/推送承诺。详见qa-results.json。
