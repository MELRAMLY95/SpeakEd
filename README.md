---
title: SpeakEd
emoji: 🗣️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# SpeakEd

A virtual speaking examiner for the Edexcel 4XES2 English (as a Second Language) speaking exam. Students practise, record answers, and receive practice marks and estimated grades. Built with Flask, PostgreSQL (SQLite for local dev), and gunicorn.

## Deploy to Render (recommended, free)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/melramly95/speaked)

One click uses the committed [`render.yaml`](render.yaml) Blueprint, which:

- creates a managed **PostgreSQL** database and wires `DATABASE_URL` automatically,
- generates a stable `SECRET_KEY`,
- pins the Python runtime and runs `gunicorn app:app`.

During setup Render prompts for two values — these are your website login:

| Variable | Set it to |
| --- | --- |
| `OWNER_EMAIL` | the email (username) you want to sign in with |
| `OWNER_PASSWORD` | the password you want to sign in with |

After it deploys, open the `*.onrender.com` URL and sign in at `/login` with those credentials. To enable real AI exam marking, add `GEMINI_API_KEY` or `ZAI_API_KEY` in the dashboard (otherwise the app runs with an offline rule-based fallback).

> Why these are required: in production the app refuses to start on SQLite or without a stable secret, because Render's disk is wiped on each redeploy and would silently lose every account. The Blueprint supplies a real database so this never happens.

## Local development

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/python app.py        # http://127.0.0.1:5000
```

Local runs default to a SQLite database and need no configuration. See [`.env.example`](.env.example) for all options. Run the tests with:

```bash
./.venv/bin/python -m pytest
```
