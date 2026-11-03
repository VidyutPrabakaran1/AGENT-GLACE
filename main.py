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
from pathlib import Path
import base64
import math

from datetime import datetime
import requests

from ddgs import DDGS
import trafilatura

## MISC

console = Console()

def ollama_active_check(url="http://127.0.0.1:11434"):
    try:
        response = requests.get(url, timeout=5)
        return response.status_code == 200

    except requests.exceptions.ConnectionError:
        return False

if ollama_active_check():
    pass
else:
    console.print(Panel("Ollama is not running. Please start Ollama to use Agent Glace."))
    sys.exit()

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
os.makedirs(transcripts_dir, exist_ok=True)
session_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
session_transcript_fl = os.path.join(transcripts_dir, f"Transcript_{session_time}.md")
sys_msg_fl = os.path.join(script_dir, "SYSTEM.md")
think_fl = os.path.join(home, "AGENT-GLACE", "config", "thinking_status")

SANDBOX_ROOT = Path(os.path.join(home, "AGENT-GLACE", "sandbox")).resolve()
os.makedirs(SANDBOX_ROOT, exist_ok=True)

thinking_status = None

try:
    with open (think_fl, "r") as f:
        tmp_status = f.read()

        if tmp_status == "True":
            thinking_status = True

        else:
            thinking_status = False

except FileNotFoundError:
    os.makedirs(os.path.dirname(think_fl), exist_ok=True)

    with open (think_fl, "w") as f:
        f.write("False")

    thinking_status = False

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

    for msg in reversed(convo_hist):
        msg_len = len(msg["content"])

        if current_chars + msg_len <= remaining_budget:
            selected_hist.insert(0, msg)
            current_chars += msg_len

        else:
            break

    return sys_message + selected_hist

def ollama_list_models():
    model_list_raw = client.list()

    print()
    console.print(Panel(Markdown("**Available Models:**")))
    print()

    for model in model_list_raw.get('models', []):
        print(model.get('model'))

def ollama_list_running():
    ps_list_raw = client.ps()

    print()
    console.print(Panel(Markdown("**Running Models:**")))
    print()

    for model in ps_list_raw.get('models', []):
        print(model.get('name'))

## TOOLS

def save_to_memory(information: str) -> str:
    """
    Saves important, reusable information to long-term memory.
    Use this tool whenever the user explicitly asks you to remember something, or when you discover important information such as user preferences, system configurations, long-term goals, or environmental constraints that will be needed in future interactions. Keep the information concise and structured. DO NOT save transient information or conversational filler.
    """
    try:
        with open(mem_fl, "a") as f:
            f.write(information + "\n")
        return f"Information saved to memory successfully."
    except Exception as e:
        return f"Error: {e}"

def read_memory() -> str:
    """
    Reads information from long-term memory.
    Use this tool at the start of tasks where user preferences, past configurations, or long-term context might be relevant, or when the user refers to something they told you previously. Always proactively read memory if you are unsure about the user's environment, preferences, or if the current task feels underspecified.
    """
    try:
        with open(mem_fl, "r") as f:
            return f.read()
    except Exception as e:
        return f"Error: {e}"

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

    try:
        with open(search_engine_fl, "r") as f:
            search_engine = f.read().strip()
    except FileNotFoundError:
        search_engine = "DDG"

    if search_engine == "SXNG":
        params = {
            "q": query,
            "format": "json",
            "safesearch": 1,
            "categories": "general,news"
        }

        try:
            with open(sxng_url_fl, "r") as f:
                sxng_url = f.read().strip()
                if not sxng_url.endswith("search"):
                    sxng_url = f"{sxng_url.rstrip('/')}/search"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
            response = requests.get(sxng_url, params=params, headers=headers)
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
    try:
        try:
            with open(vmodel_fl, "r", encoding="utf-8") as f:
                vmodel_name = f.read().strip()

            encode_img = base64.b64encode(Path(file_path).read_bytes()).decode()
            desc = client.chat(model=vmodel_name, messages = [{'role': 'user', 'content': 'Describe this image for an LLM', 'images': [encode_img] } ])
            return desc['message']['content']
        
        except FileNotFoundError:
            return "No visual model selected!"
        
    except Exception as e:
        return f"Error: {e}"

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
            subprocess.call(["open", appname])
        else:
            subprocess.call(["xdg-open", appname])
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
        webbrowser.open(url)
        return f"Web page '{url}' opened successfully."
    except Exception as e:
        return f"Error: {e}"

TOOL_REGISTRY = {
    "save_to_memory": save_to_memory,
    "read_memory": read_memory,
    "web_search": web_search,
    "read_sandboxed_file": read_sandboxed_file,
    "list_sandboxed_files": list_sandboxed_files,
    "get_image_context": get_image_context,
    "math_tool": math_tool,
    "check_internet": check_internet,
    "open_app": open_app,
    "open_webpage": open_webpage
}

## CODE

console.print(Rule(style="orange3"))
console.print(Panel(Markdown(" WELCOME TO **AGENT GLACE!** "), title="AGENT GLACE", style="orange3"))

console.print(Panel(Markdown('''
Quick Commands:
- Use `/help` to view available commands.
- Use `/exit` or `/bye` to exit the agent.
''')))

console.print(Rule(style="orange3"))

def main_loop():
    model_name = ""

    with open(sys_msg_fl, "r") as f:
        system_msg = f.read()

    system_msg_final = f"\n\n Current Date: {datetime.now().strftime('%B %d, %Y')}\n\n{system_msg}"

    messages = [
        {
            'role': 'system',
            'content': system_msg_final
        }
    ]

    try:
        with open(model_config_fl, "r", encoding="utf-8") as f:
            saved_model = f.read().strip()

        model_name = saved_model
        #console.print(Panel(Markdown(f"Model Selected: **{saved_model}**")))
        #console.print(Rule(style="orange3"))

    except FileNotFoundError:
        ollama_list_models()
        model_list = client.list().get("models", [])
        available_models = [model.get("model") for model in model_list if model.get("model")]

        if not available_models:
            console.print(Panel(Markdown("**No installed Ollama models were found. Please install a model first.**")))
            console.print(Rule(style="orange3"))
            return

        while model_name not in available_models:
            print()
            console.print(Rule(style="orange3"))
            def_model_input = console.input("\nEnter model name: ").strip()

            if def_model_input in available_models:
                os.makedirs(os.path.dirname(model_config_fl), exist_ok=True)
                with open(model_config_fl, "w", encoding="utf-8") as f:
                    f.write(def_model_input)

                model_name = def_model_input
                console.print(Rule(style="orange3"))
                console.print(Panel(Markdown(f"Model Selected: **{def_model_input}**")))
                console.print(Rule(style="orange3"))
                break

            console.print(Panel(Markdown("**Model not found. Please enter one of the installed models shown above.**")))
            console.print(Rule(style="orange3"))

    try:
        with open(context_window_fl, "r", encoding="utf-8") as f:
            context_size = f.read().strip()

            if not context_size.isdigit() or int(context_size) <= 0:
                console.print(Panel(Markdown("**Invalid context window size found in configuration. Please enter a positive integer for the context window size.**")))
                console.print(Rule(style="orange3"))
                raise FileNotFoundError

    except FileNotFoundError:
        print()
        console.print(Rule(style="orange3"))

        while True:
            try:
                ctxt_size_input = int(console.input("\nEnter context window size (e.g., 6144): ").strip())

                if ctxt_size_input <= 0:
                    console.print(Panel(Markdown("**Invalid input. Please enter a positive integer for the context window size.**")))
                    console.print(Rule(style="orange3"))
                    continue

                break
            except ValueError:
                console.print(Panel(Markdown("**Invalid input. Please enter a valid positive integer for the context window size.**")))
                console.print(Rule(style="orange3"))

        os.makedirs(os.path.dirname(context_window_fl), exist_ok=True)
        with open(context_window_fl, "w", encoding="utf-8") as f:
            f.write(str(ctxt_size_input))

        context_size = ctxt_size_input
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
- `/clear` - To clear conversation history from the current session memory.
- `/context_size` - To change context window size.
- `/transcripts` - To open the transcripts directory.
- `/sandbox` - To open the sandbox directory.
- `/search_engine` - To change search engine.
- `/vision_model` - To set the vision model for image analysis.
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
                ollama_list_models()
                print()
                model_name = ""
                model_list = client.list().get("models", [])
                available_models = [model. get("model") for model in model_list if model.get("model")]

                while model_name not in available_models:
                    model_change_input = console.input("Enter model name: ").strip()

                    if model_change_input in available_models:
                        #os.makedirs(os.path.dirname(model_config_fl))
                        with open (model_config_fl, "w", encoding="utf-8") as f:
                            f.write(model_change_input)

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
                global thinking_status
                if thinking_status == True:
                    thinking_status = False
                    with open(think_fl, "w") as f:
                        f.write("False")

                    console.print(Panel("Thinking has been turned off."))

                elif thinking_status == False:
                    thinking_status = True
                    with open(think_fl, "w") as f:
                        f.write("True")

                    console.print(Panel("Thinking has been turned on."))

                continue

            elif user_input.lower() == "/clear":
                messages = [
                    {
                        'role': 'system',
                        'content': system_msg
                    }
                ]
                console.print(Panel("Conversation history cleared."))
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

                context_size = new_context_size
                os.makedirs(os.path.dirname(context_window_fl), exist_ok=True)
                with open(context_window_fl, "w", encoding="utf-8") as f:
                    f.write(str(new_context_size))

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

                except FileNotFoundError:
                    console.print(Panel(Markdown("**Transcripts directory not found. | No transcripts available.**")))

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
            
                except FileNotFoundError:
                    console.print(Panel(Markdown("**Unable to open Sandbox directory. Try restarting Agent Glace.**")))
                    
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
                        with open(search_engine_fl, "w") as f:
                            f.write("DDG")
                        se_title = "DuckDuckGo"
                    elif new_search_engine == 2:
                        with open(search_engine_fl, "w") as f:
                            f.write("SXNG")
                        tmp_sxng_url = console.input("Enter SearXNG URL (e.g., http://localhost:8080/search ): ").strip()
                        sxng_url = tmp_sxng_url
                        with open(sxng_url_fl, "w") as f:
                            f.write(tmp_sxng_url)
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
                ollama_list_models()
                print()
                vision_model_name = ""
                model_list = client.list().get("models", [])
                available_models = [model. get("model") for model in model_list if model.get("model")]

                while vision_model_name not in available_models:
                    vision_model_change_input = console.input("Enter vision model name (/disable to disable vision): ").strip()

                    if vision_model_change_input.lower() == "/disable":
                        with open (vmodel_fl, "w", encoding="utf-8") as f:
                            f.write("")
                        console.print(Panel(Markdown("**Vision disabled**")))
                        break

                    elif vision_model_change_input in available_models:
                        with open (vmodel_fl, "w", encoding="utf-8") as f:
                            f.write(vision_model_change_input)

                        vision_model_name = vision_model_change_input
                        print()
                        console.print(Rule(style="orange3"))
                        console.print(Panel(Markdown(f"Vision Model Selected: **{vision_model_change_input}** ")))
                        console.print(Rule(style="orange3"))
                        break

                    console.print(Panel(Markdown("**Model not found. Please enter one of the installed models shown above.**")))
                    console.print(Rule(style="orange3"))

                continue

            messages.append(
                {
                    'role': 'user',
                    'content': user_input
                }
            )

            context_payload = get_char_budget_window(messages, max_chars=int(context_size))

            stream =client.chat(
                model=model_name,
                messages=context_payload,
                stream=True,
                tools=list(TOOL_REGISTRY.values()),
                think=thinking_status
            )

            def render_stream(response_stream):
                thinking_txt = ""
                response_txt = ""
                shown_response = 0
                shown_thinking = 0
                tool_calls_buffer = []

                # Ollama emits one chunk per token, so a word like " quick"
                # arrives as a single step. Pull tokens at full speed on a
                # background thread and reveal their characters at a steady
                # pace instead, so the output types out smoothly.
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
                    with Live(console=console, refresh_per_second=60, transient=False) as live:
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

                except ollama.ResponseError:
                    with open(think_fl, "w") as f:
                        f.write("False")

                    global thinking_status
                    thinking_status = False
                    console.print(Panel("Model does not support thinking. Thinking has been turned off." , style="bold red"))

                console.print()

                final_clean_response = re.sub(r'【.*?】', '', response_txt)
                return final_clean_response, tool_calls_buffer

            while True:
                response_txt, tool_calls = render_stream(stream)
                
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
                    fn_name = tool['function']['name']
                    fn_args = tool['function']['arguments']
                    
                    console.print(f"[dim] ⚙️ TOOL EXECUTION: {fn_name} for {fn_args} ⚙️[/dim]\n")
                    
                    if fn_name in TOOL_REGISTRY:
                        tool_result = TOOL_REGISTRY[fn_name](**fn_args)
                    else:
                        tool_result = f"Error: Tool {fn_name} not found."
                        
                    messages.append(
                        {
                            'role': 'tool',
                            'content': str(tool_result)
                        }
                    )
                
                context_payload = get_char_budget_window(messages, max_chars=int(context_size))

                stream = client.chat(
                    model=model_name,
                    messages=context_payload,
                    tools=list(TOOL_REGISTRY.values()),
                    stream=True,
                    think=thinking_status
                )

            with open(session_transcript_fl, "a", encoding="utf-8", errors="replace") as f:
                f.write("\n\nUSER: \n")
                f.write(user_input + "\n")
                f.write("GLACE: \n")
                f.write(final_response_for_transcript + "\n")

        except KeyboardInterrupt:
            console.print(Rule(style="orange3"))
            console.print(Panel(Markdown(" **Exiting Agent Glace...** ")), style="bold red")
            console.print(Rule(style="orange3"))

            #subprocess.run(["ollama", "stop", model_name])
                    
            break

if __name__ == "__main__":
    main_loop()