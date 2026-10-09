# 請 AI 協助部署

English: [AI_DEPLOYMENT.en.md](AI_DEPLOYMENT.en.md)

將下面文字貼給能讀取此 repository、執行本機命令的 AI，並填入自己的帳號。先不要把憑證或 token 貼進對話。

> 請協助部署這個 codex-reset-calendar repository。先讀 README.md，確認 Windows、Python 3.10+、既有 Codex CLI 登入、專案根目錄與安裝計畫。使用專案自己的 .venv，不修改全域模型、登入、ExecutionPolicy、其他 skills 或 agent 設定。
>
> 先執行唯讀 query 與 doctor。我的預期 Codex email 是［填入］；Google Calendar email 是［填入，可與 Codex 不同］。若 connector 不可用，先完成查詢與 ICS 備援，清楚回報限制。
>
> 請列出 Setup 與 init 的具體計畫供我確認。部署後先 preview，呈現 paired accounts、primary 日曆、候選到期時間、私人／空閒與提前 60 分鐘 popup；在我確認候選前，不同步、不自行代答同意。
>
> 每日排程與 skill 為選配，只有我明確要求才安裝。排程安裝前先呈現 Install-Task 計畫；請說明需開機且保持登入，每日最多一次嘗試，當日失敗不自動重試。
>
> 不使用重置額度、不啟動額外模型回合、不搬憑證、不建立測試行程、不清空 pending 或 ledger、不修改或刪除既有日曆事件。只用這個工具的固定入口。最後提供實際測試結果、安裝位置、帳號綁定、狀態與尚未驗證的 Calendar 寫入權限。

若只是想查期限，直接要求 AI 用 `query` 即可，不需要初始化 Calendar 或安裝排程。
