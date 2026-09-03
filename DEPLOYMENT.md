# Deploying ResuMetr

**Frontend → Vercel · Backend → Render**

This guide assumes you have never deployed anything before. Every step says what to
click, what to type, and how to check it worked. If a step fails, the
[Troubleshooting](#12-troubleshooting) section at the end lists the errors you are most
likely to hit and what each one means.

Budget about **45 minutes** the first time.

---

## Table of contents

1. [How the pieces fit together](#1-how-the-pieces-fit-together)
2. [What you need before you start](#2-what-you-need-before-you-start)
3. [Get a Gemini API key](#3-get-a-gemini-api-key)
4. [Put the code on GitHub](#4-put-the-code-on-github)
5. [Deploy the backend to Render](#5-deploy-the-backend-to-render)
6. [Deploy the frontend to Vercel](#6-deploy-the-frontend-to-vercel)
7. [Connect the two (CORS)](#7-connect-the-two-cors)
8. [Check it actually works](#8-check-it-actually-works)
9. [Environment variables, in full](#9-environment-variables-in-full)
10. [Costs and free-tier limits](#10-costs-and-free-tier-limits)
11. [Updating after a code change](#11-updating-after-a-code-change)
12. [Troubleshooting](#12-troubleshooting)
13. [Security checklist](#13-security-checklist)

---

## 1. How the pieces fit together

ResuMetr is two separate programs that talk over the internet.

```
   Your user's browser
           │
           │  loads the page from
           ▼
   ┌───────────────────┐        POST /api/evaluate        ┌──────────────────────┐
   │   Vercel          │  ─────────────────────────────►  │   Render             │
   │   (frontend)      │                                  │   (backend)          │
   │   React + Vite    │  ◄─────────────────────────────  │   FastAPI + Python   │
   │   static files    │        JSON with the score       │                      │
   └───────────────────┘                                  └──────────┬───────────┘
                                                                     │
                                                                     │ 6 calls
                                                                     ▼
                                                            ┌──────────────────┐
                                                            │  Google Gemini   │
                                                            └──────────────────┘
```

**Why two hosts?** The frontend is just files (HTML, CSS, JavaScript) — Vercel serves
those extremely fast and free. The backend needs to run Python, open PDFs, and call
Gemini, which needs a real server. Render provides that.

**The single most important rule:** the **Gemini API key lives only on Render**. Never
put it in the frontend. Anything in a Vercel `VITE_*` variable is compiled into the
JavaScript your users download and can be read by anyone.

---

## 2. What you need before you start

| Thing | Cost | Where |
|---|---|---|
| GitHub account | Free | <https://github.com/signup> |
| Render account | Free | <https://render.com> — sign in with GitHub |
| Vercel account | Free | <https://vercel.com> — sign in with GitHub |
| Google AI Studio account | Free tier available | <https://aistudio.google.com> |
| `git` on your computer | Free | `git --version` to check |

You do **not** need a credit card for any of the free tiers.

---

## 3. Get a Gemini API key

1. Go to <https://aistudio.google.com/apikey>.
2. Click **Create API key**.
3. Choose a Google Cloud project (or let it create one).
4. Copy the key. It is a long opaque string beginning with `AQ.` — treat it like a password.

Keep this tab open — you will paste the key into Render in step 5.

> **Free tier limits matter here.** The free tier allows **20 requests per day, per
> model, per project**. One evaluation makes **6 model calls**, so a single model
> supports roughly **3 evaluations per day**. ResuMetr automatically falls back across
> three models (`gemini-3.6-flash` → `gemini-3.5-flash` → `gemini-3.1-flash-lite`),
> giving you about **10 evaluations a day** before everything is exhausted.
>
> Two consequences worth knowing now:
> - **Creating a new API key in the same Google Cloud project does not help** — the
>   quota is counted per *project*, not per key. You need a different project, or
>   billing enabled.
> - For any real usage, enable billing in Google AI Studio. It is pay-as-you-go and
>   these models are inexpensive.

---

## 4. Put the code on GitHub

Render and Vercel both deploy *from a GitHub repository*, so the code has to be there
first.

Open a terminal in the project folder (the one containing `backend/` and `frontend/`):

```bash
cd /path/to/spo_recommendation_engine

git init
git add .
git commit -m "Initial commit"
```

**Before you push, confirm your secrets are not included:**

```bash
git ls-files | grep -E "\.env$|\.env\.local$" || echo "Good — no .env files are tracked"
```

You must see `Good — no .env files are tracked`. If a `.env` file *is* listed, stop and
run `git rm --cached backend/.env` before continuing. The repository's `.gitignore`
already excludes them, but check anyway — a leaked API key is the most common and most
expensive deployment mistake.

Now create the repository:

1. Go to <https://github.com/new>.
2. Name it, for example, `resumetr`.
3. Leave it **Private** unless you intend to publish it.
4. Do **not** tick "Add a README" — you already have one.
5. Click **Create repository**.
6. Run the two commands GitHub shows you:

```bash
git remote add origin https://github.com/YOUR-USERNAME/resumetr.git
git branch -M main
git push -u origin main
```

> **On private source material.** `knowledge-base/signal-corpora/` holds archives
> extracted from real students' resumes. It is listed in `.gitignore`, so it stays on
> your machine and is never pushed — nothing at runtime reads it. The derived
> dictionaries in `backend/scoring/` are what the matcher loads, and those *are*
> committed. Confirm with `git ls-files | grep signal-corpora`, which should print
> nothing.

---

## 5. Deploy the backend to Render

### 5.1 Create the service

1. Go to <https://dashboard.render.com> and click **New +** → **Web Service**.
2. Click **Connect GitHub** and authorise Render, then pick your `resumetr` repository.
3. Fill in the form exactly as below. **The Root Directory field is the one people get
   wrong** — it must be `backend`, because that is where the Python code lives.

| Field | Value |
|---|---|
| **Name** | `resumetr-api` (this becomes part of your URL) |
| **Region** | Pick the one closest to your users (e.g. Singapore for India) |
| **Branch** | `main` |
| **Root Directory** | `backend` |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn main:app --host 0.0.0.0 --port $PORT --app-dir app` |
| **Instance Type** | `Free` |

**About the start command.** `$PORT` is a variable Render sets for you — do not replace
it with a number. `--app-dir app` tells uvicorn that `main.py` lives inside `backend/app/`.
`--host 0.0.0.0` makes the server reachable from outside the container; `127.0.0.1`
would only accept connections from inside it, and Render would report the service as
unhealthy.

### 5.2 Add the environment variables

Scroll to **Environment Variables** and add these three:

| Key | Value |
|---|---|
| `GEMINI_API_KEY` | the key you copied in step 3 |
| `GEMINI_API_KEYS` | *(optional)* more keys, comma-separated — see below |
| `GEMINI_MODEL_NAME` | `gemini-3.6-flash` |
| `CORS_ORIGINS` | `http://localhost:5173` — you will correct this in step 7 |

**Beating the daily quota with extra keys.** Free-tier quota is counted per day, per
model, per **Google Cloud project**. The backend already rotates across three models;
adding keys from *different projects* multiplies that again:

```
GEMINI_API_KEYS = key-from-project-B,key-from-project-C
```

When a model returns 429 on one key, the request is retried on the **next key with the
same model** — the model is fine, only that project's allowance is spent, and keeping
the model keeps scoring consistent. Only when every key is exhausted for that model does
it move to the next model. A 503 behaves differently and moves straight to the next
model, because a busy model is busy for every key.

Three projects x three models ≈ **90 requests/day ≈ 15 evaluations**, up from about 10
on a single key. A second key from the **same** project adds nothing — the quota is
shared. `/api/health` reports `api_keys_configured` so you can confirm they were read.

Leave `CORS_ORIGINS` as-is for now. You cannot fill in the real value until Vercel has
given you a URL, which happens in step 6.

### 5.3 Deploy

Click **Create Web Service**. The first build takes **5–10 minutes** — it installs
PyMuPDF and the Google SDK from scratch.

Watch the log. You are waiting for:

```
Uvicorn running on http://0.0.0.0:10000
==> Your service is live 🎉
```

Render shows your URL at the top of the page, like
`https://resumetr-api.onrender.com`. **Copy it — you need it in step 6.**

### 5.4 Confirm the backend is alive

Open this in a browser, replacing the hostname with yours:

```
https://resumetr-api.onrender.com/api/health
```

You should see JSON beginning:

```json
{
  "status": "ok",
  "engine_version": "spo-resume-intelligence/1.0",
  "capabilities": { "gemini_configured": true, ... }
}
```

**`"gemini_configured": true` is the bit that matters.** If it says `false`, your
`GEMINI_API_KEY` was not saved — go back to 5.2, re-add it, and click **Manual Deploy →
Deploy latest commit**.

---

## 6. Deploy the frontend to Vercel

1. Go to <https://vercel.com/new>.
2. Click **Import** next to your `resumetr` repository.
3. Set **Root Directory** to `frontend` — click *Edit* beside the field. Like Render's
   root directory, this is the step most often missed.
4. Vercel should auto-detect **Vite** as the framework. If not, select it. Build command
   `npm run build` and output directory `dist` are correct defaults.
5. Expand **Environment Variables** and add:

| Key | Value |
|---|---|
| `VITE_API_BASE_URL` | your Render URL from step 5.3, e.g. `https://resumetr-api.onrender.com` |
| `VITE_USE_MOCK` | `false` |

   Do **not** put a trailing slash on the URL. `https://resumetr-api.onrender.com/` will
   produce request paths with a double slash.

   `VITE_USE_MOCK=false` makes the app call your real backend. Setting it to `true`
   serves a bundled sample result instead, which is useful for a demo with no API key
   and costs no quota.

6. Click **Deploy**. This takes about a minute.

Vercel gives you a URL like `https://resumetr.vercel.app`. **Copy it.**

> **Never add `GEMINI_API_KEY` to Vercel.** Every `VITE_*` variable is baked into the
> JavaScript bundle and is publicly readable. The key belongs on Render only.

---

## 7. Connect the two (CORS)

Right now your frontend will load but every evaluation will fail. Browsers block a page
on one domain from calling a server on another domain unless that server explicitly
allows it. This is called **CORS**, and you have to tell Render which site to trust.

1. Go back to your Render service → **Environment**.
2. Edit `CORS_ORIGINS` and set it to your Vercel URL:

```
https://resumetr.vercel.app
```

   No trailing slash. To allow several sites, separate them with commas and no spaces:

```
https://resumetr.vercel.app,https://resumetr-git-main-you.vercel.app
```

3. Click **Save Changes**. Render redeploys automatically (about a minute).

> **Vercel preview deployments.** Every pull request gets its own URL like
> `https://resumetr-abc123-you.vercel.app`. Those will *not* work until you add them to
> `CORS_ORIGINS` too. For a demo, deploying only from `main` avoids the issue entirely.

---

## 8. Check it actually works

Open your Vercel URL and run one real evaluation:

1. The header should show the ResuMetr wordmark, with **no** "Sample data" chip. If you
   see that chip, `VITE_USE_MOCK` is not `false`.
2. Upload a PDF resume and pick a target role.
3. Click **Evaluate resume**.

**Expect the first run to be slow — 90 seconds is normal, and up to 3 minutes is
possible.** Two things add up:

- **Render free tier sleeps.** After 15 minutes of no traffic the service shuts down.
  The next request has to start it again, which takes **about 50 seconds** before your
  code even begins running. Subsequent requests are fast.
- **The evaluation itself makes 6 Gemini calls**, normally 60–180 seconds in total.

A successful run shows the score ring, the **Diagnostic report** (top strengths,
critical missing elements, line-by-line formatting fixes), the pillar breakdown, and
your PDF on the right with highlighted regions.

If it fails, go to [Troubleshooting](#12-troubleshooting).

---

## 9. Environment variables, in full

### Render (backend)

| Variable | Required | Default | What it does |
|---|---|---|---|
| `GEMINI_API_KEY` | **Yes** | — | Your Google AI Studio key. Without it, evaluations cannot run. |
| `GEMINI_API_KEYS` | No | — | Extra keys, comma-separated, tried when one hits its daily quota. Use keys from *different* Google Cloud projects; same-project keys share one allowance. |
| `CORS_ORIGINS` | **Yes** | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated list of sites allowed to call the API. Must contain your Vercel URL. |
| `GEMINI_MODEL_NAME` | No | `gemini-3.6-flash` | The model tried first. |
| `GEMINI_FALLBACK_MODELS` | No | `gemini-3.5-flash,gemini-3.1-flash-lite` | Tried in order when the primary is overloaded or out of quota. Set to empty to disable. |
| `GEMINI_TIMEOUT_SECONDS` | No | `45` | How long one model gets before the call moves to the next. |
| `MAX_UPLOAD_BYTES` | No | `8388608` (8 MB) | Largest PDF accepted. |

### Vercel (frontend)

| Variable | Required | Default | What it does |
|---|---|---|---|
| `VITE_API_BASE_URL` | **Yes** | — | Your Render URL. No trailing slash. |
| `VITE_USE_MOCK` | **Yes** | `false` | `true` serves the bundled sample and never calls the API. |

> Anything named `VITE_*` is **public**. Treat it as if printed on the homepage.

---

## 10. Costs and free-tier limits

Everything below runs at **zero cost**, with real constraints you should understand
before demoing.

| Limit | Effect | Fix |
|---|---|---|
| **Render free: sleeps after 15 min idle** | First request takes ~50s extra | Open the site a minute before a demo to wake it. Paid tier ($7/mo) never sleeps. |
| **Render free: 512 MB RAM** | Enough for this app. Do **not** add `torch`/`transformers` to `requirements.txt` — they will exhaust memory and the build will fail. | The optional SigLIP visual scorer is intentionally excluded from `requirements.txt`. |
| **Render free: 750 hours/month** | One always-on service fits | — |
| **Gemini free: 20 requests/day/model/project** | ~10 evaluations/day on one key across the three-model chain | Add `GEMINI_API_KEYS` with keys from other projects (~15/day for three), or enable billing. |
| **Vercel free (Hobby)** | Generous; not a practical limit here | Hobby is for non-commercial use. |

**Cold start and the client timeout interact.** The frontend gives up after 300 seconds.
A cold start (50s) plus a slow evaluation (up to 180s) still fits, but if Gemini is
degraded you may see *"The evaluation did not finish within five minutes."* Retrying
usually succeeds because the service is now awake.

---

## 11. Updating after a code change

Both platforms redeploy automatically when you push to `main`:

```bash
git add .
git commit -m "Describe what changed"
git push
```

- **Vercel** rebuilds in ~1 minute.
- **Render** rebuilds in ~3–5 minutes.

Changing an environment variable also triggers a redeploy on both. To redeploy without a
code change, use **Manual Deploy → Deploy latest commit** on Render, or the **⋯ →
Redeploy** menu on Vercel.

Before pushing, it is worth running the test suite locally:

```bash
cd backend && .venv/bin/python -m pytest -q
cd ../frontend && npx tsc --noEmit && npm run build
```

---

## 12. Troubleshooting

### The page loads but every evaluation fails immediately

Open your browser's developer console (F12 → Console). A message mentioning **CORS** or
*"has been blocked by CORS policy"* means `CORS_ORIGINS` on Render does not exactly
match your Vercel URL. Check for a trailing slash, `http` vs `https`, and typos. It must
match character for character.

### `{"gemini_configured": false}` on `/api/health`

`GEMINI_API_KEY` is missing or misspelled on Render. Re-add it under **Environment**,
then **Manual Deploy → Deploy latest commit**. Note that Render does not apply variable
changes until it redeploys.

### `RATE_LIMITED` — "The model quota for this key is exhausted"

You have used the free tier's 20 requests per model for today. Options: wait for the
daily reset, enable billing in Google AI Studio, or create a key in a **different**
Google Cloud project. A new key in the *same* project shares the same exhausted quota.

### "This model is currently experiencing high demand" (503)

Google is load-shedding. The app already handles this by moving to the next model in the
chain automatically, so an evaluation usually still completes — just more slowly. If all
three models are busy, retry in a few minutes.

### The evaluation times out at five minutes

Usually a cold start plus a slow Gemini day. Retry — the service is now awake. If it
persists, check the Render logs for the actual failure.

### Render build fails with `ModuleNotFoundError`

A dependency is missing from `backend/requirements.txt`. Add it, commit, and push.

### Render build fails with "out of memory" or is killed

Something heavy got into `requirements.txt` — most likely `torch` or `transformers`.
Remove them. The visual layout scorer that uses them is optional and disabled by default.

### Vercel build fails with "Could not resolve entry module"

**Root Directory** is not set to `frontend`. Fix it in **Settings → General → Root
Directory** and redeploy.

### The dashboard shows "Sample data" and never calls the backend

`VITE_USE_MOCK` is not `false`. Fix it in Vercel's environment variables and redeploy —
Vite bakes these in at build time, so a redeploy is required.

### Uploads fail for a large PDF

The default cap is 8 MB. Raise `MAX_UPLOAD_BYTES` on Render if you genuinely need more.

### How do I read the backend logs?

Render service → **Logs** in the left sidebar. This is live, and it is where evaluation
errors, model fallbacks and quota messages appear. Lines such as
`extraction: gemini-3.6-flash is out of quota; parking it and trying the next model` are
the fallback chain working as intended, not failures.

---

## 13. Security checklist

Run through this before sharing the URL with anyone.

- [ ] `git ls-files | grep "\.env"` returns nothing.
- [ ] `GEMINI_API_KEY` exists on Render and **nowhere** in Vercel.
- [ ] No key appears anywhere under `frontend/`.
- [ ] `CORS_ORIGINS` lists only sites you control — not `*`.
- [ ] If the repository is public, `knowledge-base/signal-corpora/` has been removed. It
      contains material from real students' resumes.
- [ ] Any API key that has ever been pasted into a chat, an issue, or a screenshot has
      been **rotated** at <https://aistudio.google.com/apikey>.
- [ ] You have decided how long uploaded PDFs are retained. The app does not write them
      to browser storage, and the server keeps them only for the duration of a request —
      but confirm that matches what you tell your users.

---

## Appendix: running it locally

You do not need any of the above to develop.

```bash
# One-time setup
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
printf 'GEMINI_API_KEY=your-key-here\nGEMINI_MODEL_NAME=gemini-3.6-flash\n' > .env
chmod 600 .env

cd ../frontend
npm install
```

Then, from the project root:

```bash
./run.sh
```

This starts the API on <http://localhost:8000> and the dashboard on
<http://localhost:5173>. Press `Ctrl-C` to stop both.

To work on the interface without spending API quota, run the frontend against the
bundled sample instead:

```bash
cd frontend
VITE_USE_MOCK=true npm run dev
```

There is also a command-line interface, which is useful for scoring a resume without the
dashboard:

```bash
cd backend
.venv/bin/python scoring/run_evaluation.py /path/to/resume.pdf --track SDE
```
