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

from datetime import datetime
import requests

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

model_config_fl = os.path.join(script_dir, "config", "model_choice")
context_window_fl = os.path.join(script_dir, "config", "context_window_size")

transcripts_dir = os.path.join(script_dir, "storage", "transcripts")
os.makedirs(transcripts_dir, exist_ok=True)
session_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
session_transcript_fl = os.path.join(transcripts_dir, f"Transcript_{session_time}.md")
sys_msg_fl = os.path.join(script_dir, "storage", "SYSTEM.md")
think_fl = os.path.join(script_dir, "config", "thinking_status")

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

    messages = [
        {
            'role': 'system',
            'content': system_msg
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
                ctxt_size_input = int(console.input("\nEnter context window size (e.g. 6144): ").strip())

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

                subprocess.run(["ollama", "stop", model_name])

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

                list_input = console.input("\nEnter Option (e.g. 1): ")
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
                        new_context_size = int(console.input("\nEnter new context window size (e.g. 6144): ").strip())

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
                think=thinking_status
            )

            def render_stream(response_stream):
                thinking_txt = ""
                response_txt = ""
                try:
                    with Live(console=console, refresh_per_second=30, transient=False) as live:
                        for chunk in response_stream:
                            message = chunk.get('message', {})

                            thinking_delta = message.get('thinking', '')
                            if thinking_delta:
                                thinking_txt += thinking_delta

                            content_delta = message.get('content', '')
                            if content_delta:
                                response_txt += content_delta

                            renderables = []

                            if thinking_txt:
                                renderables.append(Markdown('### Thinking...'))
                                renderables.append(Text(thinking_txt, style="grey66"))

                            if response_txt:
                                renderables.append(Markdown('### Response :'))
                                renderables.append(Markdown(response_txt))

                            if renderables:
                                live.update(Group(*renderables))

                except KeyboardInterrupt:
                    print()
                    console.print(Panel("RESPONSE INTERRUPTED", style="bold red"))

                except ollama.ResponseError:
                    with open(think_fl, "w") as f:
                        f.write("False")

                    global thinking_status
                    thinking_status = False
                    console.print(Panel("Model does not support thinking. Thinking has been turned off." , style="bold red"))

                console.print()

                timestamp_now = datetime.now()
                timestamp_now_formatted = timestamp_now.strftime("%H:%M")

                with open(session_transcript_fl, "a", encoding="utf-8", errors="replace") as f:
                    #f.write(timestamp_now_formatted)

                    f.write("\n\nUSER: \n")
                    f.write(user_input + "\n")

                    f.write("GLACE: \n")
                    f.write(response_txt + "\n")

                return response_txt

            response_txt = render_stream(stream)
            messages.append(
                {
                    'role': 'assistant',
                    'content': response_txt
                }
            )

        except KeyboardInterrupt:
            console.print(Rule(style="orange3"))
            console.print(Panel(Markdown(" **Exiting Agent Glace...** ")), style="bold red")
            console.print(Rule(style="orange3"))

            subprocess.run(["ollama", "stop", model_name])
                    
            break

if __name__ == "__main__":
    main_loop()