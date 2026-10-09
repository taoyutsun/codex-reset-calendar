# Ask an AI to help deploy

繁體中文 / Traditional Chinese: [AI_DEPLOYMENT.md](AI_DEPLOYMENT.md)

Give the following prompt to an AI that can read this repository and execute local commands. Fill in your accounts; do not paste credentials or tokens.

> Help deploy this codex-reset-calendar repository. Read README.en.md first and inspect Windows, Python 3.10+, existing Codex CLI sign-in, repository root and installation plan. Use the project's .venv. Do not change global models, sign-in, ExecutionPolicy, other skills or agent settings.
>
> Run read-only query and doctor first. My expected Codex email is [fill in]; Google Calendar email is [fill in, may differ]. If the connector is unavailable, complete query and ICS fallback first and explain the limitation.
>
> Present concrete Setup and init plans for review. After deployment, run preview and show paired accounts, primary calendar, candidate expirations, private/free events and the 60-minute popup. Do not synchronize or answer approval on my behalf before I confirm candidates.
>
> The daily task and skill are optional; install only when I explicitly ask. Show Install-Task's plan first. Explain that the computer must be on and signed in, with at most one daily attempt and no automatic retry after a failed day.
>
> Do not redeem credits, start extra model turns, move credentials, create test events, clear pending or ledger, or edit/delete existing events. Use only this tool's fixed entry points. Report actual verification, installation paths, paired accounts, status and any unverified Calendar write permissions.

If you only want expiry information, ask the AI to use `query`. Calendar initialization and scheduling are unnecessary.
