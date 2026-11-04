# GrokArm — Track 04: Voice Control × UR3e

> **Hackathon 项目资料与执行清单**  
> 活动：Grok Hackathon at the Museum · Pavia, Italy · 2026-11-04 至 2026-11-05  
> 文档版本：v1.0（整理日期：2026-11-04）  
> 赛题：**Track 04 — Voice Control**  
> 团队被分配设备：**n1-UR3e（Universal Robots UR3e）**，由现场设备消息确认  
> 项目工作名称：**GrokArm — From Natural Language to Safe Physical Action**  
> 状态说明：**[官方]**＝活动官网明确要求；**[现场]**＝活动现场屏幕或设备分配消息；**[建议]**＝团队实施建议；**[待确认]**＝需要向工作人员/导师核实的信息。

## 0. TL;DR

我们要用 **Grok Voice + function calling + Universal Robots UR3e** 制作一个真实、可解释、可安全验证的语音机械臂助手。用户用自然意大利语表达需求；Grok 从 **3–5 个预定义技能**中选择合适操作、必要时澄清、**每次运动前取得语音确认**；程序向 UR3e 发出经过现场验证的技能命令，读取执行状态并报告结果。**任何时候都应有可用的停止机制**，实际紧急安全防护不能依赖 LLM 或普通网络指令。

**核心验收：[官方]** 评委现场给 **5 条新的命令**（含歧义命令与一次中途 “stop”），每条须匹配技能、运动前确认并最终报告；官方评测指标还包括 **10 条命令的正确执行数量**、话语结束到开始运动的延迟、歧义/不可达命令处理、任意时刻停止的可靠性。

**最大待确认事项：** 官网 Track 04 指定 **Arm 3（无摄像头）**；团队收到的是 **n1-UR3e**。目前未得到它们是同一站位的明确映射，请先请工作人员确认，**不要直接假设 n1-UR3e = Arm 3**。

---

## 1. 活动基本情况与全部通用要求

### 1.1 基本信息

| 项目 | 内容 | 依据 |
|---|---|---|
| 活动名称 | Grok Hackathon at the Museum | [官方主页](https://pavia.grokbot.it/) |
| 日期 | **2026-11-04（周三）—11-05（周四）** | [官方主页](https://pavia.grokbot.it/) |
| 地点 | Ctrl+Alt Museum，Via Gragnani 18，27100 Pavia PV，Italy | [官方主页](https://pavia.grokbot.it/) |
| 时间 | 官网标注为 **Rome time / CET** | [官方日程](https://pavia.grokbot.it/) |
| 团队人数 | **4–6 人**（4 人才算组成团队；组队登记及锁定规则详见官网） | [官方主页](https://pavia.grokbot.it/) |
| 资源 | 提供 Grok API credits；自带笔记本；活动人员支持硬件 | [官方主页](https://pavia.grokbot.it/) |
| 评审 | 官方通用评分 rubric **尚未公布**；Track 04 自有具体指标 | [主页与 Tracks](https://pavia.grokbot.it/tracks) |

### 1.2 重要时间线

| 时间（意大利当地） | 安排 | 来源 |
|---|---|---|
| **11/04 09:00** | Kick-off / hardware tour / 组队与开始开发 | [官方] |
| 11/04 10:00 | Cobots、机器人狗、无人机等介绍 | [官方] |
| 11/04 夜间 | 可继续开发，场地通宵开放 | [官方] |
| **11/05 10:00** | Grok Models / API / Voice / Bots 主题分享 | [官方] |
| **11/05 16:00** | **Minimum Demo 必须可展示；现场屏幕另写 “Video demo deadline (all tracks)”** | [官方 Tracks] + [现场屏幕] |
| **11/05 16:00–19:00** | Project evaluation and pitches | [官方] |
| 11/05 21:00 | Awards ceremony | [官方] |

> **[待确认]** 视频 Demo 的具体时长、文件格式、上传入口，以及是否必须在 **16:00 前**上传：现场屏幕明确写了 “Video demo deadline (all tracks)”，但活动网页对上传方式没有详细说明。不要用“有现场演示”替代视频交付确认。现场安排可能更新，以工作人员最新指示为准。

### 1.3 所有赛道的通用硬性要求（Official Rules for All Tracks）

来自 [官方 Tracks 页底部规则](https://pavia.grokbot.it/tracks)：

- [ ] **Grok 必须是产品运行的核心**（Grok API / Grok Voice / Grok Bot），不能只是表层装饰。
- [ ] **11/05（周四）16:00 前**准备好 Minimum Demo，可在**评委挑选的新案例**上运行。
- [ ] 交付一个 **代码仓库（repository）**，至少包含：
  - [ ] `README.md`
  - [ ] 所使用的数据（如可公开的测试命令、模拟数据、去敏日志/样例）
  - [ ] **至少一个与 baseline 比较的量化结果**
  - [ ] **已知局限（known limitations）**
- [ ] 机械臂与机器狗采用 **30 分钟 slots**，**必须有工作人员陪同**；非硬件时段在模拟器或已录制视频上继续开发。
- [ ] 机械臂**没有通用夹爪**：提供带 **fork（叉）、pusher（推板）和 tip（指示尖端）**的打印工具；只能托举**放在带槽托盘上的物品**。
- [ ] 只使用**公开数据、合成数据或本次活动企业提供的数据**。

**注意：** 通用评委 rubric 仍标记 “To be announced”。不要把团队自行设定的权重、目标分数或推荐 Pitch 时长误写为官方规则。

---

## 2. Track 04 — Voice Control 完整赛题要求

**官方入口：** [Track 04 — Voice Control（页面内对应章节）](https://pavia.grokbot.it/tracks#track-04-voice-control)  
如锚点失效，请到 [完整 Tracks 页面](https://pavia.grokbot.it/tracks) 搜索 `Track 04`。

### 2.1 赛题定位 [官方]

**原始问题**：能否用**自然意大利语**指挥机械臂？工业现场不懂机器人编程的使用者，应当能用免手操作召唤现有技能，但需要运动前确认与随时可用的停止机制。

**要做的系统**：一个语音助手，理解请求，从机械臂已有的 **3–5 项预定义技能**中选择动作，**请求确认 → 执行 → 汇报完成情况**。

**Grok 的角色**：
- Grok Voice：实时语音交互；
- Function calling：把意图映射为机械臂的已授权技能；
- 每次运动前获取语音确认；
- 识别用户在过程中的 `stop`，并触发停止处理。

### 2.2 输入和设备 [官方]

- **Arm 3**：Track 04 指定，**无摄像头**，为本赛道专用站位。
- 配有 **3D 打印工具**和**带槽托盘**。
- 机械臂基本技能由团队通过机械臂软件准备，官网示例：
  1. `go_to_pose` — 到已验证的预定义姿态；
  2. `indicate` — 用尖端指示；
  3. `lift_tray` — 通过工具托起带槽托盘；
  4. `put_down_tray` — 放下托盘；
  5. `push` — 使用推板推送物体。
- 使用**笔记本麦克风**输入语音。
- 官方建议资源：`xai-sdk-python` 和 `voice-agent-web`。

### 2.3 Minimum Demo — 必做 [官方]

- [ ] **评委给出 5 条未预告的新语音命令**；
- [ ] 包括至少一条**有歧义的请求**：系统必须主动**追问澄清**；
- [ ] 包括一次在机械臂执行过程中说 **“stop”**：系统必须能让机械臂停止；
- [ ] **每条指令**都要匹配到允许的 skill；
- [ ] **任何运动前**必须获取确认；
- [ ] 执行后给出**最终结果报告**（完成 / 未完成 / 拒绝与原因）。

### 2.4 评审指标 [官方]

| 指标 | 具体含义 | 推荐记录方式 [建议] |
|---|---|---|
| Correct execution | **10 条指令中正确执行的数量** | `success_count / 10`，保留逐条日志 |
| Response latency | **用户说完话 → 机械臂开始运动**的时间 | `movement_start_ts - utterance_end_ts`，统计中位数和 P95 |
| Ambiguity / reachability | 能否处理**模糊请求**及**不可达命令** | 追问、拒绝、零意外运动 |
| Reliable stop | **任意时刻停止的可靠性** | 记录触发到动作停止的延迟与失败案例；现场人员监督 |

> 官网同时提到 **5 条评委现场新命令**与 **10 条正确率统计**，两者属于不同层次的要求，**不要错误合并成“只测 5 条”或“现场一定给 10 条”**。

### 2.5 Stretch Goals — 加分项 [官方]

- [ ] 多技能顺序执行：例如“抬起托盘并移到右边”；
- [ ] 通过语音**录制新的 skill**（必须经人工审核，不等于开放任意轨迹）；
- [ ] 更多语言：意大利语为基础，英语可作为扩展。

### 2.6 明确不做（Out of Scope）[官方]

- **禁止**根据用户语音自由生成未经批准的机器人运动轨迹；
- **禁止**绕过确认直接运动。

### 2.7 共享硬件限制 [官方]

- Track 04 的 **Arm 3 无摄像头**。
- **2 个团队轮换使用**；所有机械臂使用一般为 **30 分钟一档且有工作人员陪同**。
- 非使用时段必须让**同一套命令协议**接入模拟机械臂继续开发。

---

## 3. 团队分配的硬件：n1-UR3e

### 3.1 已知信息与区分

| 项目 | 当前状态 |
|---|---|
| 机器人资产编号 | **n1-UR3e** [团队收到的现场设备消息] |
| 厂商 / 型号 | **Universal Robots / UR3e** [现场] |
| 机械臂自由度 | **6 个旋转关节** [官方厂商资料] |
| 标称负载 | **3 kg** [厂商规格，**非现场允许载荷**] |
| 标称工作半径 | **500 mm** [厂商规格，**非实际安全工作区**] |
| 教导/控制环境 | **PolyScope**（实际版本和控制器代际待现场检查） |
| 官方 Track 04 对应站位 | **Arm 3**；**尚未确认是否等于 n1-UR3e** |
| 末端执行工具 | Track 通用说明为带 fork/pusher/tip 的打印工具；**实际装配方式待确认** |
| 普通摄像头 | Track 04 官方明确**没有摄像头**，不要按视觉方案设计 |
| 控制器 IP、是否同网、是否启用 RTDE | **待现场确认** |
| URSim 对应型号/控制器版本 | **按实际 PolyScope 版本选择** |

资料：[UR3e 官方产品页](https://www.universal-robots.com/products/ur3e/)；[官方技术规格](https://www.universal-robots.com/manuals/EN/HTML/SW5_19/Content/prod-usr-man/complianceUR3e/H_g5_sections/appendix_g5/tech_spec_data.htm)。

> **安全边界：** 3 kg 负载、500 mm 半径只是厂商产品指标；不是本次现场的允许动作参数。现场目标姿态、速度、载荷、运动范围、人员隔离、工具及托盘用法，都应由硬件导师确认。**不得把模拟器的默认 `home` 关节角直接用于真机。**

### 3.2 UR3e 开发技术路线 [建议]

**首选：Python `ur_rtde`**（University of Southern Denmark / SDU Robotics 维护的 UR RTDE 库）：

- `RTDEControlInterface`：向 UR 控制器发送运动控制调用；
- `RTDEReceiveInterface`：读取关节/末端执行器位姿与状态；
- 受控预定义技能可以使用 `moveJ`/`moveL`（**仅针对已审核的轨迹**）；
- 要让执行中的运动可中止，需提前设计**异步运动 + 单独的中止入口**（例如 `stopJ` / `stopL` 的正确配对）；默认阻塞运动调用不能简单当作随时可打断；
- 对于更严格的控制器/厂商接口，配合现场工作人员确定 Remote Control 或 External Control URCap 路线。

**官方提醒：** `stopJ`/`stopL` 属于控制命令，**不是经安全认证的 Emergency Stop**。`stop` 的语音识别/网络链路不具确定实时性。物理急停、限制区域和操作人员监督必须保留。

### 3.3 真机连接前的检查 [待确认]

- [ ] `n1-UR3e` 是不是 Track 04 的 **Arm 3**，或者是否获准在该机器人上运行 Track 04？
- [ ] PolyScope 版本（5 / X）、控制器型号、软件版本？
- [ ] 工作人员是否允许队伍笔记本在指定网络访问机器人控制器？
- [ ] 是否有可用的 RTDE、Remote Control 或 External Control URCap 配置？**由工作人员操作启用**。
- [ ] 是否已存在工作人员提供的预设动作/标定姿态、托盘、叉头？
- [ ] 哪些预设技能可在演示时执行？速度/加速度/范围的允许配置？
- [ ] 如何检测运动完成、异常、Protective Stop、断连？
- [ ] 语音 `stop` 与独立安全停止机制如何分别演示？负责安全的工作人员是谁？
- [ ] 硬件 slot 的预约规则和 11/05 演示时的调度？

---

## 4. 已找到的开源代码、官方文档与可复用材料

> **状态说明：** 下列链接是已确认存在的**参考资源**，不意味着已下载到团队本地、成功运行或验证了与现场控制器的兼容性。克隆代码前检查当前提交、使用许可及依赖版本。优先参考官方文件，不要把研究 Demo 直接用于未验证的真机运动。

### 4.1 P0：立即使用 / 必须读

| 资源 | 链接 | 我们复用的部分 |
|---|---|---|
| **Track 04 官方要求** | https://pavia.grokbot.it/tracks | 完整验收条款、评分、硬件与 slots |
| **Hackathon 官方首页** | https://pavia.grokbot.it/ | 日程、地点、组队、API credits |
| **xAI `voice-agent-web`** | https://github.com/xai-org/xai-cookbook/tree/main/examples/voice-agent-web | React/TypeScript UI、FastAPI Python 后端、WebSocket、音频流、转录和 debug console |
| **该示例的 README** | https://github.com/xai-org/xai-cookbook/blob/main/examples/voice-agent-web/README.md | 启动方法、目录、API contract、环境变量 |
| **xAI Speech-to-Speech guide** | https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech | Realtime Voice API、事件及工具集成 |
| **xAI Function Calling** | https://docs.x.ai/developers/tools/function-calling | 自定义工具 schema、调用与返回 |
| **xAI Python SDK** | https://github.com/xai-org/xai-sdk-python | Grok Python SDK；**语音 Web 示例可直接使用 WebSocket，不必强行改造为 SDK** |
| **`ur_rtde` 主文档** | https://sdurobotics.gitlab.io/ur_rtde/ | UR 控制器 Python 接口 |
| **`ur_rtde` 安装** | https://sdurobotics.gitlab.io/ur_rtde/pages/getting_started/installation.html | `pip install ur_rtde` |
| **`ur_rtde` Quick Start** | https://sdurobotics.gitlab.io/ur_rtde/pages/getting_started/quick_start.html | 控制 / 接收接口，**先在仿真中测试** |
| **`ur_rtde` 异步运动与中止示例** | https://sdurobotics.gitlab.io/ur_rtde/pages/examples/basic_motion/move_async_example.html | `moveJ`/`moveL` 异步及 `stopJ`/`stopL` 的使用原则 |

### 4.2 P1：机器人模拟与控制权限

| 资源 | 链接 | 用途 |
|---|---|---|
| **URSim Desktop 1.7.3（官方）** | https://www.universal-robots.com/download/ursim-desktop/ursim-desktop-173/ | 选择 UR3e + 适配 PolyScope 版本的桌面模拟器；支持 Windows、macOS Apple Silicon、Linux（各有环境要求） |
| **`ur_rtde` Simulator / Real Setup** | https://sdurobotics.gitlab.io/ur_rtde/pages/getting_started/environment_setup.html | Docker 仿真、网络、真实机器人连接方式 |
| **UR 官方 Robot Setup** | https://docs.universal-robots.com/Universal_Robots_ROS_Documentation/kilted/doc/ur_client_library/doc/setup/robot_setup.html | Remote Control / External Control / RTDE 设置说明 |
| **UR 官方产品页** | https://www.universal-robots.com/products/ur3e/ | UR3e 产品规格与手册入口 |
| **UR 在线手册入口** | https://www.universal-robots.com/manuals/EN/HTML/MainLanding/Content/Landingpages/mainlanding.htm | 根据现场控制器和 PolyScope 版本选择匹配手册 |

**注意：** URSim Desktop 版本和机器人实际固件版本可能不同，**仿真可运行不代表真机已通过安全验证**。官网 `ur_rtde` 示例的示例 IP、关节角、移动距离**绝不能原样传给真实 UR3e**。

### 4.3 P2：类似项目（只参考架构）

| 项目 | 链接 | 可借鉴点 / 局限 |
|---|---|---|
| **LLM Robotic Arm（研究参考）** | https://github.com/cais-psu/llm-roboticarm | LLM 与机器人操作的架构思路；不是本次 Grok + UR3e 的即插即用驱动 |
| **AI Robot Arm Agent（ESP32）** | https://github.com/Skywalker1080/arm_controller | 技能/Mock/动作记录的思路；面向不同硬件，不能直接用作 UR3e 控制器 |

### 4.4 许可证与资料来源 [建议]

- 直接复用仓库源代码前，检查该仓库或所用子目录的 **`LICENSE`**、依赖许可证与保留署名条件。
- 在团队 `README.md` 的 `Credits / Open-source acknowledgements` 中明确说明复用、修改了什么。
- 不要把现场人员、场地无授权视频、API key、控制器密码、真实 IP 或不允许公开的机器人日志上传到公开仓库。
- **API key 仅放服务端 `.env`**；仓库提交 `.env.example`，不要上传 `.env`。

---

## 5. 推荐技术架构（可以直接开发）

```text
Browser / Laptop Microphone
       |
       v
React + TypeScript Voice UI
- Live transcript / debug panel
- State: Listening / Clarifying / Awaiting Confirmation
- State: Running / Stopping / Completed / Error
       |
       | WebSocket
       v
FastAPI Voice Gateway  <---->  xAI Grok Realtime Voice
       |                           (Italian speech, tool calling)
       v
Intent / Tool-Call Router
       |
       v
Dialogue & Confirmation State Machine
  [IDLE -> PROPOSED -> CONFIRMED -> EXECUTING -> DONE]
     |                 |              |
     |                 |              +--> STOPPING / FAILED
     |                 +-- explicit consent required
     +-- ambiguous / unreachable -> CLARIFY or REJECT
       |
       v
Skill Registry (only allowlisted skill IDs, no arbitrary coordinates)
       |
       v
Robot Adapter Interface (same contract)
     /                       \
MockUR3eAdapter         RealUR3eAdapter
                        (ur_rtde, staff-approved)
     \                       /
       v                   v
Execution State + Robot Feedback + Event Log
```

### 5.1 各模块职责 [建议]

| 模块 | 核心责任 | 推荐技术 |
|---|---|---|
| Voice UI | 录音、转录、状态、演示仪表板 | 复用 xAI React 示例 |
| Grok session | 意大利语理解、追问、工具意图 | xAI Realtime Voice API |
| Function router | 将 `skill_id` 等结构化工具参数送到本地 | Python / FastAPI |
| Confirmation FSM | **动作前确认，确认只对当前动作有效** | Python 状态机 |
| Skill Registry | 只允许 3–5 个审核技能，不接收原始轨迹 | Python 配置 + 白名单 |
| Robot adapter | 在 Mock 和真实 UR3e 间切换 | `ur_rtde` / URSim |
| Stop handler | 和普通指令处理分开，尽早发起受控停止 | 独立本地控制路径 + 硬件安全设施 |
| Logging & evaluation | 逐条命令结果、延迟、失败原因、baseline | JSONL / CSV + dashboard |

### 5.2 推荐预定义技能 [建议，必须现场批准]

为最短时间获得可靠 Demo，优先准备 **3 个基础技能**，最多扩展到 5 个：

1. `go_to_safe_pose` — 进入**工作人员定义**的安全位置；
2. `point_left` — 指向/移动到**工作人员示教**的左侧姿态；
3. `point_right` — 指向/移动到**工作人员示教**的右侧姿态；
4. `lift_tray` — 使用叉头托起**符合条件的带槽托盘**（只有实际验证后才启用）；
5. `put_down_tray` — 在已批准位置放下托盘（只有实际验证后才启用）。

`push` 可以作为 `lift_tray` / `put_down_tray` 的替代技能，具体依工具和工位条件决定。

**技能约束：**
- 模型只可选择 `skill_id` 和白名单内的命名参数，不可传任意六维坐标、关节角或速度；
- 对请求范围外的动作必须拒绝并解释；
- 所有动作都必须 `PROPOSED → CONFIRMED → EXECUTING`，不可从语音意图直接执行；
- 执行结果必须从**控制器状态**获得，不能由模型猜测为完成；
- 一次确认只能批准一次具体动作；多步骤序列的每次运动都应满足赛题“运动前确认”的要求；
- 断连、错误、取消、不明确反馈一律不发起新动作。

### 5.3 建议的工具接口（概念结构，**不是直接可执行的真机代码**）

```json
{
  "name": "propose_robot_skill",
  "arguments": {
    "skill_id": "point_left",
    "parameters": {},
    "user_intent": "indica la posizione a sinistra"
  }
}
```

Backend 自行校验技能是否存在、参数是否合法、机器人是否空闲/可用，并要求当前用户确认后才有资格调用技能执行层。

### 5.4 STOP 的两种含义：比赛功能 vs 工业安全

1. **比赛功能层**：持续监听 “stop / fermati / basta”；**不必等普通长句回答完成**，触发应用侧停止流程并反馈状态。需实际测量响应时间和失败次数。
2. **工业安全层**：工作人员监管、控制器安全配置和物理急停是独立且必须有效的防护。普通 Grok 语音 + Python 软件**不构成安全认证系统**。即使软件已发出 `stopJ`/`stopL`，也不代表机械臂实现了安全级紧急停止或“零延迟”。

---

## 6. Demo 设计与评价数据

### 6.1 必做 Demo（建议 2–3 分钟演示稿；**时间并非官方规定**）

1. **开场 15–20 s**：用一句意大利语介绍“自然语言 → 安全的物理动作”。
2. **正常命令**：`Indica la posizione a sinistra.` → 提议动作 → 用户确认 → UR3e 指向左侧 → 报告完成。
3. **自然语言改写**：`Puoi mostrarmi quello a destra?` → 同一技能类别，体现 Grok 不只识别关键词。
4. **歧义命令**：`Spostalo lì.` → 系统询问指代/位置，**未澄清前不运动**。
5. **STOP 展示**：在工作人员批准并准备的安全动作中说 `Fermati!` → 显示停止请求、机器人状态与停止耗时。
6. **收尾**：显示真实测试成功率、baseline 对照、已知限制；展示仓库。

**重要：** 上述命令是团队自行准备的练习案例；真正展示时应让评委输入新命令。

### 6.2 测试集最低配置 [建议]

准备 **10 条基础命令 + 一组额外边界测试**；正式分数应按照实际执行的测试集记录，不能伪造或只挑成功项。

| 类别 | 建议样本 | 预期 |
|---|---|---|
| 标准明确意图 | 3–4 条 | 正确调用技能，先确认后执行 |
| 意大利语变体表达 | 2 条 | 同意图不同措辞，仍可匹配 |
| 歧义指令 | 1–2 条 | 追问，不运动 |
| 未知/不可达/不允许操作 | 1–2 条 | 合理拒绝，无运动 |
| 语音停止 | ≥1 条（工作人员监督） | 尽早停止并读取控制器结果 |
| 取消确认 | ≥1 条 | 不执行 |
| 网络/API 异常 | ≥1 条（模拟） | Fail-closed，不启动新动作 |

### 6.3 指标与 baseline

**至少做一个量化对照是官方强制。** 对 Track 04 最有说服力的 baseline：

- **Baseline A：固定关键词/规则匹配系统**（如字面识别“left/right/home”），保持相同的技能列表；
- **Our system：Grok Voice + 意图结构化 + 歧义澄清 + 确认状态机**；
- 两者使用**同一套意大利语测试请求**；
- 测量并保存：
  - `intent_accuracy`（在明确、可执行指令上的意图匹配准确率）；
  - `valid_action_rate`（在允许的指令中正确执行数 / 总数）；
  - `unsafe_execution_count`（未确认或不可达命令错误触发的次数，目标 0）；
  - `latency_ms`（话语结束 → 开始运动）；
  - `stop_latency_ms`（停止命令结束/识别 → 实际速度趋零，注明采样方法）。

推荐 CSV 字段：

```csv
test_id,language,utterance,expected_behavior,parsed_skill,clarification,confirmed,execution_result,utterance_end_ts,motion_start_ts,stop_detected_ts,motion_stopped_ts,error
```

如果无法测得真机速度或 Stop 时间，不要编造数据；请标明 `not measured / simulation only`。

### 6.4 Q&A 重点 [建议]

| 评委问题 | 推荐用证据回答 |
|---|---|
| Why Grok, not a keyword parser? | 相同语句集上的正确率对比；展示多措辞和歧义澄清 |
| How do you prevent hallucinated actions? | Skill 白名单、严格参数校验、确认状态机、无法映射则拒绝 |
| Can the robot stop at any moment? | 展示实际停止路径、测试日志和硬件急停的独立性；坦陈语音延迟 |
| What if API/network drops? | Fail-closed、超时、状态反馈、拒绝新运动 |
| What is the biggest limitation? | 只有少量示教技能；共享硬件；语音噪音与网络延迟；非安全认证系统 |
| Can it scale to real factories? | 技能注册、权限审计、明确工业安全控制层；先不宣称已符合部署认证 |

---

## 7. 开发与团队协作安排（按优先级）

### 7.1 P0：先完成可运行最小系统

- [ ] 克隆 `xai-cookbook/examples/voice-agent-web`，跑通本地 microphone → Grok Voice → transcript；
- [ ] 创建 `MockUR3eAdapter`，可接受 3–5 个 `skill_id` 并模拟状态（**不含任意位姿生成**）；
- [ ] 实现 `propose → clarify → confirm → execute → report` 状态机；
- [ ] 实现独立的 `stop_requested` 入口和动作状态日志；
- [ ] 先用 5 条新 Italian test phrases 走完整流程。

### 7.2 P1：打通 URSim，再接现场真机

- [ ] URSim 选择 UR3e、匹配合适的 PolyScope 模拟环境；
- [ ] Mock 与 Simulator 使用一致的抽象接口；
- [ ] 先验证**状态读取**、再验证工作人员审核的示教运动；
- [ ] **真机测试必须在工作人员许可、slot 内及安全措施有效的情况下**进行；
- [ ] 真实 UR3e 只加载**已审核技能**，拒绝任何未授权轨迹。

### 7.3 P2：确保提交完整

- [ ] 10 条命令与错误场景的测试记录；
- [ ] 至少一个 **baseline 对比**及解释；
- [ ] `README.md`：安装、架构、运行模式、Demo 说明；
- [ ] `data/`：合成测试语句、去敏结果；
- [ ] `LIMITATIONS.md` 或 README 的 known limitations；
- [ ] Demo 视频（**提交入口及格式需现场确认**）；
- [ ] 演示时软件 fallback（Mock / URSim）和真机视频；
- [ ] 所有外部开源库、参考源码的 Credits。

### 7.4 4–6 人建议分工

| 角色 | 主要任务 |
|---|---|
| Person 1 — Grok Voice | Voice API、function calling、意大利语命令与澄清 |
| Person 2 — Robot SDK | URSim、`ur_rtde`、真实 UR3e 连接与技能（同工作人员协作） |
| Person 3 — Backend / Safety Logic | 技能注册、确认状态机、停止处理、错误与日志 |
| Person 4 — Frontend / Demo | 语音 UI、执行状态、实时反馈与 Demo |
| Person 5（若有） — Evaluation | Baseline、测试脚本、数据统计、README |
| Person 6（若有） — Integration / Pitch | 集成测试、录屏、展示讲稿、Q&A |

**关键路径：** 不能等拿到真机才开发；Voice / Mock / UI / Evaluation 应并行工作。

---

## 8. 推荐代码仓库结构

```text
grokarm-ur3e/
├── README.md                  # 项目介绍、运行和复现说明
├── docs/
│   ├── HACKATHON_BRIEF.md     # 本文
│   ├── ARCHITECTURE.md
│   ├── SAFETY_AND_LIMITATIONS.md
│   └── DEMO_SCRIPT.md
├── frontend/                  # 复用/改造 xAI voice-agent-web client
├── backend/
│   ├── main.py
│   ├── voice_gateway.py
│   ├── tool_router.py
│   ├── confirmation_fsm.py
│   ├── skill_registry.py
│   ├── robot_adapter.py
│   ├── mock_adapter.py
│   └── ur3e_adapter.py
├── config/
│   └── skills.example.yaml    # 无真实坐标/机密配置
├── data/
│   ├── test_commands.csv
│   ├── results_baseline.csv
│   └── results_grok.csv
├── tests/
│   ├── test_intent.py
│   ├── test_confirmation.py
│   └── test_stop_simulated.py
├── demo/
│   ├── demo_video_info.md
│   └── slides_notes.md
├── .env.example
└── LICENSE
```

> 这是**推荐目录结构**，不是已经创建好的项目，也不是官方要求的固定布局。可随团队已有仓库调整。`skills.example.yaml` 不应包含可以直接运行在未经验证的真机上的危险姿态或速度。

---

## 9. 组织者 / 硬件导师待确认问题（英文可直接发送）

1. **Is our assigned `n1-UR3e` the `Arm 3` designated for Track 04 Voice Control?**
2. Which **PolyScope version** and controller software does this UR3e use?
3. Can we access it over the local network using **RTDE / ur_rtde**, or must we use **External Control URCap** / preloaded PolyScope programs?
4. Does the robot already have **staff-approved poses, slotted trays and predefined skills**? Who approves new skills?
5. What **30-minute testing slots** are available today and tomorrow, and will a mentor be present?
6. For the **spoken STOP test**, what is the approved demonstration procedure, and what independent safety controls must be used?
7. What is the **video submission URL / file format / maximum length**? Is the deadline precisely **November 5, 16:00 CET**?
8. Is the **live pitch length** fixed, and where will the final evaluation rubric be announced?

---

## 10. Source of truth：官方来源与参考链接

**官方活动：**
- [Grok Hackathon 首页](https://pavia.grokbot.it/)
- [Tracks 及 Rules for All Tracks](https://pavia.grokbot.it/tracks)

**xAI 官方：**
- [xAI Cookbook](https://github.com/xai-org/xai-cookbook)
- [Web Voice Agent 源码](https://github.com/xai-org/xai-cookbook/tree/main/examples/voice-agent-web)
- [Web Voice Agent README](https://github.com/xai-org/xai-cookbook/blob/main/examples/voice-agent-web/README.md)
- [Realtime Speech-to-Speech](https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech)
- [Function Calling](https://docs.x.ai/developers/tools/function-calling)
- [xAI Python SDK](https://github.com/xai-org/xai-sdk-python)

**Universal Robots / `ur_rtde`：**
- [UR3e 产品页](https://www.universal-robots.com/products/ur3e/)
- [URSim Desktop](https://www.universal-robots.com/download/ursim-desktop/ursim-desktop-173/)
- [UR Online Manuals](https://www.universal-robots.com/manuals/EN/HTML/MainLanding/Content/Landingpages/mainlanding.htm)
- [UR 官方 Robot Setup](https://docs.universal-robots.com/Universal_Robots_ROS_Documentation/kilted/doc/ur_client_library/doc/setup/robot_setup.html)
- [`ur_rtde` 文档](https://sdurobotics.gitlab.io/ur_rtde/)
- [`ur_rtde` Simulator / Real Setup](https://sdurobotics.gitlab.io/ur_rtde/pages/getting_started/environment_setup.html)
- [`ur_rtde` Async Move & Stop 示例](https://sdurobotics.gitlab.io/ur_rtde/pages/examples/basic_motion/move_async_example.html)

**开源参考：**
- [cais-psu/llm-roboticarm](https://github.com/cais-psu/llm-roboticarm)
- [Skywalker1080/arm_controller](https://github.com/Skywalker1080/arm_controller)

**其他现场来源：**
- 现场议程投屏照片（团队提供）：**11 月 5 日 16:00 Video demo deadline**。
- 活动组织者的机械臂名单消息（团队提供）：**n1-UR3e — Universal Robots UR3e**。

---

**最终决策 [建议]：** 使用 **n1-UR3e** 做 **Track 04 Voice Control**，以**意大利语语音理解 + 3–5 个安全预定义技能 + 澄清 + 每次动作前确认 + 可验证的停止行为 + baseline 数据**为主线。优先确保最低 Demo 完整度，而不是增加自由轨迹或复杂硬件视觉功能。
