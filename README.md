# Agent Glace

Agent Glace is a lightweight, local agentic harness for running smaller LLMs (e.g. <4B parameters) on modest systems through Ollama, aimed at making small local models more useful for lightweight everyday assistance.
It provides the model with a focused set of tools for tasks such as web search, image analysis, and sandboxed file access.

> **Note:** Tool-calling reliability, speed, and quality may vary based on model.

## Requirements

- Python 3.10 or later
- [Ollama](https://ollama.com/) installed and running on the same computer
- At least one Ollama model installed. Choose a model that supports tool calling for the best experience; model capabilities vary.
- An internet connection for web search and page retrieval

Agent Glace connects to Ollama at `http://127.0.0.1:11434`.

## Installation

Clone or download this repository, then create and activate a virtual environment in the same directory.

### Windows (Powershell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### macOS and Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Install at least one model with Ollama before launching. For example:

```sh
ollama pull gemma4:e2b
```

Use an Ollama model compatible with your machine; model names and capabilities may change.

## Run

From the project directory, with Ollama running and the virtual environment active:

```sh
python main.py
```

On first launch, Agent Glace asks you to select an installed model and enter a positive context-window size. The selected model must be available in Ollama.

The context size you enter is used by Agent Glace in two ways: it is sent to Ollama as the requested `num_ctx` for chat requests, and it helps Agent Glace limit how much conversation history it includes. That local history limit is measured approximately in characters, not tokens. You normally do not need to enter the same value separately in Ollama; however, if your Ollama setup imposes a lower context limit, raise that limit to allow the requested size. Larger context windows can use more memory.

## Commands

Enter these commands at the Agent Glace prompt:

| Command | Action |
|---|---|
| `/help` | Show available commands |
| `/list` | List available or currently running Ollama models |
| `/model` | Change the chat model |
| `/thinking` | Toggle model thinking support |
| `/clear` | Clear the current conversation and offer to save durable memory |
| `/context_size` | Change the context-window setting |
| `/transcripts` | Open the transcript folder |
| `/sandbox` | Open the sandbox folder |
| `/search_engine` | Choose DuckDuckGo or configure a SearXNG instance |
| `/vision_model` | Enable, change, or disable image analysis |
| `/exit`, `/bye` | Exit and offer to save durable memory |

Press Ctrl+C to interrupt a response or exit.

Opening folders requires a desktop environment and its platform opener (`open` on macOS, `xdg-open` on Linux, or the Windows shell).

## Tools

Agent Glace can use tools for:

- Saving, reading, and searching local long-term memory and conversation transcripts
- Web search and extracting text from result pages
- Listing, reading, creating, and making exact text edits to files inside its sandbox directory. Files are limited to 1 MB; creation never overwrites, and edits require one unique match.
- Image analysis with a separately selected Ollama vision model
- Basic math, checking internet connectivity, opening applications, and opening web pages

This release does **not** provide a general-purpose shell or arbitrary script execution. Model tool support varies; a model may not reliably call every tool.

To create a file, ask the assistant to save it in the sandbox (for example, “Create `notes/ideas.txt` in the sandbox with these notes…”). Files are stored locally under `~/AGENT-GLACE/sandbox`. Existing files are not replaced.

To edit a file, ask for a specific change to a sandbox file. The edit tool replaces one exact text snippet only when it occurs once; it will refuse ambiguous matches and will not create or overwrite files.

## Local data and network use

Agent Glace stores configuration, memory, transcripts, and sandbox files (including files created by the assistant) under `~/AGENT-GLACE` (the current user's home directory). It reads `SYSTEM.md` from the application directory. The exact home-directory location depends on the operating system.

Chat and image-analysis requests are sent to the configured Ollama endpoint, which this version fixes at `http://127.0.0.1:11434`. Web search uses DuckDuckGo by default, or a SearXNG server if configured. Search results may cause page text to be fetched from the result websites. The internet-check tool contacts `https://www.example.com`; opening a web page launches the system browser. This application does not currently send local memory or sandbox files to a developer-operated service.

## Tested models & performance

These are the models that have been tested to work reliably with Agent Glace, below are the average speeds of the models on this system configuration:

- **CPU:** Intel Core i7-1185G7
- **Memory:** 24 GB DDR4-3200

| Ollama model | Average speed |
|---|---:|
| `gemma4:e2b` | 18.33 tok/s |
| `granite4.2:3b` | 10.46 tok/s |
| `gemma4:e4b` | 8.80 tok/s |

These are results from one system and setup, not guaranteed performance figures. Speed and tool-calling quality can vary with hardware, Ollama and model versions, and configuration.

## Troubleshooting

- **Cannot connect to Ollama:** Start Ollama and confirm it is listening on `127.0.0.1:11434`.
- **Saved model is missing:** Install it with Ollama, then restart Agent Glace and select an installed model.
- **Vision is unavailable:** Use `/vision_model` to choose an installed model capable of image analysis.
- **Linux cannot open a folder or app:** Install `xdg-utils` and use a graphical desktop session, or navigate to the files manually.
- **Search fails:** Check your internet connection. If using SearXNG, verify the server URL and that its JSON search endpoint is enabled.

## License

Agent Glace is distributed under the MIT License; see [LICENSE](./LICENSE). Third-party software, model weights, and external services may have separate terms and licenses.