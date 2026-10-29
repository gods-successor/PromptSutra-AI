# PromptSutra AI — Free Version Shuru Karne ka Tarika

**Yeh actual full-stack starter project hai**, sirf HTML design nahi. Windows + VS Code par run hoga.

## Step 1 — Software

- **Python 3.12 ya 3.13** install rakho (especially agar tumhare PC par sirf Python 3.14 hai, toh 3.12 parallel install karna easiest rahega).
- VS Code open karo, extract hua `PromptSutra-AI` folder kholo.
- Python dependencies install karne ke liye internet chahiye.

## Step 2 — Terminal mein ye commands ek-ek karke chalao

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python setup_local.py
```

Agar Python 3.13 install hai, `-3.12` ki jagah `-3.13` likho.

## Step 3 — Free Gemini API key lagao

1. https://aistudio.google.com/apikey par jaakar free-tier-eligible API key create karo.
2. Folder ke andar hidden `.env` file kholo (ye `setup_local.py` create karega).
3. `GEMINI_API_KEY=` ke aage apni key paste karo.
4. Key kisi ko mat bhejna. GitHub par `.env` upload mat karna.

## Step 4 — Website chalao

```powershell
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Browser mein **http://127.0.0.1:8000** kholo.

## Step 5 — Free email OTP test

- Website par apna email address type karke **Send verification code** dabao.
- Development mode mein OTP **Python terminal mein print hoga**, Gmail inbox mein nahi jayega.
- OTP enter karo → Dashboard open ho jayega.
- Real Gmail OTP chahiye toh `.env` mein SMTP service configure karni padegi; email provider ke usage limits aur charges ho sakte hain.

## Step 6 — Prompt generate karo

- AI ko apna idea batao, jaise: “Mujhe college management website banani hai”.
- Gemini tumse relevant questions puchega (AI key mandatory).
- Chat ke neeche **Prompt settings** se language, tone, detail aur target AI choose karo.
- **Generate Prompt** button se final prompt generate aur save hoga.
- Library mein prompts copy, edit, refine, favorite ya TXT download kar sakte ho.

## Kya free hai, kya configurable hai?

| Feature | Status |
|---|---|
| Frontend / backend / SQLite | Free, included |
| Local OTP testing | Free, included — terminal-based |
| Gemini AI | Real API integration included; free key and available quota required |
| Google login | Integration included; Firebase setup required |
| Actual Gmail/email OTP | SMTP credentials required, provider limits apply |
| Phone number SMS OTP | **Not included** — real SMS generally requires paid configuration |
| Public web hosting / custom domain | Not included, may cost money |

Detailed Google login steps, SMTP config, tests, security and deployment notes **README.md** mein hain.
