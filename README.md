# codex-reset-calendar

English: [README.en.md](README.en.md)

查詢 Codex「可用重置次數」各自的精確到期時間，匯出 ICS，或透過既有 Codex Google Calendar 連線建立提醒。固定腳本負責查詢與同步，不需要啟動模型生成回合；自然語言操作時，AI 對話本身仍可能消耗 Token。

這裡查的是 earned rate-limit reset credits 的到期日，與每五小時／每週使用量視窗的重置時間不同。工具不會替你使用或兌換額度。

## 支援與限制

- 第一版完整支援 Windows 10／11、Python 3.10+、PowerShell 5.1／7。
- 需要本機 Codex CLI 已以 ChatGPT 登入。API-key-only 帳號無法提供本工具需要的帳號資料。
- 查詢與 ICS 不要求 Google Calendar 連線；直接同步需要 CLI 可呼叫的 `codex_apps` Google Calendar 工具及相應權限。
- 已核對的介面基準是 Codex CLI 0.144.3；其他版本須通過 `doctor`，不承諾所有未來版本相容。
- 服務可能只提供數量或部分明細，工具會明示未知部分；不把缺漏資料當成零。
- connector 讀取成功不代表寫入或無人值守排程一定獲准。遇到登入、批准要求或結果不明時停止新增。
- macOS／Linux 未列為第一版部署與排程支援平台。

## 安裝

下載或 clone 這個 repository，進入含 `pyproject.toml` 的資料夾。所有操作只在這個 repository 內進行。

```powershell
.\scripts\Setup.ps1
.\scripts\Setup.ps1 -Apply
```

第一行只顯示計畫；第二行建立新的 `.venv`，並安裝此專案與 `tzdata`。不修改全域 Python、Codex 設定、登入或模型。若 `.venv` 已存在，安裝器停止，不覆寫。

若 PowerShell 執行原則阻擋腳本，工具不自行更改政策。可改用直接 Python 指令：

```powershell
python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

下列例子均不需要啟動虛擬環境，也不要求修改 PATH。

## 查詢與 ICS 備援

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar query
.\.venv\Scripts\python.exe -m codex_reset_calendar query --format json
.\.venv\Scripts\python.exe -m codex_reset_calendar query --time-zone America/New_York
.\.venv\Scripts\python.exe -m codex_reset_calendar export-ics --output .\reset-reminders.ics
```

預設顯示 `Asia/Taipei`，時間精確到秒並包含 UTC 對照。首次未初始化時沿用目前登入的 Codex 帳號；可用 `--expected-email` 核對預期帳號，用 `--codex` 指定 CLI 完整路徑。

ICS 只匯出目前已知、仍有效且有到期時間的 Codex 額度。部分明細可匯出，但結果會保留缺漏警告；資料互相矛盾時停止匯出。檔案包含私人、空閒、一分鐘事件及提前 60 分鐘 `VALARM`。檔案已存在時停止，請另選新檔名。

**匯出不代表已加入日曆。** 請手動匯入目的日曆並檢查時間與通知。Google Calendar 匯入 ICS 不會形成持續同步，匯入工具也可能不保留提醒設定。ICS 的 UID 與描述標記是穩定的，之後直接同步可搜尋並接管保留標記的事件。不要刪掉事件描述中的識別標記；也不要假定每一款匯入工具都會保留它。

## 綁定帳號與直接同步

先以唯讀方式檢查連線、查看預計綁定的帳號：

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar doctor --format json
.\.venv\Scripts\python.exe -m codex_reset_calendar init
```

確認後，以自己的帳號執行；下面 `example.com` 均為虛構範例：

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar init --expected-email codex-user@example.com --calendar-email calendar-user@example.com --apply
.\.venv\Scripts\python.exe -m codex_reset_calendar preview
```

Codex 與 Google 可以使用不同 email。`init --apply` 只保存本機綁定資料、空 ledger 及唯讀驗證結果，不新增事件、不安裝 skill、不啟用排程。預設狀態位於 `%USERPROFILE%\.codex-reset-calendar`；若要另選位置，在所有入口一致傳入 `--state-dir` 或腳本 `-StateDir`。已存在且非空的狀態目錄會被拒絕，避免覆寫。

初始化後，CLI 不接受用參數覆蓋已保存的帳號、時區或執行檔位置。若要使用另一組設定，請選擇不同且空白的狀態目錄，重新檢查及綁定；原 ledger 必須保留，並先檢查是否會產生重複提醒。

預覽會顯示 paired accounts、primary 日曆、候選與 `previewId`。有候選時，檢查後再執行：

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar sync --confirm-preview <剛才輸出的previewId>
```

請把佔位字換成預覽回傳的 32 位十六進位 ID。預覽 15 分鐘有效；帳號、目的日曆、時區、執行檔或候選到期時間變更，需重新預覽。手動同步可在排程未啟用時執行。沒有候選時直接回報結果即可，不必批准新增。

預設提醒寫入已核對 Google 帳號的 primary 日曆：私人、空閒、一分鐘、提前 60 分鐘 popup、無外部受邀人、無 Google Meet。

### 去重與未知結果

- 每次新增前搜尋該額度的精確標記，不按標題或日期猜測相同事件。
- 新增前先保存 durable pending；逾時、批准要求、程序中斷或回傳無法核實時，保留 pending。
- pending 後只核對事件；即使搜尋暫時沒有結果，也不自動再送一次 create。
- 既有事件被修改、取消或額度消失時，不自動修復／刪除；讀取失敗也不重建。
- pending／review 需要人工釐清，沒有一般「清空 ledger 後重試」入口。請先檢查日曆、登入與批准需求；若結果仍不確定，保留紀錄。

手動建立、沒有本工具標記的舊事件無法自動接管。已有其他工具在同一帳號同步時，先用預覽檢查重複風險；不要同時啟用兩套寫入排程。

## Windows 每日排程

先完成帳號綁定與預覽，再決定是否授權定期新增：

```powershell
.\scripts\Install-Task.ps1
.\scripts\Install-Task.ps1 -Apply
```

`-Apply` 是此安裝「每日自動新增新額度提醒」的明確授權。安裝器再次執行唯讀 preflight，先註冊停用任務、設定本機 gate，再啟用；不立即啟動任務。任務已存在就停止，不使用 Force。

- 每日 **電腦本機時間 08:00**，另有目前使用者登入後 30 秒補跑。
- 查詢顯示時區獨立於排程時區；更改 `--time-zone` 不會改成另一國的 08:00 執行。
- 首次執行取下一個未來的 08:00；當天 08:00 已過則從隔天開始。
- 目前使用者 InteractiveToken、LeastPrivilege；不使用 SYSTEM、不儲存密碼、不提高權限。
- 電腦需開機且使用者保持登入；鎖定螢幕可以保持登入。
- `StartWhenAvailable`、登入補跑與每日觸發共用每天一次 claim。08:00 前登入先等待，08:00 後登入可補跑。
- claim 在網路呼叫前保存；當日失敗、中斷、離線也不自動重試。不迴圈補歷史日期，時鐘倒退不重跑。
- 跨程序鎖與 `IgnoreNew` 防止重疊，最長五分鐘，使用 `pythonw.exe` 不開 console。
- 沒有新額度時不新增事件，也不彈通知。錯誤留在本機狀態與 Task Scheduler 結果。

任務名称為 `CodexResetCalendar-<安裝識別碼>-Daily`，識別碼由實際狀態路徑產生。

```powershell
.\.venv\Scripts\python.exe -m codex_reset_calendar status
.\scripts\Disable-Task.ps1
.\scripts\Disable-Task.ps1 -Apply
```

停用保留日曆事件、狀態與 log，不終止已在執行的程序。已有任務不會被重新安裝覆寫；需要恢復時先檢查狀態，再由維護者明確處理。

## AI 協助與選配 skill

完整提示：[繁體中文](docs/AI_DEPLOYMENT.md)／[English](docs/AI_DEPLOYMENT.en.md)。

```powershell
.\scripts\Install-Skill.ps1
.\scripts\Install-Skill.ps1 -Apply
```

安裝器只新增 `codex-reset-calendar` skill，使用此專案的虛擬環境及指定狀態目錄；同名已存在即停止。它不修改其他 skills 或 AGENTS.md。skill 可以理解「查一下重置到期時間」「預覽日曆提醒」「查看同步狀態」，仍依預覽／確認規則呼叫固定工具。

dot 若具有這台 Windows 主機的命令執行權限，可呼叫相同 CLI。OpenClaw 在 WSL 時可使用 Windows Python：

```bash
"/mnt/c/path/to/codex-reset-calendar/.venv/Scripts/python.exe" -m codex_reset_calendar query --format json
```

請換成自己的路徑。此方式使用 **Windows 的 Codex 登入與 connector**，不代表 WSL 或其他 agent 自動取得那些權限。第一版不自動安裝 OpenClaw skills 或修改其設定。

## 狀態、隱私與疑難排解

所有 runtime 狀態與有容量上限的 log 均位於指定 state directory，與 repository 分離。重要檔案為 `config.json`、`ledger.json`、`preview.json`、`runs.json`、`verification.json`、`last-result.json` 及最多四檔、合計約 1 MiB 的 `runtime.log`。

設定包含本機路徑與 paired emails；ledger 包含 credit/event ID。它們是個人資料，不應公開或讓多台電腦同步覆寫。log 只記固定代碼、時間及數量，不保存 token、原始上游診斷或事件內容。本工具不讀取／搬運認證檔，不自行登入。備份程式與個人狀態應分開處理。

| 代碼／狀態 | 處理方式 |
|---|---|
| `cli_not_found` | 安裝既有 Codex CLI 或用 `--codex` 指定完整路徑 |
| `auth_unavailable`／`account_mismatch` | 在 Codex 中自行核對登入；工具不切換帳號 |
| `timezone_unavailable` | 確認已安裝專案依賴，使用有效 IANA 名稱 |
| `calendar_tools_unavailable` | 檢查 CLI 的 Google Calendar connector；先使用查詢或 ICS |
| `host_request_required`／`calendar_tool_failed_or_approval_required` | 服務要求登入／批准或拒絕操作，停止並檢查來源連線 |
| `credits_incomplete_no_sync` | 服務未提供完整明細，稍後重新查詢，不寫入 |
| `manual_preview_*` | 重新預覽、檢查候選與設定後確認 |
| `pending`／`reviewCount > 0` | 保留 ledger，人工核對；不反覆重送 |
| `state_*`／`ledger_*` | 檢查備份與路徑，不刪檔讓工具假定全是新額度 |

## 開發與驗證

```powershell
.\.venv\Scripts\python.exe -m pip install ".[test]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m build
```

CI 在 Windows／Python 3.10、3.12 執行離線測試、PowerShell 語法檢查與獨立 wheel 安裝。測試使用虛構帳號、假 Calendar adapter／stdio server，不使用真實日曆寫入或安裝排程。即使 mock 通過，也不代表你的 connector 已獲得 create 權限。

程式安裝後不依賴 repository 的父資料夾。若將分享版放在個人專案下，Git 初始化、提交與發佈的根目錄應限於含本 README 的分享專區。

驗證範圍與結果：[繁體中文](docs/VALIDATION.md)／[English](docs/VALIDATION.en.md)。

## 參考與授權

- [Codex app-server：account/rateLimits/read](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)
- [Google Calendar ICS 匯入](https://support.google.com/calendar/answer/37118)
- [iCalendar RFC 5545](https://www.rfc-editor.org/rfc/rfc5545)
- [Windows StartWhenAvailable](https://learn.microsoft.com/en-us/windows/win32/taskschd/tasksettings-startwhenavailable)

[MIT License](LICENSE)。這是社群工具，沒有承諾特定帳號一定有重置額度或 connector 權限。
