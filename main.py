## LIBRARIES

import ollama
from ollama import Client

from rich.console import Console, Group
from rich.rule import Rule
from rich.markdown import Markdown
from rich.live import Live
from rich.text import Text
from rich.panel import Panel

import os
import sys
import subprocess
import re
import queue
import threading
import time
import tempfile
import stat
from pathlib import Path, PureWindowsPath
import base64
import math

from difflib import SequenceMatcher

from datetime import datetime
import requests

from ddgs import DDGS
import trafilatura

## MISC

console = Console()

def read_config(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return default
    except (OSError, UnicodeError) as e:
        console.print(Panel(f"Could not read configuration file '{path}': {e}", style="bold red"))
        return default

def write_config(path, value):
    try:
        config_path = Path(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(str(value), encoding="utf-8")
        return True
    except OSError as e:
        console.print(Panel(f"Could not save configuration file '{path}': {e}", style="bold red"))
        return False

def ollama_active_check(url="http://127.0.0.1:11434"):
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200

    except requests.exceptions.RequestException:
        return False

if ollama_active_check():
    pass
else:
    console.print(Panel("Could not connect to Ollama at http://127.0.0.1:11434. Start Ollama and try again.", style="bold red"))
    sys.exit(1)

client = ollama.Client(host='http://127.0.0.1:11434')
script_dir = os.path.dirname(os.path.abspath(__file__))
home = Path.home()

model_config_fl = os.path.join(home, "AGENT-GLACE", "config", "model_choice")
context_window_fl = os.path.join(home, "AGENT-GLACE", "config", "context_window_size")
search_engine_fl = os.path.join(home, "AGENT-GLACE", "config", "search_engine")
sxng_url_fl = os.path.join(home, "AGENT-GLACE", "config", "searxng_url")
vmodel_fl = os.path.join(home, "AGENT-GLACE", "config", "vmodel_choice")
mem_fl = os.path.join(home, "AGENT-GLACE", "MEMORY.md")

transcripts_dir = os.path.join(home, "AGENT-GLACE", "transcripts")
session_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
session_transcript_fl = os.path.join(transcripts_dir, f"Transcript_{session_time}.md")
sys_msg_fl = os.path.join(script_dir, "SYSTEM.md")
think_fl = os.path.join(home, "AGENT-GLACE", "config", "thinking_status")

SANDBOX_ROOT = Path(os.path.join(home, "AGENT-GLACE", "sandbox")).resolve()
try:
    Path(transcripts_dir).mkdir(parents=True, exist_ok=True)
    SANDBOX_ROOT.mkdir(parents=True, exist_ok=True)
except OSError as e:
    console.print(Panel(f"Could not create Agent Glace data directories: {e}", style="bold red"))
    sys.exit(1)

thinking_status = read_config(think_fl, "False").lower() == "true"

## MEMORY

MEMORY_INJECT_CHARS = 3000
SUMMARY_TRANSCRIPT_CHARS = 8000

MEMORY_STOPWORDS = {
    "is", "are", "was", "were", "the", "has", "have", "had",
    "and", "or", "at", "in", "of", "to", "for", "on", "with", "user", "this", "that",
}

def memory_tokens(line: str) -> set:
    words = re.findall(r"[a-z0-9]+", line.lower())
    return {w for w in words if w not in MEMORY_STOPWORDS and len(w) > 2}

def similar_memory_lines(line_a: str, line_b: str) -> bool:
    """
    True when two memory lines carry the same fact despite rephrasing.
    Compares content-word overlap; falls back to raw string similarity
    for short lines where tokens are weak.
    """
    tokens_a = memory_tokens(line_a)
    tokens_b = memory_tokens(line_b)

    if not tokens_a or not tokens_b:
        return False

    overlap = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    if overlap >= 0.7:
        return True

    return SequenceMatcher(None, line_a.lower(), line_b.lower()).ratio() >= 0.85

def load_memory_text() -> str:
    try:
        with open(mem_fl, "r", encoding="utf-8") as f:
            return f.read().strip()

    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError) as e:
        console.print(Panel(f"Could not read long-term memory: {e}", style="bold red"))
        return ""

def build_system_message() -> str:
    try:
        with open(sys_msg_fl, "r", encoding="utf-8") as f:
            system_msg = f.read()

    except FileNotFoundError:
        console.print(Panel(f"System instructions file '{sys_msg_fl}' is missing.", style="bold red"))
        system_msg = ""
    except (OSError, UnicodeError) as e:
        console.print(Panel(f"Could not read system instructions: {e}", style="bold red"))
        system_msg = ""

    memory_section = ""
    memory_text = load_memory_text()

    if memory_text:
        recent_memory = memory_text[-MEMORY_INJECT_CHARS:]
        memory_section = (
            "\n\n## Long-Term Memory (carried over from previous sessions)\n"
            "Facts below are durable knowledge about the user, their environment, and past decisions.\n"
            "Treat them as true unless the user says otherwise.\n\n"
            f"{recent_memory}"
        )

        if len(memory_text) > MEMORY_INJECT_CHARS:
            memory_section += (
                "\n\n(Older memory was trimmed out. Use the `read_memory` tool "
                "for the full file and `search_history` to look through past transcripts.)"
            )

    return (
        f"\n\n Current Date: {datetime.now().strftime('%B %d, %Y')}\n\n"
        f"{system_msg}{memory_section}"
    )

def append_memory(new_text: str, header: str = None) -> int:
    """
    Appends only NEW facts to MEMORY.md, skipping lines that duplicate
    existing memory (even when rephrased). The header is written only
    when at least one fact survives dedup, so no empty sections appear.
    """
    existing_lines = [line.strip() for line in load_memory_text().splitlines() if line.strip()]

    incoming_lines = [
        line.strip() for line in new_text.splitlines()
        if line.strip() and not line.strip().startswith("## Session")
    ]

    fresh_lines = []

    for line in incoming_lines:
        against = existing_lines + fresh_lines
        if any(similar_memory_lines(line, other) for other in against):
            continue

        fresh_lines.append(line)

    if not fresh_lines:
        return 0

    os.makedirs(os.path.dirname(mem_fl), exist_ok=True)
    with open(mem_fl, "a", encoding="utf-8") as f:
        if header:
            f.write(header + "\n")
        f.write("\n".join(fresh_lines) + "\n")

    return len(fresh_lines)

def compact_memory() -> int:
    """
    Removes rephrased duplicates already sitting in MEMORY.md, keeping the
    first occurrence of each fact. Also drops session headers that lost
    every fact under them. Returns how many lines were removed.
    """
    lines = [line.strip() for line in load_memory_text().splitlines() if line.strip()]

    kept = []
    facts_kept = []

    for line in lines:
        if line.startswith("#"):
            kept.append(line)
            continue

        if any(similar_memory_lines(line, other) for other in facts_kept):
            continue

        kept.append(line)
        facts_kept.append(line)

    cleaned = []

    for idx, line in enumerate(kept):
        if line.startswith("## Session"):
            next_line = kept[idx + 1].strip() if idx + 1 < len(kept) else ""

            if not next_line or next_line.startswith("#"):
                continue

        cleaned.append(line)

    removed = len(lines) - len(cleaned)

    if removed <= 0:
        return 0

    with open(mem_fl, "w", encoding="utf-8") as f:
        f.write("\n".join(cleaned) + "\n")

    return removed

def summarize_session(messages, model_name, context_size):
    """
    Asks the model itself to extract durable facts from the current
    conversation. Returns a bullet-list summary or None if there is
    nothing worth remembering.
    """
    transcript_lines = []

    for msg in messages:
        role = msg.get('role')
        content = (msg.get('content') or '').strip()

        if not content:
            continue

        if role == 'user':
            transcript_lines.append(f"USER: {content}")
        elif role == 'assistant':
            transcript_lines.append(f"GLACE: {content}")

    if len(transcript_lines) < 2:
        return None

    transcript = "\n\n".join(transcript_lines)[-SUMMARY_TRANSCRIPT_CHARS:]

    existing_memory = load_memory_text()
    existing_memory_block = ""

    if existing_memory:
        existing_memory_block = (
            f"\n\nEXISTING MEMORY (do NOT repeat facts already listed here; only output NEW facts):\n"
            f"{existing_memory[-3000:]}"
        )

    extraction_prompt = f"""Below is the transcript of a conversation between the user and an AI assistant.

Your job: extract ONLY durable, reusable knowledge for future sessions. Include:
- User preferences (name, style, likes/dislikes)
- Facts about the user's environment (OS, hardware, projects, file paths, tools)
- Long-term goals, decisions, and commitments
- Important corrections the user made

EXCLUDE everything transient: small talk, one-off task steps, temporary file contents, anything only relevant to this session.{existing_memory_block}

Output format: plain markdown bullet lines (one fact per line, "- fact"). Keep each line short and self-contained.
If there is genuinely nothing new to remember, output exactly: NONE

TRANSCRIPT:
{transcript}"""

    try:
        response = client.chat(
            model=model_name,
            messages=[{'role': 'user', 'content': extraction_prompt}],
            stream=False,
            options={'num_ctx': int(context_size)}
        )

        summary = response['message']['content'].strip()
        summary = re.sub(r'<think>.*?</think>', '', summary, flags=re.DOTALL).strip()

        if not summary or summary.upper().startswith("NONE"):
            return None

        return summary

    except Exception as e:
        console.print(Panel(f"Memory consolidation failed: {e}", style="bold red"))
        return None

## FUNCTIONS

def get_char_budget_window(messages, max_chars):
    if not messages:
        return []

    sys_message = [messages[0]] if messages[0].get("role") == "system" else []
    sys_msg_char_count = len(sys_message[0]["content"]) if sys_message else 0

    remaining_budget = max_chars - sys_msg_char_count
    convo_hist = messages[1:] if sys_message else messages

    selected_hist = []
    current_chars = 0

    for idx, msg in enumerate(reversed(convo_hist)):
        content = msg.get("content") or ""
        msg_len = len(content)
        room = remaining_budget - current_chars

        if idx == 0 and msg_len > room and room > 0:
            content = content[: max(room // 2, 1000)] + "\n...[truncated]"
            msg_len = len(content)

        if current_chars + msg_len <= remaining_budget:
            selected_hist.insert(0, dict(msg, content=content))
            current_chars += msg_len

        else:
            break

    return sys_message + selected_hist

def ollama_list_models(show=True):
    try:
        model_list_raw = client.list()
    except (ollama.RequestError, ollama.ResponseError) as e:
        console.print(Panel(f"Could not retrieve Ollama models: {e}", style="bold red"))
        return None

    model_names = [
        model.get('model')
        for model in model_list_raw.get('models', [])
        if model.get('model')
    ]
    if not model_names:
        console.print(Panel("No installed Ollama models were found. Install a model and try again."))
    elif show:
        print()
        console.print(Panel(Markdown("**Available Models:**")))
        print()
        for model_name in model_names:
            print(model_name)
    return model_names

def start_chat_stream(**kwargs):
    try:
        return client.chat(**kwargs)
    except (ollama.RequestError, ollama.ResponseError) as e:
        report_ollama_chat_error(e)
        return None

def report_ollama_chat_error(error):
    message = str(error)
    if "model" in message.lower() and "not found" in message.lower():
        message += "\nThe selected model may have been removed. Use /model to choose another installed model."
    console.print(Panel(f"Ollama request failed: {message}", style="bold red"))

def ollama_list_running():
    try:
        ps_list_raw = client.ps()
    except (ollama.RequestError, ollama.ResponseError) as e:
        console.print(Panel(f"Could not retrieve running Ollama models: {e}", style="bold red"))
        return

    print()
    console.print(Panel(Markdown("**Running Models:**")))
    print()

    for model in ps_list_raw.get('models', []):
        print(model.get('name'))

## TOOLS

MAX_TOOL_RESULT_CHARS = 4000

def save_to_memory(information: str) -> str:
    """
    Saves important, reusable information to long-term memory.
    Use this tool whenever the user explicitly asks you to remember something, or when you discover important information such as user preferences, system configurations, long-term goals, or environmental constraints that will be needed in future interactions. Keep the information concise and structured. DO NOT save transient information or conversational filler.
    """
    try:
        added = append_memory(information)

        if added == 0:
            return "Already in memory; nothing new saved."

        return f"Information saved to memory successfully ({added} new lines)."

    except Exception as e:
        return f"Error: {e}"

def read_memory() -> str:
    """
    Reads the FULL long-term memory file.
    The most recent memories are already injected into your context under the "Long-Term Memory" section, so you usually do NOT need this tool. Only call it when you suspect older entries you need were trimmed from that section, or the user explicitly asks to see their stored memories.
    """
    try:
        return load_memory_text()
    except Exception as e:
        return f"Error: {e}"

def search_history(query: str, max_files: int = 3) -> str:
    """
    Searches past conversation transcripts (markdown files) for a TOPIC KEYWORD.
    Use this ONLY when the user refers to a past conversation about a specific topic
    (e.g., "that python script we wrote", "what did I say about the server setup").
    For recency questions without a topic ("what did I ask last time?", "what did
    we talk about?"), NEVER use this tool — use `read_recent_history` instead.
    NEVER pass meta-words like "last", "previous", "yesterday", "convo", or
    "remember" as the query; they will not match anything.
    Args:
        query (str): The keyword or phrase to search for. Keep it short (1-3 words).
        max_files (int): How many recent transcript files to search (default 3).
    """
    q = query.lower().strip()

    if not q:
        return "Error: empty query."

    transcript_files = sorted(Path(transcripts_dir).glob("*.md"), key=lambda p: p.name, reverse=True)

    if not transcript_files:
        return "No past transcripts exist yet."

    results = []

    for path in transcript_files[:max(1, max_files)]:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        file_hits = []

        for lineno, line in enumerate(text.splitlines(), 1):
            if q in line.lower():
                file_hits.append(f"  - line {lineno}: {line.strip()[:200]}")

            if len(file_hits) >= 3:
                break

        if file_hits:
            results.append(f"{path.name}:\n" + "\n".join(file_hits))

    if not results:
        return (
            f"No mentions of '{query}' found in the last {max_files} transcripts. "
            "If the user was asking about a recent conversation without a specific topic "
            "(e.g., 'what did we talk about?'), try the `read_recent_history` tool instead."
        )

    return "\n\n".join(results)

def read_recent_history(files_back: int = 1, max_lines: int = 40) -> str:
    """
    Shows the tail end of a recent conversation transcript, newest-first.
    Use this whenever the user refers to a recent chat WITHOUT mentioning a specific
    topic (e.g., "what did I ask last time?", "what did we talk about?", "continue
    where we left off"). NEVER use `search_history` for those questions.
    Args:
        files_back (int): 1 = most recent transcript, 2 = the one before it, and so on.
        max_lines (int): How many transcript lines to show (default 40).
    """
    transcript_files = sorted(Path(transcripts_dir).glob("*.md"), key=lambda p: p.name, reverse=True)

    if not transcript_files:
        return "No past transcripts exist yet."

    if files_back < 1 or files_back > len(transcript_files):
        return f"Only {len(transcript_files)} transcripts exist. Use files_back between 1 and {len(transcript_files)}."

    path = transcript_files[files_back - 1]

    try:
        lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    except Exception as e:
        return f"Error reading transcript: {e}"

    max_lines = max(10, max_lines)
    selected = lines[-max_lines:]

    header = f"Transcript: {path.name}"
    if len(lines) > len(selected):
        header += f" (showing last {len(selected)} of {len(lines)} lines)"

    listing = "\n".join(f"  - {item.name}" for item in transcript_files[:5])

    return (
        f"Recent transcripts (newest first):\n{listing}\n\n"
        f"{header}:\n" + "\n".join(selected)
    )

def web_search(query: str, max_results: int=3) -> str:
    """
    Searches the live web. Use this whenever the user asks
    about current events, recent news, real-time data, or facts you are unsure of.
    NOTE: This returns TEXT ONLY. Do not use this to show images, videos, or maps. If the user wants to see an image, construct an image search URL and use the `open_webpage` tool instead.
    Args:
        query (str): A concise, 2-5 word keyword search query. NEVER pass full
            questions or conversational filler (e.g., "Python 3.14 release notes").
        max_results (int): Number of results to return (Minimum is 3).
    """

    search_engine = read_config(search_engine_fl, "DDG") or "DDG"

    if search_engine == "SXNG":
        params = {
            "q": query,
            "format": "json",
            "safesearch": 1,
            "categories": "general,news"
        }

        try:
            sxng_url = read_config(sxng_url_fl)
            if not sxng_url:
                return "SearXNG is selected but its URL is missing. Set it with /search_engine."
            if not sxng_url.endswith("search"):
                sxng_url = f"{sxng_url.rstrip('/')}/search"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(sxng_url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            results = []

            for item in data.get("results", [])[:max_results]:
                title = item.get("title", "")
                content = item.get("content", "")
                url = item.get("url", "")
                results.append(f"Title: {title}\nURL: {url}\nSnippet: {content}\n")
            
            if not results:
                return "No search results found."
                
            return "\n---\n".join(results)

        except Exception as e:
            return f"An error occurred during the web search: {str(e)}"

    else:
        max_results = max(3, max_results)
        context_parts = []
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))

                for i, result in enumerate(results):
                    title = result.get('title', 'No Title')
                    href = result.get('href', 'No URL')
                    snippet = result.get('body', '')

                    if href and isinstance(href, str) and not href.startswith(('http://', 'https://')):
                        href = 'https://' + href.lstrip('/')

                    page_text = ''
                    try:
                        downloaded = trafilatura.fetch_url(href)
                        if downloaded:
                            extracted = trafilatura.extract(
                                downloaded, include_links=False, include_images=False
                            )
                            if extracted:
                                page_text = extracted[:1500].strip()

                    except Exception:
                        page_text = ''

                    content=page_text if page_text else snippet

                    context_parts.append(
                        f'Source [{i}]: {title}\nURL: {href}\nContent:\n{content}'
                    )

        except Exception as e:
            return f"An error occurred during web search: {str(e)}"

        if not context_parts:
            return f"No results found for the query: {query}"

        return "\n\n---\n\n".join(context_parts)

def read_sandboxed_file(file_name: str) -> str:
    """
    Read a text file strictly from inside the sandboxed folder.
    Use this whenever you need to access a text file present inside the sandboxed folder.
    Args:
        file_name (str): Filename or path from list_sandboxed_files.
    """
    try:
        relative_path = Path(file_name)
        if relative_path.parts and relative_path.parts[0] == "SANDBOX":
            relative_path = Path(*relative_path.parts[1:])

        target_path = (SANDBOX_ROOT / relative_path).resolve()

        if not target_path.is_relative_to(SANDBOX_ROOT):
            return "Error: Access denied. Path traversal attempt detected."
            
        if not target_path.is_file():
            return f"Error: File '{file_name}' does not exist."

        with open(target_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def create_sandboxed_file(file_path: str, content: str) -> str:
    """
    Create a new UTF-8 text file inside the sandbox. Never overwrites existing files.
    Args:
        file_path: Relative path and filename inside SANDBOX; may start with SANDBOX/.
        content: Text to write, limited to 1 MB when encoded as UTF-8.
    """
    if not isinstance(file_path, str) or not file_path.strip():
        return "Error: provide a relative file path inside SANDBOX."
    if not isinstance(content, str):
        return "Error: file content must be text."

    normalized_path = file_path.strip().replace("\\", "/")
    if "\x00" in normalized_path or ":" in normalized_path:
        return "Error: invalid characters in file path."

    if normalized_path.split("/", 1)[0].lower() == "sandbox":
        normalized_path = normalized_path.split("/", 1)[1] if "/" in normalized_path else ""

    relative_path = Path(normalized_path)
    if (
        not normalized_path
        or relative_path.is_absolute()
        or relative_path.drive
        or PureWindowsPath(normalized_path).is_absolute()
        or PureWindowsPath(normalized_path).drive
        or any(part in ("", "..") for part in normalized_path.split("/"))
        or relative_path == Path(".")
    ):
        return "Error: file path must be relative to SANDBOX and cannot contain '..'."

    try:
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > 1_000_000:
            return "Error: file content exceeds the 1 MB limit."

        target_path = SANDBOX_ROOT / relative_path
        parent_path = target_path.parent.resolve()
        parent_path.relative_to(SANDBOX_ROOT)
        parent_path.mkdir(parents=True, exist_ok=True)

        parent_path = target_path.parent.resolve()
        parent_path.relative_to(SANDBOX_ROOT)
        resolved_target = (parent_path / target_path.name).resolve()
        resolved_target.relative_to(SANDBOX_ROOT)

        with resolved_target.open("x", encoding="utf-8", newline="") as file:
            file.write(content)
        return f"Created SANDBOX/{relative_path.as_posix()}."
    except FileExistsError:
        return f"Error: SANDBOX/{relative_path.as_posix()} already exists; no file was overwritten."
    except ValueError:
        return "Error: access denied. File path resolves outside SANDBOX."
    except (OSError, UnicodeError) as e:
        return f"Error creating SANDBOX/{relative_path.as_posix()}: {e}"

def edit_sandboxed_file(file_path: str, old_text: str, new_text: str) -> str:
    """
    Replace one exact, unique text match in an existing UTF-8 sandbox file.
    Never creates a file or replaces more than one occurrence.
    """
    if not isinstance(file_path, str) or not file_path.strip():
        return "Error: provide a relative file path inside SANDBOX."
    if not isinstance(old_text, str) or not old_text:
        return "Error: old_text must be a non-empty exact text snippet."
    if not isinstance(new_text, str):
        return "Error: new_text must be text."

    normalized_path = file_path.strip().replace("\\", "/")
    if "\x00" in normalized_path or ":" in normalized_path:
        return "Error: invalid characters in file path."
    if normalized_path.split("/", 1)[0].lower() == "sandbox":
        normalized_path = normalized_path.split("/", 1)[1] if "/" in normalized_path else ""

    relative_path = Path(normalized_path)
    if (
        not normalized_path
        or relative_path.is_absolute()
        or relative_path.drive
        or PureWindowsPath(normalized_path).is_absolute()
        or PureWindowsPath(normalized_path).drive
        or any(part in ("", "..") for part in normalized_path.split("/"))
        or relative_path == Path(".")
    ):
        return "Error: file path must be relative to SANDBOX and cannot contain '..'."

    temp_path = None
    try:
        target_path = (SANDBOX_ROOT / relative_path).resolve()
        target_path.relative_to(SANDBOX_ROOT)
        if not target_path.is_file():
            return f"Error: sandbox file '{relative_path.as_posix()}' does not exist."

        original_bytes = target_path.read_bytes()
        if len(original_bytes) > 1_000_000:
            return "Error: file exceeds the 1 MB edit limit."
        original_text = original_bytes.decode("utf-8")
        match_count = original_text.count(old_text)
        if match_count == 0:
            return "Error: old_text was not found; no changes were made."
        if match_count > 1:
            return f"Error: old_text occurs {match_count} times; provide a more specific snippet. No changes were made."

        updated_text = original_text.replace(old_text, new_text, 1)
        updated_bytes = updated_text.encode("utf-8")
        if len(updated_bytes) > 1_000_000:
            return "Error: edited file would exceed the 1 MB limit."
        if updated_text == original_text:
            return f"No changes needed in SANDBOX/{relative_path.as_posix()}."

        original_mode = target_path.stat().st_mode
        file_descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            dir=target_path.parent
        )
        temp_path = Path(temp_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as temp_file:
            temp_file.write(updated_text)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        if os.name != "nt":
            os.chmod(temp_path, stat.S_IMODE(original_mode))

        if target_path.read_bytes() != original_bytes:
            return "Error: file changed during editing; no changes were applied. Try again."

        os.replace(temp_path, target_path)
        temp_path = None
        return f"Updated SANDBOX/{relative_path.as_posix()}."
    except ValueError:
        return "Error: access denied. Resolved path is outside SANDBOX."
    except UnicodeDecodeError as e:
        return f"Error: sandbox file is not valid UTF-8 text: {e}"
    except OSError as e:
        return f"Error editing SANDBOX/{relative_path.as_posix()}: {e}"
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError as cleanup_error:
                console.print(Panel(f"Could not remove temporary edit file '{temp_path}': {cleanup_error}", style="bold red"))

def handle_sub_dir_error(error):
    console.print((Markdown(f"Skipping subdirectory due to error: {error.filename} ({error.strerror})", style="dim")))

def list_sandboxed_files():
    """
    List all files inside the sandboxed folder.
    Use this whenever the user asks for what files are inside the sandboxed folder (i.e. directly accessible to you).
    List of files inside the sandboxed folder may change if the user adds or removes files so use this tool to confirm the list each
    """
    try:
        sandbox_path = Path(SANDBOX_ROOT)
        found_items = []
        
        for path in sandbox_path.rglob('*'):
            if path.is_dir() or path.is_file():
                relative_path = path.relative_to(sandbox_path).as_posix()
                found_items.append(f"SANDBOX/{relative_path}")
                
        if not found_items:
            return "No files or directories found in the sandbox."
            
        return "\n".join(found_items)

    except OSError as e:
        return(f"OS Error occured: {e}")

def get_image_context(file_path: str) -> str:
    """
    Provides a description of an image file.
    Use this whenever you need to see what's in an image file path given by the user.
    The image file path doesn't need to be inside the sandbox folder.
    """
    vmodel_name = read_config(vmodel_fl)
    if not vmodel_name:
        return "Vision is disabled. Choose a model with /vision_model to analyze images."

    try:
        image_data = base64.b64encode(Path(file_path).read_bytes()).decode()
        response = client.chat(
            model=vmodel_name,
            messages=[{
                'role': 'user',
                'content': 'Describe this image for an LLM',
                'images': [image_data]
            }]
        )
        return response['message']['content']
    except FileNotFoundError:
        return f"Image file '{file_path}' was not found."
    except PermissionError:
        return f"Permission denied while reading image '{file_path}'."
    except (ollama.RequestError, ollama.ResponseError) as e:
        return (
            f"Could not analyze the image with vision model '{vmodel_name}': {e}. "
            "The model may have been removed or may not support images. "
            "Use /vision_model to choose another model or disable vision."
        )
    except (OSError, UnicodeError) as e:
        return f"Could not read image '{file_path}': {e}"
    except Exception as e:
        return f"Error: {e}"

def configure_vision_model():
    current_model = read_config(vmodel_fl)
    available_models = ollama_list_models()

    if current_model:
        if available_models is not None and current_model not in available_models:
            console.print(Panel(f"Saved vision model '{current_model}' is no longer installed."))
        else:
            console.print(Panel(f"Current vision model: **{current_model}**"))
    else:
        console.print(Panel("Vision is currently disabled."))

    if available_models is None:
        console.print(Panel("Ollama is unavailable. You can still disable vision or cancel; start Ollama to select a model."))
    elif not available_models:
        console.print(Panel("No installed models are available. Install a model before enabling vision."))

    while True:
        selection = console.input(
            "Enter an installed model name to enable/change vision, "
            "/disable to turn it off, or /cancel to keep the current setting: "
        ).strip()
        normalized_selection = selection.lower()

        if normalized_selection == "/cancel" or not selection:
            console.print(Panel("Vision setting unchanged."))
            return

        if normalized_selection == "/disable":
            if write_config(vmodel_fl, ""):
                console.print(Panel("Vision disabled."))
            return

        if available_models is None:
            console.print(Panel("Could not verify that model because Ollama is unavailable. Start Ollama and try again."))
            return

        if selection in available_models:
            if write_config(vmodel_fl, selection):
                console.print(Panel(f"Vision enabled with model **{selection}**."))
            return

        if not available_models:
            console.print(Panel("No installed models are available. Enter /disable or /cancel."))
        else:
            console.print(Panel("Model not found. Choose a model from the list, /disable, or /cancel."))

def math_tool(expression: str) -> str:
    """
    Solve a mathematical expression.
    Use this tool whenever you need to calculate something.
    """
    safe_dict = {
        "__builtins__": {},
        "sqrt": math.sqrt,
        "pi": math.pi,
        "e": math.e,
        "abs": abs,
        "round": round,
    }

    try:
        result = eval(expression, safe_dict, {})
        return str(result)
        
    except Exception as e:
        return f"Error: {e}"

def check_internet():
    """
    Checks if there is an internet connection.
    """
    try:
        requests.get("https://www.example.com", timeout=5)
        return True
    except Exception as e:
        return False

def open_app(appname: str) -> str:
    """
    Opens an application.
    Use this tool whenever you need to open an application.
    Some applications may not open due to permissions or other issues.
    """
    try:
        if sys.platform == "win32":
            os.startfile(appname)
        elif sys.platform == "darwin":
            subprocess.run(["open", appname], check=True)
        else:
            subprocess.run(["xdg-open", appname], check=True)
        return f"Application '{appname}' opened successfully."
    except Exception as e:
        return f"Error: {e}"

def open_webpage(url: str) -> str:
    """
    Opens a web page in the default browser.
    CRITICAL: Use this tool whenever the user asks you to "show" them visual media like images, videos, maps, or UI elements, OR if they ask to search or navigate to specific content on a website (e.g., "search for cats on youtube" or "open my reddit notifications"). The `web_search` tool ONLY returns text and CANNOT show images or open deep links.
    - If asked to see an image: construct an image search URL (e.g., `https://www.google.com/search?tbm=isch&q=your+search+term`).
    - If asked to search a specific site: construct its search URL (e.g., `https://www.youtube.com/results?search_query=cats`).
    - If asked to open a specific page/feature on a site (e.g., reddit notifications, github repos): logically deduce the deep link URL (e.g., `https://www.reddit.com/notifications`) and open it.
    Also use this when asked to "open" a generic website or link.
    """
    import webbrowser
    try:
        if not webbrowser.open(url):
            return f"Could not open web page '{url}'."
        return f"Web page '{url}' opened successfully."
    except Exception as e:
        return f"Error: {e}"

TOOL_REGISTRY = {
    "save_to_memory": save_to_memory,
    "read_memory": read_memory,
    "search_history": search_history,
    "read_recent_history": read_recent_history,
    "web_search": web_search,
    "read_sandboxed_file": read_sandboxed_file,
    "create_sandboxed_file": create_sandboxed_file,
    "edit_sandboxed_file": edit_sandboxed_file,
    "list_sandboxed_files": list_sandboxed_files,
    "get_image_context": get_image_context,
    "math_tool": math_tool,
    "check_internet": check_internet,
    "open_app": open_app,
    "open_webpage": open_webpage
}

## CODE

console.print(Rule(style="orange3"))
console.print(Panel(Markdown(" WELCOME TO **AGENT GLACE!** [v0.1]"), title="AGENT GLACE", style="orange3"))

console.print(Panel(Markdown('''
Quick Commands:
- Use `/help` to view available commands.
- Use `/exit` or `/bye` to exit the agent.
''')))

console.print(Rule(style="orange3"))

def main_loop():
    global thinking_status
    model_name = ""

    system_msg_final = build_system_message()

    messages = [
        {
            'role': 'system',
            'content': system_msg_final
        }
    ]

    had_conversation = False

    def consolidate_memory():
        """
        Extracts durable facts from `messages` and appends them to MEMORY.md.
        """
        nonlocal had_conversation

        if not had_conversation:
            return

        had_conversation = False

        console.print(Rule(style="orange3"))
        console.print(Panel("Consolidating this session into long-term memory..."))

        summary = summarize_session(messages, model_name, context_size)

        if summary:
            try:
                compact_memory()
                added = append_memory(summary, header=f"\n## Session {session_time}")
            except OSError as e:
                console.print(Panel(f"Could not save long-term memory: {e}", style="bold red"))
                console.print(Rule(style="orange3"))
                return

            if added:
                console.print(Panel(f"Saved {added} new memory lines."))
            else:
                console.print(Panel("Session matched existing memory. Nothing new saved."))

        else:
            console.print(Panel("Nothing durable enough to remember from this session."))

        console.print(Rule(style="orange3"))

    def offer_memory_save():
        nonlocal had_conversation

        if not had_conversation:
            return

        try:
            choice = console.input(
                "Save durable facts from this conversation to long-term memory? (Yes/No): "
            ).strip().lower()
        except KeyboardInterrupt:
            had_conversation = False
            console.print("\nLong-term memory save skipped.")
            return

        if choice in {"y", "yes"}:
            consolidate_memory()
        else:
            had_conversation = False
            console.print("Long-term memory save skipped.")

    model_name = read_config(model_config_fl)
    available_models = ollama_list_models(show=False)
    if available_models is None:
        return
    if model_name not in available_models:
        if model_name:
            console.print(Panel(f"Saved model '{model_name}' is no longer installed. Select an installed model."))
        if not available_models:
            return
        console.print(Panel(Markdown("**Available Models:**")))
        for available_model in available_models:
            print(available_model)

        while model_name not in available_models:
            print()
            console.print(Rule(style="orange3"))
            model_input = console.input("\nEnter model name: ").strip()

            if model_input in available_models:
                if write_config(model_config_fl, model_input):
                    model_name = model_input
                    console.print(Rule(style="orange3"))
                    console.print(Panel(Markdown(f"Model Selected: **{model_input}**")))
                    console.print(Rule(style="orange3"))
                    break
                return

            console.print(Panel(Markdown("**Model not found. Please enter one of the installed models shown above.**")))
            console.print(Rule(style="orange3"))

    saved_context_size = read_config(context_window_fl)
    if saved_context_size.isdigit() and int(saved_context_size) > 0:
        context_size = int(saved_context_size)
    else:
        if saved_context_size:
            console.print(Panel(Markdown("**Invalid context window size in configuration. Please enter a positive integer.**")))
        print()
        console.print(Rule(style="orange3"))

        while True:
            try:
                context_size = int(console.input("\nEnter context window size (e.g., 6144): ").strip())

                if context_size <= 0:
                    console.print(Panel(Markdown("**Invalid input. Please enter a positive integer for the context window size.**")))
                    console.print(Rule(style="orange3"))
                    continue

                break
            except ValueError:
                console.print(Panel(Markdown("**Invalid input. Please enter a valid positive integer for the context window size.**")))
                console.print(Rule(style="orange3"))

        write_config(context_window_fl, context_size)
        console.print(Rule(style="orange3"))

    console.print(Panel(Markdown(f"Model Selected: **{model_name}** | Context Window Size: **{context_size}**")))
    console.print(Rule(style="orange3"))

    while True:
        try:
            console.print()
            console.print(Rule(style="orange4"))
            user_input = console.input("[bold green]>>> [/bold green]")
            console.print(Rule(style="orange4"))
            console.print()

            if user_input.lower() == "/exit" or user_input.lower() == "/bye":
                offer_memory_save()
                console.print(Rule(style="orange3"))
                console.print(Panel(Markdown(" **Exiting Agent Glace...** ")), style="bold red")
                console.print(Rule(style="orange3"))

                #subprocess.run(["ollama", "stop", model_name])

                break

            elif user_input.lower() == "/help":
                console.print(
                    Panel(
                        Markdown('''
**Miscellaneous:**
- Ctrl + C - To interrupt the response from the model.

**Available Commands:**
- `/exit` or `/bye` - To exit the agent.
- `/list` - To list available/running models.
- `/model` - To change model.
- `/thinking` - To toggle thinking on/off.
- `/clear` - To clear the current model context. Transcript files are kept; saving durable facts to long-term memory is optional.
- `/context_size` - To change context window size.
- `/transcripts` - To open the transcripts directory.
- `/sandbox` - To open the sandbox directory.
- `/search_engine` - To change search engine.
- `/vision_model` - To enable, change, or disable image analysis.
''')
                    )
                )
                continue

            elif user_input.lower() == "/list":
                console.print(Panel('''
    List Options:
    [1] - List Available Models
    [2] - List Running Models
                '''))

                list_input = console.input("\nEnter Option (e.g., 1): ")
                if list_input.lower() == "1":
                    ollama_list_models()
                elif list_input.lower() == "2":
                    ollama_list_running()

                continue

            elif user_input.lower() == "/model":
                available_models = ollama_list_models()
                if not available_models:
                    continue
                print()
                while True:
                    model_change_input = console.input("Enter model name: ").strip()

                    if model_change_input in available_models:
                        if not write_config(model_config_fl, model_change_input):
                            break
                        model_name = model_change_input
                        print()
                        console.print(Rule(style="orange3"))
                        console.print(Panel(Markdown(f"Model Selected: **{model_change_input}** ")))
                        console.print(Rule(style="orange3"))
                        break

                    console.print(Panel(Markdown("**Model not found. Please enter one of the installed models shown above.**")))
                    console.print(Rule(style="orange3"))

                continue

            elif user_input.lower() == "/thinking":
                new_thinking_status = not thinking_status
                if write_config(think_fl, new_thinking_status):
                    thinking_status = new_thinking_status
                    state = "on" if thinking_status else "off"
                    console.print(Panel(f"Thinking has been turned {state}."))

                continue

            elif user_input.lower() == "/clear":
                offer_memory_save()
                messages = [
                    {
                        'role': 'system',
                        'content': build_system_message()
                    }
                ]
                console.print(Panel("Current model context cleared. Transcript files are unchanged."))
                continue

            elif user_input.lower() == "/context_size":
                while True:
                    try:
                        new_context_size = int(console.input("\nEnter new context window size (e.g., 6144): ").strip())

                        if new_context_size <= 0:
                            console.print(Panel(Markdown("**Invalid input. Please enter a positive integer for the context window size.**")))
                            console.print(Rule(style="orange3"))
                            continue

                        break
                    except ValueError:
                        console.print(Panel(Markdown("**Invalid input. Please enter a valid positive integer for the context window size.**")))
                        console.print(Rule(style="orange3"))

                if write_config(context_window_fl, new_context_size):
                    context_size = new_context_size
                    console.print(Panel(Markdown(f"Context window size updated to: **{new_context_size}**")))
                continue

            elif user_input.lower() == "/transcripts":
                current_os = sys.platform

                try:
                    if current_os.startswith("win"):
                        os.startfile(transcripts_dir)
                    elif current_os == "darwin":
                        subprocess.run(["open", transcripts_dir])
                    else:
                        subprocess.run(["xdg-open", transcripts_dir])

                    console.print(Panel(Markdown("**Transcripts directory opened.**")))

                except (OSError, subprocess.SubprocessError) as e:
                    console.print(Panel(f"Could not open transcripts directory: {e}", style="bold red"))

                continue

            elif user_input.lower() == "/sandbox":
                current_os = sys.platform
            
                try:
                    if current_os.startswith("win"):
                        os.startfile(SANDBOX_ROOT)
                    elif current_os == "darwin":
                        subprocess.run(["open", SANDBOX_ROOT])
                    else:
                        subprocess.run(["xdg-open", SANDBOX_ROOT])
                    console.print(Panel(Markdown("**Sandbox directory opened.**")))
            
                except (OSError, subprocess.SubprocessError) as e:
                    console.print(Panel(f"Could not open sandbox directory: {e}", style="bold red"))
                    
                continue

            elif user_input.lower() == "/search_engine":
                console.print(Panel(
                    '''
                    Search Engine Options:
                    [1] - DuckDuckGo (No setup required)
                    [2] - SearXNG (Requires separate SearXNG instance, with JSON output enabled)
                    '''
                ))

                try:
                    new_search_engine = int(console.input("\nEnter new search engine (e.g., 1): ").strip())

                    if new_search_engine == 1:
                        if not write_config(search_engine_fl, "DDG"):
                            continue
                        se_title = "DuckDuckGo"
                    elif new_search_engine == 2:
                        tmp_sxng_url = console.input("Enter SearXNG URL (e.g., http://localhost:8080/search ): ").strip()
                        if not tmp_sxng_url:
                            console.print(Panel(Markdown("**SearXNG URL cannot be empty.**")))
                            continue
                        if not write_config(sxng_url_fl, tmp_sxng_url):
                            continue
                        if not write_config(search_engine_fl, "SXNG"):
                            continue
                        se_title = "SearXNG"
                    else:
                        console.print(Panel(Markdown("**Invalid input. Please enter 1 or 2 for the search engine.**")))
                        console.print(Rule(style="orange3"))
                        continue

                    console.print(Panel(Markdown(f"Search engine updated to: **{se_title}**")))
                    continue
                except ValueError:
                    console.print(Panel(Markdown("**Invalid input. Please enter a valid number for the search engine.**")))
                    console.print(Rule(style="orange3"))
                    continue

            elif user_input.lower() == "/vision_model":
                configure_vision_model()
                continue

            messages.append(
                {
                    'role': 'user',
                    'content': user_input
                }
            )

            had_conversation = True

            context_payload = get_char_budget_window(messages, max_chars=int(context_size))

            stream = start_chat_stream(
                model=model_name,
                messages=context_payload,
                stream=True,
                tools=list(TOOL_REGISTRY.values()),
                think=thinking_status,
                options={'num_ctx': int(context_size)}
            )
            if stream is None:
                continue

            def render_stream(response_stream):
                global thinking_status
                thinking_txt = ""
                response_txt = ""
                shown_response = 0
                shown_thinking = 0
                tool_calls_buffer = []

                tokens = queue.Queue()

                def pump():
                    try:
                        for chunk in response_stream:
                            tokens.put(chunk)
                    except BaseException as exc:
                        tokens.put(exc)
                    finally:
                        tokens.put(None)

                threading.Thread(target=pump, daemon=True).start()

                try:

                    with Live(console=console, refresh_per_second=60, transient=True, vertical_overflow="crop") as live:
                        stream_done = False

                        while True:
                            # 1) Drain every chunk that has arrived (never blocks).
                            while True:
                                try:
                                    chunk = tokens.get_nowait()
                                except queue.Empty:
                                    break

                                if chunk is None:
                                    stream_done = True
                                    break

                                if isinstance(chunk, BaseException):
                                    raise chunk

                                message = chunk.get('message', {})

                                thinking_delta = message.get('thinking', '')
                                if thinking_delta:
                                    thinking_txt += thinking_delta

                                content_delta = message.get('content', '')
                                if content_delta:
                                    response_txt += content_delta

                                if 'tool_calls' in message and message['tool_calls']:
                                    tool_calls_buffer.extend(message['tool_calls'])

                            # 2) Reveal characters. A bigger backlog means a
                            # bigger step, so we catch up within ~0.25s.
                            dirty = False

                            response_backlog = len(response_txt) - shown_response
                            if response_backlog > 0:
                                shown_response += max(1, response_backlog // 16)
                                dirty = True

                            thinking_backlog = len(thinking_txt) - shown_thinking
                            if thinking_backlog > 0:
                                shown_thinking += max(1, thinking_backlog // 16)
                                dirty = True

                            # 3) Render only the revealed prefix.
                            if dirty:
                                renderables = []

                                if shown_thinking:
                                    renderables.append(Markdown('### THINKING...'))
                                    renderables.append(Text(thinking_txt[:shown_thinking], style="dim"))

                                if shown_response:
                                    clean_response = re.sub(r'【.*?】', '', response_txt[:shown_response])
                                    renderables.append(Markdown('### RESPONSE :'))
                                    renderables.append(Markdown(clean_response))

                                if renderables:
                                    live.update(Group(*renderables))

                            if (stream_done
                                    and shown_response >= len(response_txt)
                                    and shown_thinking >= len(thinking_txt)):
                                break

                            time.sleep(1 / 60)

                except KeyboardInterrupt:
                    try:
                        response_stream.close()
                    except Exception:
                        pass
                    print()
                    console.print(Panel("RESPONSE INTERRUPTED", style="bold red"))

                except ollama.ResponseError as e:
                    error_text = str(e).lower()
                    if thinking_status and "think" in error_text and (
                        "not support" in error_text or "unsupported" in error_text
                    ):
                        write_config(think_fl, False)
                        thinking_status = False
                        console.print(Panel("This model does not support thinking. Turned thinking off; please retry your message.", style="bold red"))
                    else:
                        report_ollama_chat_error(e)
                    return None, []

                except ollama.RequestError as e:
                    report_ollama_chat_error(e)
                    return None, []

                console.print()

                final_clean_response = re.sub(r'【.*?】', '', response_txt)

                if thinking_txt:
                    console.print(Markdown('### THINKING...'))
                    console.print(Text(thinking_txt, style="dim"))

                if response_txt:
                    console.print(Markdown('### RESPONSE :'))
                    console.print(Markdown(final_clean_response))

                console.print()

                return final_clean_response, tool_calls_buffer

            while True:
                response_txt, tool_calls = render_stream(stream)
                if response_txt is None:
                    break
                
                assistant_msg = {
                    'role': 'assistant',
                    'content': response_txt,
                }
                if tool_calls:
                    assistant_msg['tool_calls'] = tool_calls
                    
                messages.append(assistant_msg)

                if not tool_calls:
                    final_response_for_transcript = response_txt
                    break

                for tool in tool_calls:
                    try:
                        function = tool["function"]
                        fn_name = function["name"]
                        fn_args = function["arguments"]
                        if not isinstance(fn_name, str) or not isinstance(fn_args, dict):
                            raise ValueError("tool name and arguments have invalid types")
                    except (KeyError, TypeError, ValueError) as e:
                        console.print(f"[orange3] ⚠️ Ignoring malformed tool call: {e}[/orange3]\n")
                        messages.append(
                            {
                                'role': 'tool',
                                'content': f"Error: malformed tool call: {e}"
                            }
                        )
                        continue
                    
                    console.print(f"[dim] ⚙️ TOOL EXECUTION: {fn_name} for {fn_args} ⚙️[/dim]\n")
                    
                    if fn_name in TOOL_REGISTRY:
                        try:
                            tool_result = TOOL_REGISTRY[fn_name](**fn_args)
                        except TypeError as te:
                            bad_arg = None
                            m = re.search(r"unexpected keyword argument '([^']+)'", str(te))
                            if m:
                                bad_arg = m.group(1)
                            console.print(f"[orange3] ⚠️ Invalid params for {fn_name}: {te}[/orange3]\n")
                            tool_result = (
                                f"Error: {fn_name}() called with invalid arguments: {te}. "
                                f"Use the tool's parameter schema exactly and call it again."
                            )
                            if bad_arg:
                                tool_result += f" Remove the unsupported argument '{bad_arg}'."
                        except Exception as e:
                            console.print(f"[orange3] ⚠️ Tool {fn_name} failed: {e}[/orange3]\n")
                            tool_result = f"Error: Tool {fn_name} raised {type(e).__name__}: {e}"
                    else:
                        tool_result = f"Error: Tool {fn_name} not found."

                    tool_content = str(tool_result)
                    if len(tool_content) > MAX_TOOL_RESULT_CHARS:
                        tool_content = tool_content[:MAX_TOOL_RESULT_CHARS] + "\n...[truncated to fit context]"

                    messages.append(
                        {
                            'role': 'tool',
                            'content': tool_content
                        }
                    )
                
                context_payload = get_char_budget_window(messages, max_chars=int(context_size))

                stream = start_chat_stream(
                    model=model_name,
                    messages=context_payload,
                    tools=list(TOOL_REGISTRY.values()),
                    stream=True,
                    think=thinking_status,
                    options={'num_ctx': int(context_size)}
                )
                if stream is None:
                    response_txt = None
                    break

            if response_txt is None:
                continue

            try:
                with open(session_transcript_fl, "a", encoding="utf-8", errors="replace") as f:
                    f.write("\n\nUSER: \n")
                    f.write(user_input + "\n")
                    f.write("GLACE: \n")
                    f.write(final_response_for_transcript + "\n")
            except OSError as e:
                console.print(Panel(f"Could not save this exchange to the transcript: {e}", style="bold red"))

        except KeyboardInterrupt:
            offer_memory_save()
            console.print(Rule(style="orange3"))
            console.print(Panel(Markdown(" **Exiting Agent Glace...** ")), style="bold red")
            console.print(Rule(style="orange3"))

            #subprocess.run(["ollama", "stop", model_name])
                    
            break

if __name__ == "__main__":
    main_loop()