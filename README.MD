This project is a small Python wrapper around yfinance that exposes Yahoo Finance market data through simple HTTP endpoints. It is intended for local use with workflow tools such as n8n, so stock prices, expiration dates, and options chains can be fetched over HTTP instead of calling yfinance directly from the automation platform. Because yfinance is an unofficial Yahoo Finance client, endpoint behavior and data availability may change if Yahoo changes its underlying interfaces.

How to run locally
pip install yfinance fastapi uvicorn

Start locally the APi with
uvicorn app:app --host 0.0.0.0 --port 7000
