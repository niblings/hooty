#!/usr/bin/env python3
"""
Rich Library - Terminal Prompt Examples
Demonstrates various Rich library features for beautiful terminal UIs
"""

from rich.console import Console
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.markdown import Markdown
from rich import print as rprint
import time

console = Console()


def basic_prompts():
    """Basic prompt examples"""
    console.print("\n[bold cyan]═══ Basic Prompts ═══[/bold cyan]\n")
    
    # Simple text prompt
    name = Prompt.ask("What is your [bold green]name[/bold green]?")
    console.print(f"Hello, [bold]{name}[/bold]! 👋")
    
    # Prompt with default value
    language = Prompt.ask(
        "What's your favorite programming language?",
        default="Python"
    )
    console.print(f"Great choice: [yellow]{language}[/yellow]")
    
    # Integer prompt
    age = IntPrompt.ask("How old are you?", default=25)
    console.print(f"Age: [blue]{age}[/blue]")
    
    # Confirm (yes/no)
    likes_rich = Confirm.ask("Do you like the Rich library?")
    if likes_rich:
        console.print("[green]Awesome! 🎉[/green]")
    else:
        console.print("[yellow]Give it a try! 😊[/yellow]")


def choice_prompts():
    """Prompts with choices"""
    console.print("\n[bold cyan]═══ Choice Prompts ═══[/bold cyan]\n")
    
    # Prompt with limited choices
    color = Prompt.ask(
        "Choose a color",
        choices=["red", "green", "blue", "yellow"],
        default="blue"
    )
    console.print(f"You selected: [{color}]{color}[/{color}]")
    
    # Password prompt (hidden input)
    # Uncomment to test:
    # password = Prompt.ask("Enter password", password=True)
    # console.print("Password received! ✓")


def styled_prompts():
    """Styled prompts with panels and formatting"""
    console.print("\n[bold cyan]═══ Styled Prompts ═══[/bold cyan]\n")
    
    # Panel with prompt
    console.print(Panel.fit(
        "[bold magenta]Welcome to the Configuration Wizard![/bold magenta]\n"
        "Please answer the following questions:",
        border_style="magenta"
    ))
    
    # Multiple styled prompts
    config = {}
    config['project'] = Prompt.ask("📦 [bold]Project name[/bold]")
    config['version'] = Prompt.ask("🔢 [bold]Version[/bold]", default="1.0.0")
    config['author'] = Prompt.ask("👤 [bold]Author[/bold]")
    
    # Display configuration in a table
    table = Table(title="Configuration Summary", show_header=True)
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value", style="magenta")
    
    for key, value in config.items():
        table.add_row(key.capitalize(), value)
    
    console.print("\n", table)


def progress_demo():
    """Progress bars and spinners"""
    console.print("\n[bold cyan]═══ Progress & Spinners ═══[/bold cyan]\n")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Processing...", total=None)
        time.sleep(2)
        progress.update(task, description="[green]Complete! ✓")


def rich_print_demo():
    """Rich print examples"""
    console.print("\n[bold cyan]═══ Rich Print Features ═══[/bold cyan]\n")
    
    # Styled text
    rprint("[bold red]Bold Red[/bold red]")
    rprint("[italic green]Italic Green[/italic green]")
    rprint("[bold yellow on blue]Yellow on Blue[/bold yellow on blue]")
    
    # Emoji support
    rprint("✨ [bold]Emoji support![/bold] 🚀 💻 🎨")
    
    # Links (will be clickable in supported terminals)
    rprint("[link=https://github.com/Textualize/rich]Rich on GitHub[/link]")
    
    # Print Python objects
    data = {
        "name": "Rich",
        "version": "13.0",
        "features": ["Colors", "Tables", "Progress", "Syntax"],
        "awesome": True
    }
    rprint("\n[bold]Python Dictionary:[/bold]")
    rprint(data)


def syntax_demo():
    """Syntax highlighting"""
    console.print("\n[bold cyan]═══ Syntax Highlighting ═══[/bold cyan]\n")
    
    code = '''
def greet(name: str) -> str:
    """Greet someone by name"""
    return f"Hello, {name}!"

if __name__ == "__main__":
    print(greet("World"))
'''
    
    syntax = Syntax(code, "python", theme="monokai", line_numbers=True)
    console.print(syntax)


def markdown_demo():
    """Markdown rendering"""
    console.print("\n[bold cyan]═══ Markdown Rendering ═══[/bold cyan]\n")
    
    markdown_text = """
# Rich Library

## Features

- **Beautiful** terminal output
- *Easy* to use
- `Code` highlighting
- Tables, progress bars, and more!

### Installation

```bash
pip install rich
```

> Rich is a Python library for rich text and beautiful formatting in the terminal.
"""
    
    md = Markdown(markdown_text)
    console.print(md)


def interactive_menu():
    """Interactive menu example"""
    console.print("\n[bold cyan]═══ Interactive Menu ═══[/bold cyan]\n")
    
    while True:
        console.print(Panel(
            "[1] Basic Prompts\n"
            "[2] Choice Prompts\n"
            "[3] Styled Prompts\n"
            "[4] Progress Demo\n"
            "[5] Rich Print Demo\n"
            "[6] Syntax Highlighting\n"
            "[7] Markdown Rendering\n"
            "[8] Exit",
            title="[bold]Demo Menu[/bold]",
            border_style="green"
        ))
        
        choice = Prompt.ask(
            "Select an option",
            choices=["1", "2", "3", "4", "5", "6", "7", "8"],
            default="8"
        )
        
        if choice == "1":
            basic_prompts()
        elif choice == "2":
            choice_prompts()
        elif choice == "3":
            styled_prompts()
        elif choice == "4":
            progress_demo()
        elif choice == "5":
            rich_print_demo()
        elif choice == "6":
            syntax_demo()
        elif choice == "7":
            markdown_demo()
        elif choice == "8":
            console.print("\n[bold green]Goodbye! 👋[/bold green]\n")
            break
        
        if choice != "8":
            Prompt.ask("\n[dim]Press Enter to continue[/dim]", default="")
            console.clear()


def main():
    """Main function"""
    console.clear()
    
    # Title
    console.print(Panel.fit(
        "[bold magenta]Rich Library Terminal Prompt Demo[/bold magenta]\n"
        "[dim]Beautiful terminal interfaces made easy[/dim]",
        border_style="magenta"
    ))
    
    # Run interactive menu
    interactive_menu()


if __name__ == "__main__":
    main()