# 0.1.0 驗證紀錄

English: [VALIDATION.en.md](VALIDATION.en.md)

驗證日期：2026-10-04。環境：Windows、Python 3.10.6、PowerShell 5.1／7；Codex CLI 介面基準 0.144.3。

| 項目 | 結果與範圍 |
|---|---|
| 自動測試 | 48 項通過，使用虛構帳號、額度與日曆事件 |
| 查詢 | 零額度、只提供數量、缺漏欄位、null 到期日、異常時間單位、秒級 UTC／時區換算 |
| 同步 | 帳號切換即停止、缺漏明細、預覽過期／設定及候選變更、重複觸發、逾時 pending、核對後採認、重複標記 |
| 每日排程 | 下一個未來 08:00、登入補跑、網路前保存當日嘗試、跨程序鎖、當日不重試及時間倒退 |
| ICS | 獨立 iCalendar parser 驗證秒級時間、穩定 UID、私人／空閒、一分鐘、60 分鐘提醒與 UTF-8 折行 |
| PowerShell | 5.1／7 模擬部署；同名衝突停止、先停用註冊再開啟、停用保留 ledger、選配 skill、中文與空白路徑 |
| 乾淨來源安裝 | 預先下載套件後離線安裝至新虛擬環境；來源複本包含中文及空白路徑 |
| 獨立套件 | wheel／sdist 建置、獨立 wheel 安裝及 CLI entry point，從另一個工作目錄執行 |
| 完整 CLI 流程 | 假 stdio app-server 驗證 query、ICS、init、preview、confirm sync、重複觸發及 status |
| 公開內容 | 來源及建置內容未包含原版私人路徑、帳號或固定額度／事件識別碼；相對文件連結有效 |
| 原版保護 | 個人程式、既有 skills、狀態檔及 Windows 任務 XML 與實作前基準一致 |

安裝與排程測試只操作隔離目錄及假的排程 API，沒有註冊真實的新任務，也沒有安裝 skill 到實際使用者設定。套件不引用父目錄程式或個人狀態。

新版 CLI 的唯讀 query／doctor 已確認能讀取 Codex 帳號及額度明細、Google Calendar profile。沒有啟動模型生成回合，沒有新增、修改或刪除實際日曆事件。

Calendar 寫入、讀者的授權以及無人值守排程仍須由讀者自己的帳號驗證。模擬成功與唯讀連線成功都不代表實際寫入獲准。

Windows CI 已設定 Python 3.10／3.12，測試使用假服務。截至 2026-10-04 的初次交付，尚未執行雲端 CI；發佈後的結果以 [GitHub Actions](https://github.com/taoyutsun/codex-reset-calendar/actions) 為準。依賴下載需要網路；預先快取後，本機安裝與驗收可離線執行。

2026-10-04 的初次交付僅在分享版專區初始化 Git，未推送或建立 GitHub repository／release。本紀錄保留當時的驗證範圍；repository 發佈不代表新增了實際 Calendar 寫入測試。
