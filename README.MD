### This project is an all-in-one **n8n Agent** that uses a local Python wrapper library built on top of `yfinance`. The agent uses that wrapper to fetch Yahoo Finance market data over HTTP, including stock prices, expiration dates, and options chains, and then runs the full analysis workflow inside n8n. The goal is to keep everything working together in one local system: data collection, ranking, options analysis, AI evaluation, and email delivery.

###

## Important: Everybody must use their own credentials

Even if I tried to remove my credentials from the JSON file, it might not be 100% clean. So this workflow is meant to stay private or at least not shared publically with your API keys inside.

What you should do:

1. Import the JSON Options Analyzer.json workflow into **your own n8n**.
2. **DO NOT** reuse my API keys, SMTP password, or any other credentials.
3. Create **your own credentials** in n8n for:
   - SMTP / email
   - LLM (Gemini / OpenAI / whatever you choose)
4. Go into every node that uses credentials and link it to **your own** keys, not mine.

In short:

- You are using my **logic and structure**,
- but **all API keys and passwords must be yours only**.

## How to run the whole project on Linux

### 1. Start the project

```bash
cd /path/to/your/project
docker compose up -d --build
```

This:

- builds the images (including any changes in the `yfinance-wrapper`),
- starts all services in the background.

---

### 2. If you make changes to the code

If you update the `yfinance-wrapper` or any other service:

1. Run the cleanup script:

```bash
./cleanup.sh
```

2. Pull the latest code:

```bash
git pull
```

3. Rebuild and restart:

```bash
docker compose up -d --build
```

This ensures:

- old containers and volumes that might be using cached code are cleaned up,
- you get the latest changes from the repo,
- the new containers are built and running with your code.
  > **Note:** If you already imported or created the workflow in n8n, you will not lose it on rebuild. n8n stores workflows in its persistent local database/volume created during the first build, so `docker compose up -d --build` reuses the same saved data.

# Options Ticker Ranker & AI‑Analysis Agent

This is an n8n workflow that:

1. Loads a list of stocks, filters them by price,
2. Scores and ranks them for covered‑call‑style setups,
3. Fetches and analyzes options‑chain data,
4. Identifies the best‑risk‑adjusted calls, and
5. Sends a natural‑language analysis from an LLM to your email.

---

## Getting started

1. Start n8n on `http://localhost:5678` and create a profile.
2. Open the JSON file labeled `AGENT` inside n8n (this is the Agent flow).
3. Adjust the flow to your needs (e.g., change price range, models, or thresholds).
4. Execute the workflow.

---

## What each step of the workflow does

### 1. Schedule trigger

- Fires the workflow automatically at a set interval (e.g., once a day).
- Starts the pipeline without manual click.

### 2. Extract from File

- Reads the CSV or spreadsheet file (e.g., a list of stocks).
- Each row becomes one item in n8n.
- Example fields: `Symbol`, `Name`, `Last Sale`.

### 3. Filter by price

- Keeps only stocks with prices between 30 and 45.
- If you remove this filter, the next API step can run extremely slowly (potentially over 15 hours), because it processes many more tickers.

### 4. Combine all tickers

- Takes all remaining ticker symbols and joins them into one comma‑separated string.
- Example output: `A,AA,AACB,AAL`.
- This string is easier to pass into the next API or AI node than many separate items.

### 5. API request (options‑data)

#### API input

The previous step calls an options‑data API that returns detailed option metrics for each ticker. For example:

```json
{
  "ticker": "AB",
  "price": 40.17,
  "ivCurrent": 0.3477,
  "ivRank": 21.04,
  "ivDirection": "rising",
  "rv30d": 0.1685,
  "vrp": 0.1792,
  "vrpSignal": "sell_premium",
  "callOI": 9209,
  "putOI": 6001,
  "putCallSignal": "bullish"
}
```

- The workflow uses **batches of 1 with a 2‑second interval** to avoid overwhelming the API.

#### Rank score node

This step calculates a custom score for each ticker to identify better covered‑call candidates.

**How it works**

Each stock is scored from 0 to 100 using six factors:

1. **IV Rank (0–30 points)**
   - Higher IV Rank means options are expensive relative to the stock’s own history.
   - Useful for premium‑selling strategies.

2. **VRP: Implied Volatility vs Realized Volatility (0–25 points)**
   - Positive VRP means implied volatility is richer than realized volatility.
   - That favors selling option premium.

3. **IV Direction (0–15 points)**
   - Rising IV means options are getting more expensive.
   - Improves premium‑collection potential.

4. **Put/Call Signal (0–15 points)**
   - Bullish or neutral options flow gets a higher score.
   - Bearish flow gets less or no score.

5. **Current IV Level (0–10 points)**
   - Higher absolute IV usually means larger option premiums.

6. **Liquidity (0–5 points)**
   - Higher call open interest suggests better liquidity and tighter spreads.

**Output**

The workflow:

- calculates a total score for each ticker,
- assigns a human‑readable signal,
- sorts all results from highest score to lowest,
- returns only the top‑ranked names.

**Signals**

- `STRONG_SELL_PREMIUM`: positive premium‑selling setup with rising IV.
- `SELL_PREMIUM`: positive premium‑selling setup.
- `WATCH`: some favorable signs, but not strong enough.
- `SKIP`: weak setup.

### 6. Select the top 10 ranked tickers

This step takes the ranked results from the scoring node and keeps only the **10 best tickers** based on the signal and score logic.

- The workflow sorts all candidates by rank.
- It keeps only the strongest premium-selling setups.
- The output at this stage is the final shortlist of 10 tickers that passed the ranking system.

### 7. Final ticker string (packaging)

This step takes those **10 selected tickers** and converts them into a single JSON output containing one comma-separated string.

- It reads the 10 shortlisted tickers from the previous node.
- It joins them into one string separated by commas.
- Example output:

```json
{
  "tickers": "AB,AA,AAL,XYZ,MMM"
}
```

This string is used in the next API step so the workflow can pass all selected tickers in one compact format.

### 8. Wait node (API throttling)

- Introduces a delay (e.g., 2 seconds) between API requests.
- Prevents flooding the Yahoo‑Finance‑wrapper service and avoids rate limits.

### 9. Options‑chain API

The workflow calls:

for the 10 tickers that passed the ranking system.

- This is a local microservice that wraps the Yahoo Finance API.
- The `/chain` endpoint returns detailed options‑chain data for each ticker: strikes, expiries, bid/ask, implied volatility, and other metrics.
- The tickers are sent as a list, and the API returns one options‑chain result per ticker, ready for downstream analysis or AI prompts.

### 10. Call‑option analyser

This node takes the options‑chain data for each ticker and converts every call option into a structured “trade‑ready” row, adding derived metrics like premium yield, upside, and total return if the call is exercised.  
In simple terms, it is a per‑option analyser for covered calls or naked‑call setups.

For each call:

- calculates premium as `ask` (or `bid` if `ask` is missing).
- computes `premiumYield = premium / spot`.
- calculates `upsidePct = (strike - spot) / spot`.
- sums `premiumYield` and `upsidePct` into `totalIfCalled` (the total return if the call is exercised).
- adds `spreadPct` to show liquidity/market‑quality.
- skips invalid or “in‑the‑money” calls (`strike < spot` or missing strike/premium).
- returns one item per viable call option, ready for AI or downstream scoring.

### 11. Covered‑call quality engine

This node acts as a covered‑call quality engine: it takes each call‑option row, adds detailed breakeven, profit, and risk metrics, and assigns a simple quality tag (`GOOD` / `STRONG` / `SKIP`).  
It tells you which calls are decent trades to consider.

High‑level idea:  
For every call from the previous step, it:

- figures out how many days to expiry (`dte`).
- computes `breakeven`, `profitIfOTM`, `profitIfITM`, and `worstCaseLoss` in dollars.
- adds a `rewardVsRisk` ratio and a `liquidityScore`.
- tags the call as `GOOD` or `STRONG` if it meets certain thresholds (drop tolerance, spread tightness, open interest, and premium yield).

For each call, it computes:

- `breakeven`: the stock price at which the call plus premium is “even”.
- `stockCanDropBy`: how much the stock can fall before the call is exercised, expressed as a percentage of the stock price.
- `profitIfStockStaysFlat` and `profitIfStockAboveStrike`: approximate profit at expiry for two common outcomes.
- `worstCaseLoss`: downside risk if the stock must be bought at the current price.
- `rewardVsRisk`: compares the ITM profit to the worst‑case loss.
- `qualityTag` is assigned:
  - `"GOOD"` if the call has reasonable downside, tight spread, decent liquidity, and a minimal premium yield.
  - `"STRONG"` if conditions are noticeably better.
  - `"SKIP"` otherwise.

This output is ideal for feeding into an AI or filtering step that only acts on `STRONG` or `GOOD`‑tagged calls.

### 12. Split by expiry range

The workflow now splits the options into three expiry buckets:

- 0–100 days to expiry,
- 100–365 days to expiry,
- 365–900 days to expiry.  
  This lets you analyze or present short‑, medium‑, and long‑term options separately.

### 13. Filter by strong rank

The workflow keeps only options tagged as `STRONG`, discarding `GOOD` or `SKIP` unless you change the filter.  
This focuses the final steps on the highest‑quality setups.

### 14. Reward‑vs‑risk ranker

This step normalizes profit and loss into pure numbers, computes a reward‑versus‑risk ratio for each call, and returns the top 10 best‑risk‑adjusted option setups.

- Cleans `profitIfStockStaysFlat` and `worstCaseLoss` from dollar strings (e.g., `"$25.00"` → `25.00`) into plain numbers.
- Adds a `rewardVsRisk` metric that compares premium income to downside exposure.
- Sorts all calls by this metric from highest to lowest and keeps only the top 10, passing them to the final AI or execution step.

### 15. AI‑ready JSON packager

This step bundles the top‑risk‑adjusted options into a formatted JSON string that can be passed directly into an AI‑agent or prompt node.

- Reads all items from the previous node and strips their n8n wrappers.
- Converts the call‑option data into a nicely‑indented JSON string.
- Exports the result as `chatInput`, which can be inserted into an AI prompt such as:

```text
You are an options‑strategy analyst.
Here are 10 short‑call setups:

{{ $json["chatInput"] }}

For each call, explain:
- What is attractive and what is risky.
- Why you would or would not choose this strike/expiry.
- Overall: which 2–3 calls look best and why.
```

### 16. LLM analysis

The final step sends the selected options to a large language model, which generates a natural‑language recommendation and risk discussion.

#### What you configure

- **Choose provider**: either a paid model (e.g., `gemini-1.5-pro` or `GPT‑4‑compatible`) or a free‑tier‑enabled model (e.g., `gemini-2.5-flash` or a free‑tier‑enabled OpenAI‑style model).
- **Paste API key**: each user adds their own API key in the LLM node settings so the workflow runs under their account.

#### Data flow

- The prior node provides `chatInput` (a JSON‑formatted string of the top 10 options).
- The LLM prompt is similar to the example above.
- The LLM returns a free‑form text analysis, which can be:
  - stored in a file,
  - sent by email, or
  - exposed in a UI.

This lets everyone reuse the same pipeline while choosing their own model and paying only for their own API usage.

### 17. Format AI output

The next step formats the raw AI output into a clean, readable structure (e.g., Markdown or HTML) so it is ready to send as an email or save to disk.

### 18. Send email

The final step sends an email to your personal email address with:

- the list of top‑ranked covered‑call setups,
- and the AI‑generated analysis.

You receive a daily or periodic report of the best‑risk‑adjusted options, ready for your review or trade execution.

## SMTP setup for email delivery

To send emails from n8n, create an SMTP credential.

### Gmail example

1. Go to your Google Account → Security.
2. Enable 2-Step Verification.
3. Open App Passwords.
4. Generate a new Mail app password.
5. Copy the 16-character password.

### Add SMTP in n8n

1. Open n8n.
2. Go to **Credentials**.
3. Click **Add Credential**.
4. Choose **Send Email** / SMTP.
5. Fill in:

- Host: `smtp.gmail.com`
- Port: `587`
- User: your full Gmail address
- Password: your Gmail App Password
- Security: TLS

6. Save the credential.
7. Select this credential inside your email node.

## Add API key in n8n

To connect an LLM or API service:

1. Open **n8n**.
2. Go to **Credentials**.
3. Click **Add Credential**.
4. Choose your provider (OpenAI, Gemini, or another compatible provider).
5. Paste your API key.
6. If needed, add the Base URL.
7. Save the credential.
8. Select it in the corresponding AI node.

This allows each user to use their own API key and choose either a free-tier or paid model.

## Important: Everybody must use their own credentials

Even if I tried to remove my credentials from the JSON file, it might not be 100% clean. So this workflow is meant to stay private or at least not shared publically with your API keys inside.

What you should do:

1. Import the JSON workflow into **your own n8n**.
2. **DO NOT** reuse my API keys, SMTP password, or any other credentials.
3. Create **your own credentials** in n8n for:
   - SMTP / email
   - LLM (Gemini / OpenAI / whatever you choose)
4. Go into every node that uses credentials and link it to **your own** keys, not mine.

In short:

- You are using my **logic and structure**,
- but **all API keys and passwords must be yours only**.
