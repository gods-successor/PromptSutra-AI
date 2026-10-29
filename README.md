# ✦ PromptSutra AI — Free-tier-friendly full-stack starter

**Think it. Describe it. Prompt it.**

A ChatGPT-style AI prompt architect. Login with email OTP (terminal test mode or real SMTP), optionally enable Google Sign-In through Firebase, chat with Gemini for targeted questions, generate prompts, refine versions, favorite, copy, download, and revisit your history.

## What actually works

- Responsive HTML/CSS/vanilla JS application; dark/light switch; desktop/mobile sidebar.
- Python FastAPI REST backend; SQLite persistence; per-user chats and prompts.
- Local email OTP testing **without paying anything**: 6-digit code appears in your Python server terminal. This is **not a real Gmail email**.
- Real email OTP delivery when you provide SMTP credentials (some services offer limited free quotas).
- Google Sign-In when a free Firebase project and service account are configured (see below).
- Real Gemini model calls for follow-up questions, prompt generation and refinement **when you provide a free-tier-compatible API key**. No fake AI responses.
- Saved prompts and editable version history; copy to clipboard, TXT download, favorites.
- Disabled phone OTP placeholder. **Real SMS is not free and is not implemented in this starter.**

## 1. Windows setup (VS Code or PowerShell)

Use **Python 3.11–3.13** for the easiest dependency compatibility. In PowerShell inside the extracted `PromptSutra-AI` folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python setup_local.py
```

If you have Python 3.13 instead, replace `-3.12` with `-3.13`. If PowerShell prevents activation, either run commands with `.venv\Scripts\python.exe` directly, or follow Microsoft's normal virtual-env execution policy instructions. There is no need to disable Windows security.

Open `.env` and add your Gemini key:

```env
GEMINI_API_KEY=YOUR_KEY_HERE
GEMINI_MODEL=gemini-2.5-flash
```

Get the key at **https://aistudio.google.com/apikey**. Check the exact models and daily limits currently included in your project's free tier at **https://ai.google.dev/gemini-api/docs/pricing**; availability varies. A free-tier key can hit quotas. **Do not commit your `.env` to Git.** Free-tier prompts/data may be used to improve Google's products; don't send sensitive personal data.

Run the server:

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** (not `file://`). For later runs, double-click `run_windows.bat` after setup.

### Test sign-in without email expenses

1. Enter **your own email address** in the web sign-in screen.
2. Click **Send verification code**.
3. Look at the **terminal running uvicorn**. It prints `[LOCAL DEVELOPMENT ONLY] OTP for ...: 123456`.
4. Enter the 6 digits in the browser. You are logged in.
5. Describe a goal, answer a question or two, click **Generate Prompt**. The call uses Gemini and stores the result.

**Security:** Local OTP mode is for development on your own computer only; do not publicly expose this configuration. Production mode refuses to run without a configured SMTP provider. Both modes use cryptographically random codes, hashed codes, expiry, throttling, and one-time use.

## 2. Send real Gmail/email OTP (optional)

Choose an SMTP service/account that allows application email sending. Set:

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=your_smtp_account
SMTP_PASSWORD=your_app_password_or_smtp_token
EMAIL_FROM=verified-sender@example.com
```

Use an **app password or service-specific credential**, never your everyday Gmail password. The sample server connects via STARTTLS on port 587. Some hosting providers block outgoing SMTP. After configuring, restart the backend. Email OTP codes now go to the recipient's inbox rather than the terminal. Pricing and quotas depend on your email provider.

## 3. Google Sign-In with Firebase (optional; no need for phone OTP)

1. Create a project: https://console.firebase.google.com/ (start on Spark/free plan).
2. Enable **Authentication → Sign-in method → Google**; choose a support email.
3. Add a **Web App**, copy its public Firebase configuration to `.env`:

```env
FIREBASE_API_KEY=...
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
FIREBASE_PROJECT_ID=your-project
FIREBASE_APP_ID=1:...:web:...
```

4. Under **Project settings → Service accounts**, generate and download an **Admin SDK private key** JSON. Keep it outside public files, ideally in a private folder, e.g. `C:/private/promptsutra-firebase.json`.
5. Set `FIREBASE_SERVICE_ACCOUNT=C:/private/promptsutra-firebase.json` in `.env`.
6. In Firebase Auth → Settings → Authorized domains, add `localhost` / your actual deployment domain as appropriate. The popup requires an allowed domain. Restart Python.
7. The **Continue with Google** button is enabled only when the needed configuration exists.

**Never put the Admin SDK private key in `frontend/`, GitHub, or a client script.** Public Firebase Web App config is safe to send to the browser. This project sends Firebase ID tokens to FastAPI, which checks the signed token server-side before creating its own session.

## 4. Architecture

```text
PromptSutra-AI/
  frontend/
    index.html         Auth + chat dashboard + prompt library + modal
    css/style.css      Responsive styles and themes
    js/app.js          Frontend SPA with fetch API and safe DOM text
  backend/app/
    config.py          Environment settings
    database.py        SQLAlchemy models and SQLite / PostgreSQL support
    ai.py              Gemini AI interviewer, generation, refinement
    main.py            Auth, CSRF, ownership checks, API and static hosting
  backend/tests/       Automated tests
  requirements.txt
  setup_local.py       Creates local .env with a random secret
  run_windows.bat
  .env.example
```

Open `http://127.0.0.1:8000/api/docs` for the backend API interface. State and history are stored in `promptsutra.db`, created automatically. Because the frontend and API share a host, no CORS configuration is required.

### API routes

- `/api/auth/csrf`, `/api/auth/me`, `/api/auth/email/request`, `/api/auth/email/verify`, `/api/auth/google`, `/api/auth/logout`
- `/api/conversations` (list/create), `/api/conversations/{id}` (read/rename/delete), `/api/conversations/{id}/messages` (chat), `/api/conversations/{id}/generate` (prompt)
- `/api/prompts` (list), `/api/prompts/{id}` (read/edit/delete), `/api/prompts/{id}/refine`, `/api/prompts/{id}/versions`

Login relies on an HttpOnly, SameSite=Strict cookie; API writes require a matching CSRF header. Database reads and writes are scoped by authenticated user ID.

## 5. Tests

With the environment and dependencies installed:

```powershell
python -m pytest backend/tests -v
```

These tests don't spend Gemini tokens; mocked AI outputs are used in the automated tests only. Real UI behavior always requires an actual Gemini API key.

## 6. Production checklist — not ready for public deployment as-is

This is an **MVP for learning and local use**, not an audited production identity system. Before deployment:

- Replace `ENVIRONMENT=development` with `production`, use random `APP_SECRET` (already generated by setup), `SECURE_COOKIES=true`, configure HTTPS/SMTP.
- Use a managed PostgreSQL database (`DATABASE_URL`) with proper migrations (Alembic); `create_all` is local-starter convenience only.
- Replace in-memory throttling with shared Redis/proxy-level rate limiting; restrict spam/abuse and monitor SMS/email/AI billing.
- Add session/device management, monitoring, backups, account data export/deletion, privacy policy, and proper retention.
- Enable strict HTTPS, strong response security headers and hosting-level request limits; verify all dependencies and run security testing.
- If serving users publicly, review Firebase/Google AI free-tier terms, privacy, quotas, and the applicable consent requirements.

## FAQ

**Does this cost ₹0?** You can develop and test on your laptop for ₹0, subject to Gemini's free-tier eligibility/limits. Local email OTP costs nothing but goes to the terminal, not Gmail. External mail delivery, hosting, a custom domain, high AI usage or actual SMS can cost money.

**Can it work without an AI key?** You can sign in, browse and create chats. AI replies / prompt generation are deliberately blocked with a clear error until a key is configured; they are not faked.

**Why isn't phone OTP enabled?** Firebase real SMS verification needs a paid-enabled setup in many cases. We intentionally haven't pretended to implement it.

**Does ChatGPT Plus include an API key?** No; a paid ChatGPT plan and API billing are separate.
