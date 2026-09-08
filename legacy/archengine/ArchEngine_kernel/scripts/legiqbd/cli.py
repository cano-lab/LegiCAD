"""Command-line interface for LegiQBD.

Interactive terminal interface for conversational building design.
"""

import sys
import argparse
from pathlib import Path

# Setup path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm import LLMConfig
from .session import Session, SessionConfig
from .engine import ConversationEngine
from .formatter import ResponseFormatter, OutputFormat
from .visualizer import ASCIIVisualizer, quick_preview


class LegiQBDCLI:
    """Interactive CLI for LegiQBD."""

    def __init__(self, verbose: bool = False, markdown: bool = False):
        self.verbose = verbose

        # Setup components
        config = SessionConfig(verbose=verbose)
        self.session = Session(config=config)

        self.engine = ConversationEngine(session=self.session)

        fmt = OutputFormat.MARKDOWN if markdown else OutputFormat.TEXT
        self.formatter = ResponseFormatter(format=fmt)

        self.visualizer = ASCIIVisualizer()

        # State
        self.running = True

    def run(self):
        """Run the interactive CLI."""
        self._print_header()

        # Check LLM availability
        if not self._check_llm():
            return

        # Start conversation
        response = self.engine.start_conversation()
        self._print_response(response)

        # Main loop
        while self.running:
            try:
                user_input = self._get_input()

                if not user_input:
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    self._handle_command(user_input)
                    continue

                # Process input
                response = self.engine.process_input(user_input)
                self._print_response(response)

                # Show layout if solved
                if response.is_solved and self.session.solved_layout:
                    print("\n" + self.visualizer.render(self.session.solved_layout))

            except KeyboardInterrupt:
                print("\n\nInterrupted. Type /quit to exit.")
            except EOFError:
                break

        self._print_farewell()

    def _print_header(self):
        """Print welcome header."""
        print()
        print("=" * 60)
        print("  LegiQBD - Conversational Building Design")
        print("=" * 60)
        print()
        print("Type your message or use commands:")
        print("  /help     - Show help")
        print("  /status   - Show design status")
        print("  /rooms    - Show current rooms")
        print("  /layout   - Show floor plan")
        print("  /solve    - Force solve design")
        print("  /save     - Save session")
        print("  /quit     - Exit")
        print()
        print("-" * 60)

    def _print_farewell(self):
        """Print goodbye message."""
        print()
        print("-" * 60)
        print("Thanks for using LegiQBD!")
        print()

    def _check_llm(self) -> bool:
        """Check LLM availability."""
        status = LLMConfig.status()

        if not status.get("active"):
            print("ERROR: No LLM provider available.")
            print()
            print("Please configure an LLM provider:")
            print("  - Start LM Studio with a loaded model")
            print("  - Or set OPENAI_API_KEY environment variable")
            print("  - Or set ANTHROPIC_API_KEY environment variable")
            print()
            return False

        active = status.get("active", "unknown")
        print(f"Using LLM provider: {active}")
        print()
        return True

    def _get_input(self) -> str:
        """Get user input."""
        try:
            # Show phase indicator
            phase = self.session.phase.value.upper()
            prompt = f"[{phase}] You: "

            user_input = input(prompt).strip()
            return user_input

        except EOFError:
            self.running = False
            return ""

    def _print_response(self, response):
        """Print engine response."""
        print()

        # Progress bar
        progress = self.formatter.format_progress(
            response.phase,
            response.is_solvable,
            response.is_solved,
            self.session.room_count
        )
        print(progress)
        print()

        # Main response
        formatted = self.formatter.format_response(
            response.text,
            fragments_applied=response.fragments_applied,
            errors=response.errors,
            questions=response.questions,
            design_changed=response.design_changed
        )
        print("LegiQBD: " + formatted)

        # Questions
        if response.questions:
            print(self.formatter.format_questions(response.questions))

        print()

    def _handle_command(self, command: str):
        """Handle CLI command."""
        cmd = command.lower().strip()

        if cmd in ("/quit", "/exit", "/q"):
            self.running = False

        elif cmd in ("/help", "/h", "/?"):
            self._show_help()

        elif cmd in ("/status", "/s"):
            self._show_status()

        elif cmd in ("/rooms", "/r"):
            self._show_rooms()

        elif cmd in ("/layout", "/l"):
            self._show_layout()

        elif cmd in ("/solve"):
            self._force_solve()

        elif cmd.startswith("/save"):
            self._save_session(cmd)

        elif cmd.startswith("/load"):
            self._load_session(cmd)

        elif cmd in ("/debug", "/d"):
            self._show_debug()

        else:
            print(f"Unknown command: {command}")
            print("Type /help for available commands.")

    def _show_help(self):
        """Show help information."""
        print()
        print("LegiQBD Commands:")
        print("-" * 40)
        print("  /help, /h    - Show this help")
        print("  /status, /s  - Show current design status")
        print("  /rooms, /r   - List all rooms")
        print("  /layout, /l  - Show floor plan visualization")
        print("  /solve       - Manually trigger solver")
        print("  /save [file] - Save session to file")
        print("  /load [file] - Load session from file")
        print("  /debug, /d   - Show debug information")
        print("  /quit, /q    - Exit LegiQBD")
        print()
        print("Tips:")
        print("  - Describe your home naturally: '3 bedroom 2 bath house'")
        print("  - Make changes: 'make the kitchen bigger'")
        print("  - Ask questions: 'how big is the living room?'")
        print()

    def _show_status(self):
        """Show design status."""
        summary = self.session.get_state_summary()

        print()
        print("Design Status")
        print("-" * 40)
        print(f"Session: {summary['session_id']}")
        print(f"Phase: {summary['phase']}")
        print(f"Lifecycle: {summary['lifecycle']}")
        print(f"Rooms: {summary['rooms']['count']}")
        print(f"Adjacencies: {summary['adjacencies']}")
        print(f"Solvable: {summary['is_solvable']}")
        print(f"Solved: {summary['is_solved']}")
        print(f"Solve count: {summary['solve_count']}")
        print()

    def _show_rooms(self):
        """Show current rooms."""
        rooms = self.session.qbd_state.rooms

        print()
        print(quick_preview(rooms))
        print()

    def _show_layout(self):
        """Show floor plan visualization."""
        if self.session.is_solved and self.session.solved_layout:
            print()
            print(self.visualizer.render(self.session.solved_layout))
            print()
        else:
            rooms = self.session.qbd_state.rooms
            if rooms:
                print()
                print(self.visualizer.render_simple(rooms))
                print()
                print("(Layout not yet solved - positions are approximate)")
            else:
                print()
                print("No rooms defined yet.")
            print()

    def _force_solve(self):
        """Manually trigger solver."""
        if not self.session.is_solvable:
            print()
            print("Cannot solve yet - need more information.")
            print("Required: rooms, footprint constraint")
            print()
            return

        print()
        print("Solving...")
        success, result = self.engine.solve()

        if success:
            print("Solved!")
            print(f"Score: {result.get('score', 0):.1f}/10")
            print()
            print(self.visualizer.render(result.get('layout', {})))
        else:
            print(f"Failed: {result.get('error', 'Unknown error')}")
            if result.get('message'):
                print(result['message'])
        print()

    def _save_session(self, command: str):
        """Save session to file."""
        parts = command.split(maxsplit=1)
        filename = parts[1] if len(parts) > 1 else f"session_{self.session.id}.json"

        try:
            with open(filename, "w") as f:
                f.write(self.session.to_json())
            print(f"Saved to: {filename}")
        except Exception as e:
            print(f"Error saving: {e}")

    def _load_session(self, command: str):
        """Load session from file."""
        parts = command.split(maxsplit=1)
        if len(parts) < 2:
            print("Usage: /load <filename>")
            return

        filename = parts[1]
        try:
            import json
            with open(filename, "r") as f:
                data = json.load(f)
            self.session = Session.from_dict(data)
            self.engine.session = self.session
            print(f"Loaded: {filename}")
            self._show_status()
        except Exception as e:
            print(f"Error loading: {e}")

    def _show_debug(self):
        """Show debug information."""
        print()
        print("Debug Information")
        print("=" * 60)

        # LLM status
        print("\nLLM Providers:")
        status = LLMConfig.status()
        for name, info in status.get("providers", {}).items():
            available = "YES" if info.get("available") else "NO"
            active = " (ACTIVE)" if name == status.get("active") else ""
            print(f"  {name}: {available}{active}")

        # Session state
        print("\nSession State:")
        print(f"  ID: {self.session.id}")
        print(f"  Messages: {len(self.session.messages)}")
        print(f"  Questions asked: {len(self.session.questions_asked)}")

        # QBD state
        state = self.session.qbd_state
        print("\nQBD State:")
        print(f"  Lifecycle: {state.lifecycle.value}")
        print(f"  Rooms: {len(state.rooms)}")
        print(f"  Adjacencies: {len(state.adjacencies)}")
        print(f"  Constraints: {state.constraints}")

        # Last intent
        if self.engine.last_intent:
            intent = self.engine.last_intent
            print("\nLast Intent:")
            print(f"  Type: {intent.intent}")
            print(f"  Confidence: {intent.confidence:.2f}")
            print(f"  Entities: {intent.entities}")

        print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LegiQBD - Conversational Building Design"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )
    parser.add_argument(
        "-m", "--markdown",
        action="store_true",
        help="Use markdown formatting"
    )
    parser.add_argument(
        "--provider",
        choices=["lmstudio", "openai", "anthropic", "google"],
        help="LLM provider to use"
    )

    args = parser.parse_args()

    # Set provider if specified
    if args.provider:
        try:
            LLMConfig.set_active(args.provider)
        except Exception as e:
            print(f"Error setting provider: {e}")
            return 1

    # Run CLI
    cli = LegiQBDCLI(verbose=args.verbose, markdown=args.markdown)
    cli.run()

    return 0


if __name__ == "__main__":
    sys.exit(main())
