# Nifty 50 Dashboard — Setup Guide
Complete step-by-step setup. Do this once. After that, everything runs automatically.

---

## STEP 1 — Install Python on your computer

1. Go to https://www.python.org/downloads/
2. Click the big yellow "Download Python" button
3. Run the installer
4. **IMPORTANT:** On the first screen, check the box that says **"Add Python to PATH"** before clicking Install
5. Click "Install Now"
6. When done, open a new window called **Command Prompt**:
   - Press Windows key + R
   - Type `cmd` and press Enter
7. In the black window, type this and press Enter:
   ```
   python --version
   ```
   You should see something like `Python 3.12.x` — that means it worked.

---

## STEP 2 — Install required libraries

In the same Command Prompt window, paste this and press Enter:

```
pip install yfinance pandas numpy
```

Wait for it to finish (takes about 1 minute). You'll see a lot of text — that's normal.

---

## STEP 3 — Download the project files

The project folder on your computer (`Nifty Dashboard`) already contains:
- `fetch_data.py` — the main script that fetches and scores all 50 stocks
- `.github/workflows/daily_fetch.yml` — the automation file for GitHub

---

## STEP 4 — Test the script on your computer first

1. Open Command Prompt
2. Navigate to the project folder. Type this (adjust if your path is different):
   ```
   cd "C:\Users\Castiel Winchester\OneDrive\Documents\Claude\Projects\Nifty Dashboard"
   ```
3. Run the script:
   ```
   python fetch_data.py
   ```
4. It will take about 5–8 minutes to fetch all 50 stocks.
5. When done, you'll see a file called `nifty_data.json` appear in the folder.
6. You'll also see a `fetch_log.txt` with a summary of what happened.

If you see any red ERROR messages, take a screenshot and share it — we'll fix it together.

---

## STEP 5 — Set up GitHub for automated daily runs

### 5a. Create a new repository on GitHub
1. Go to https://github.com and log in
2. Click the **+** button (top right) → **New repository**
3. Name it: `nifty-dashboard`
4. Set it to **Private** (so your investment data isn't public)
5. Do NOT tick any other options
6. Click **Create repository**

### 5b. Upload your files to GitHub
GitHub will show you a page with instructions. Follow the "push an existing repository" option.

In Command Prompt (in your project folder), run these one by one:

```
git init
git add .
git commit -m "Initial setup"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/nifty-dashboard.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your actual GitHub username.

### 5c. Enable GitHub Actions
1. Go to your repository on GitHub
2. Click the **Actions** tab
3. If it asks you to enable Actions, click **Enable**
4. You'll see "Daily Nifty 50 Data Fetch" listed as a workflow

### 5d. Test the automation manually
1. Click on "Daily Nifty 50 Data Fetch" in the Actions tab
2. Click **Run workflow** → **Run workflow**
3. Watch it run (takes 5–8 minutes)
4. When it turns green ✓, check your repository — `nifty_data.json` will be updated

From now on, this runs automatically every weekday at 4:00pm IST. No laptop needed.

---

## STEP 6 — (Optional) Make it publicly shareable with GitHub Pages

If you want a live URL to share with friends:

1. Go to your repository → **Settings**
2. Scroll to **Pages** in the left sidebar
3. Under "Source", select **main** branch
4. Click **Save**
5. GitHub will give you a URL like: `https://YOUR_USERNAME.github.io/nifty-dashboard/`

Anyone with this link can view your dashboard. If you want it private, skip this step.

---

## HOW IT WORKS AFTER SETUP

```
Every weekday at 4:00pm IST
    ↓
GitHub runs fetch_data.py automatically
    ↓
Script fetches all 50 Nifty stocks from Yahoo Finance
    ↓
Computes adjusted EPS, scores, rankings
    ↓
Saves nifty_data.json to your GitHub repo
    ↓
Dashboard reads the file → always fresh data
```

If a run fails, GitHub will send you an email automatically.

---

## TROUBLESHOOTING

**"python is not recognized"** → Python wasn't added to PATH. Reinstall Python and make sure to tick "Add to PATH".

**"pip is not recognized"** → Same fix as above.

**Script runs but some stocks show errors** → Normal — Yahoo occasionally fails for 1–2 stocks. They'll be retried next day.

**GitHub Actions run fails** → Check the Actions tab for the error message. Most common cause: Yahoo Finance rate-limiting. Solution: re-run the workflow after 30 minutes.

---

*Last updated: April 2026*
