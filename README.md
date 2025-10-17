# TDS Project Overview

This project demonstrates the creation of a **Task Deployment System (TDS)** using FastAPI, Gradio, and GitHub integration.

## Features

- **LLM-based Code Generation**: Automatically generates project files based on a task brief using a large language model.
- **GitHub Integration**: Creates repositories, pushes files, and optionally deploys via GitHub Pages.
- **File Handling**: Supports CSV, JSON, images, and other attachments, saving them locally and committing to GitHub.
- **Round-based Task Management**: Supports multiple rounds (round 1 initial build, round 2 revisions) with evaluation checks.

## How It Works

1. The user submits a **task brief** and optional attachments via the API.
2. The system uses an **LLM** to generate project files according to the brief and evaluation checks.
3. Generated files are saved to a local folder and pushed to a GitHub repository.
4. GitHub Pages is optionally enabled for live preview.
5. Evaluation results are sent to a webhook for verification.
