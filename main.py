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
transcript_fl = os.path.join(script_dir, "storage", "transcripts", "transcript.md")

## FUNCTIONS

def ollama_list_models():
    model_list_raw = client.list()

    print("\nAvailable Models:\n")

    for model in model_list_raw.get('models', []):
        print(model.get('model'))

def ollama_list_running():
    ps_list_raw = client.ps()

    print("\nRunning Models:\n")

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

    def check_model_choice():
        try:
            with open (model_config_fl, "r") as f:
                model_name = f.read()

                console.print(Markdown(f"Model Selected: **{model_name}**"))
                console.print(Rule(style="orange3"))

                messages = [
                    {
                        'role': 'system',
                        'content': ''''''
                    }
                ]

        except FileNotFoundError:
            pass

    '''
    if check_model_choice() == "1":
        model_name = "oamazonasgabriel/lfm2.5-2.6b:q4_k_m-8gbGPU"

        console.print(Markdown(f"Model Selected: **LFM 2.5 (2.6B)**"))
        console.print(Rule(style="orange3"))

        messages = [
            {
                'role': 'system',
                'content': ''''''
            }
        ]
    '''

    while True:
        console.print()
        console.print(Rule(style="orange4"))
        user_input = console.input("[bold green]>>> [/bold green]")
        console.print(Rule(style="orange4"))
        console.print()

        if user_input.lower() == "/exit" or "/bye":
            console.print(Rule(style="orange3"))
            console.print(Markdown(" **Exiting Agent Glace...** "))
            console.print(Rule(style="orange3"))

            subprocess.run(["ollama", "stop", "oamazonasgabriel/lfm2.5-2.6b:q4_k_m-8gbGPU"])

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
            think=True
        )

        def render_stream(response_stream):
            thinking_txt = ""
            response_txt = ""

            with Live(console=console, refresh_per_second=10, transient=False) as live:
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
            timestamp_now_formatted = timestamp_now.strftime("%H:%M:%S, %B %d, %Y")

            with open(transcript_fl, "a", encoding="utf-8", errors="replace") as f:
                f.write(timestamp_now_formatted)

                f.write("\n\n**USER:** \n")
                f.write(user_input)
                f.write("\n\n")

                f.write("**GLACE:** \n")
                f.write(response_txt)
                f.write("\n\n")

        render_stream(stream)

if __name__ == "__main__":
    main_loop()