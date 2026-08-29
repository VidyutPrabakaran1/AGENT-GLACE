## LIBRARIES

import ollama
from ollama import Client

from rich.console import Console, Group
from rich.rule import Rule
from rich.markdown import Markdown
from rich.live import Live
from rich.text import Text

import os
import subprocess

from datetime import datetime

## MISC

client = ollama.Client(host='http://127.0.0.1:11434')
script_dir = os.path.dirname(os.path.abspath(__file__))

model_config_fl = os.path.join(script_dir, "config", "model_choice")

transcripts_dir = os.path.join(script_dir, "storage", "transcripts")
os.makedirs(transcripts_dir, exist_ok=True)
session_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
session_transcript_fl = os.path.join(transcripts_dir, f"Transcript_{session_time}.md")

## FUNCTIONS

def ollama_list_models():
    model_list_raw = client.list()

    print()
    console.print(Markdown("### **Available Models:**"))
    print()

    for model in model_list_raw.get('models', []):
        print(model.get('model'))

def ollama_list_running():
    ps_list_raw = client.ps()

    print()
    console.print(Markdown("### **Running Models:**"))
    print()

    for model in ps_list_raw.get('models', []):
        print(model.get('name'))

## CODE

console = Console()

console.print(Rule(style="orange3"))
console.print(Rule(style="orange3"))
console.print(Markdown(" WELCOME TO **AGENT GLACE!** "))
console.print(Rule(style="orange3"))
console.print(Rule(style="orange3"))

#console.print() - Spaced out automatically by below MD text
console.print(Markdown('''
- Use `/exit` or `/bye` to exit the agent.
'''))
console.print()
console.print(Rule(style="orange3"))

def main_loop():
    model_name = ""

    messages = [
        {
            'role': 'system',
            'content': '''You are Agent Glace.'''
        }
    ]

    try:
        with open(model_config_fl, "r", encoding="utf-8") as f:
            saved_model = f.read().strip()

        model_name = saved_model
        console.print(Markdown(f"Model Selected: **{saved_model}**"))
        console.print(Rule(style="orange3"))

    except FileNotFoundError:
        ollama_list_models()
        model_list = client.list().get("models", [])
        available_models = [model.get("model") for model in model_list if model.get("model")]

        if not available_models:
            console.print(Markdown("**No installed Ollama models were found. Please install a model first.**"))
            console.print(Rule(style="orange3"))
            return

        while model_name not in available_models:
            def_model_input = console.input("\nEnter model name: ").strip()

            if def_model_input in available_models:
                os.makedirs(os.path.dirname(model_config_fl), exist_ok=True)
                with open(model_config_fl, "w", encoding="utf-8") as f:
                    f.write(def_model_input)

                model_name = def_model_input
                console.print(Markdown(f"Model Selected: **{def_model_input}**"))
                console.print(Rule(style="orange3"))
                break

            console.print(Markdown("**Model not found. Please enter one of the installed models shown above.**"))
            console.print(Rule(style="orange3"))

    while True:
        console.print()
        console.print(Rule(style="orange4"))
        user_input = console.input("[bold green]>>> [/bold green]")
        console.print(Rule(style="orange4"))
        console.print()

        if user_input.lower() == "/exit" or user_input.lower() == "/bye":
            console.print(Rule(style="orange3"))
            console.print(Markdown(" **Exiting Agent Glace...** "))
            console.print(Rule(style="orange3"))

            subprocess.run(["ollama", "stop", model_name])

            break

        elif user_input.lower() == "/list":
            console.print('''
List Options:
[1] - List Available Models
[2] - List Running Models
            ''')

            list_input = console.input("\nEnter Option (e.g. 1): ")
            if list_input.lower() == "1":
                ollama_list_models()
            elif list_input.lower() == "2":
                ollama_list_running()

            continue

        elif user_input.lower() == "/model":
            pass

        messages.append(
            {
                'role': 'user',
                'content': user_input
            }
        )

        stream =client.chat(
            model=model_name,
            messages=messages,
            stream=True,
            think=False
        )

        def render_stream(response_stream):
            thinking_txt = ""
            response_txt = ""

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
                        renderables.append(Text(response_txt))

                    if renderables:
                        live.update(Group(*renderables))

            console.print()

            timestamp_now = datetime.now()
            timestamp_now_formatted = timestamp_now.strftime("%H:%M")

            with open(session_transcript_fl, "a", encoding="utf-8", errors="replace") as f:
                #f.write(timestamp_now_formatted)

                f.write("\n\n**USER:** \n")
                f.write(user_input)
                f.write("\n\n")

                f.write("**GLACE:** \n")
                f.write(response_txt)
                f.write("\n\n")

            return response_txt

        response_txt = render_stream(stream)
        messages.append(
            {
                'role': 'assistant',
                'content': response_txt
            }
        )

if __name__ == "__main__":
    main_loop()