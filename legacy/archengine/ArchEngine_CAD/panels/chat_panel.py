"""
Chat Panel - Interface for LLM-driven design

Provides a conversational interface for modifying building designs.
When LLM layer is available, connects to providers for AI-assisted design.
"""
from typing import Optional, List, Dict, Any
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QLineEdit, QPushButton, QLabel, QComboBox, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot

from core.document import ArchDocument
from core.events import event_bus


# Try to import LLM layer (may not be available)
LLM_AVAILABLE = False
try:
    import sys
    llm_path = Path(__file__).parent.parent.parent / "ArchEngine_kernel" / "scripts"
    if llm_path.exists():
        sys.path.insert(0, str(llm_path))
        from llm import LLMConfig, TemplateModifier, SchemaGenerator
        LLM_AVAILABLE = True
except ImportError:
    pass


class LLMWorker(QThread):
    """Background thread for LLM calls."""
    finished = pyqtSignal(dict, str)  # modified schema, description
    error = pyqtSignal(str)           # error message

    def __init__(self, modifier, schema, message, pinned):
        super().__init__()
        self.modifier = modifier
        self.schema = schema
        self.message = message
        self.pinned = pinned

    def run(self):
        try:
            # TemplateModifier returns (schema, description)
            modified, description = self.modifier.modify(
                self.schema,
                self.message,
                pinned_elements=self.pinned
            )
            self.finished.emit(modified, description)
        except Exception as e:
            self.error.emit(str(e))


class ChatPanel(QWidget):
    """Panel for conversational design with LLM."""

    # Signals
    message_sent = pyqtSignal(str)  # user message
    schema_updated = pyqtSignal(dict)  # Emitted when LLM updates schema
    onboarding_complete = pyqtSignal(dict)  # Emitted when onboarding finishes with extracted data
    onboarding_progress = pyqtSignal(int, int)  # Emitted on progress (current, total)

    def __init__(self, document: ArchDocument, parent=None):
        super().__init__(parent)
        self.document = document
        self._selected_items: List[Any] = []
        self._worker: Optional[LLMWorker] = None

        # LLM components (initialized if available)
        self.modifier = None
        self.generator = None

        self._setup_ui()
        self._connect_signals()
        self._init_llm()

    def _setup_ui(self):
        """Set up the panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # Header with provider selector
        header = QHBoxLayout()
        header.addWidget(QLabel("Design Chat"))
        header.addStretch()

        self.provider_combo = QComboBox()
        self.provider_combo.setMinimumWidth(120)
        self.provider_combo.currentTextChanged.connect(self._on_provider_changed)
        header.addWidget(self.provider_combo)

        # Status indicator
        self.status_label = QLabel("●")
        self.status_label.setStyleSheet("color: gray;")
        self.status_label.setToolTip("Status")
        header.addWidget(self.status_label)

        layout.addLayout(header)

        # Chat history
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 5px;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        layout.addWidget(self.chat_history, stretch=1)

        # Progress bar (hidden by default)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(3)
        layout.addWidget(self.progress)

        # Input area
        input_layout = QHBoxLayout()

        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Describe design changes...")
        self.input_field.returnPressed.connect(self._on_send)
        self.input_field.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 1px solid #555;
                border-radius: 4px;
                background: #2d2d2d;
                color: #fff;
            }
        """)
        input_layout.addWidget(self.input_field, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._on_send)
        self.send_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 16px;
                background: #0078d4;
                color: white;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background: #1084d8; }
            QPushButton:disabled { background: #555; }
        """)
        input_layout.addWidget(self.send_btn)

        layout.addLayout(input_layout)

        # Context indicator
        self.context_label = QLabel("No selection | None pinned")
        self.context_label.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(self.context_label)

    def _init_llm(self):
        """Initialize LLM if available."""
        self.provider_combo.clear()

        if not LLM_AVAILABLE:
            self.provider_combo.addItem("LLM not available")
            self.provider_combo.setEnabled(False)
            self._set_status("gray", "LLM layer not found")
            self._add_message("System",
                "LLM integration not available. Messages will show debug info only.",
                "#888")
            return

        try:
            LLMConfig.register_defaults()
            available = LLMConfig.get_available()

            if not available:
                self.provider_combo.addItem("No providers")
                self.provider_combo.setEnabled(False)
                self._set_status("orange", "No LLM providers configured")
                self._add_message("System",
                    "No LLM providers available. Start LM Studio or set API keys.",
                    "#ffaa00")
                return

            for name, provider in available.items():
                self.provider_combo.addItem(provider.name, name)

            self.provider_combo.setEnabled(True)
            self._set_status("green", "Ready")

            # Initialize modifier with default provider (TemplateModifier is faster)
            self.modifier = TemplateModifier()
            self.generator = SchemaGenerator()

        except Exception as e:
            self.provider_combo.addItem("Error")
            self.provider_combo.setEnabled(False)
            self._set_status("red", f"Init error: {e}")

    def _connect_signals(self):
        """Connect to document and event signals."""
        self.document.element_pinned.connect(self._update_context)
        self.document.document_changed.connect(self._update_context)
        event_bus.selection_changed.connect(self._on_selection_changed)

    def _on_selection_changed(self, selected_items: List):
        """Handle selection change from event bus."""
        self._selected_items = selected_items
        self._update_context()

    def _on_provider_changed(self, display_name: str):
        """Handle provider selection change."""
        if not LLM_AVAILABLE:
            return

        idx = self.provider_combo.currentIndex()
        provider_key = self.provider_combo.itemData(idx)
        if provider_key:
            try:
                LLMConfig.set_active(provider_key)
                self.modifier = SchemaModifier()
                self.generator = SchemaGenerator()
                self._set_status("green", f"Using {display_name}")
            except Exception as e:
                self._set_status("red", f"Error: {e}")

    def _set_status(self, color: str, tooltip: str):
        """Set status indicator."""
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setToolTip(tooltip)

    def _on_send(self):
        """Handle send button click."""
        message = self.input_field.text().strip()
        if not message:
            return

        # Add user message to history
        self._add_message("You", message, "#6baaff")
        self.input_field.clear()

        # Emit signal for external handlers
        self.message_sent.emit(message)

        # Check if in onboarding mode
        if self.is_onboarding:
            self._process_onboarding_response(message)
            return

        # Normal mode - Get current state
        pinned = self.document.get_pinned_elements()
        pinned_count = sum(len(v) for v in pinned.values())

        if LLM_AVAILABLE and self.modifier:
            # Run LLM in background
            self._run_llm(message, pinned)
        else:
            # Debug mode - show what would happen
            self._show_debug_response(message, pinned, pinned_count)

    def _run_llm(self, message: str, pinned: Dict):
        """Run LLM modification in background thread."""
        self._set_processing(True)

        pinned_count = sum(len(v) for v in pinned.values())
        if pinned_count > 0:
            self._add_message("System", f"Respecting {pinned_count} pinned element(s)", "#888")

        schema = self.document.to_json()
        self._worker = LLMWorker(self.modifier, schema, message, pinned)
        self._worker.finished.connect(self._on_llm_success)
        self._worker.error.connect(self._on_llm_error)
        self._worker.start()

    def _show_debug_response(self, message: str, pinned: Dict, pinned_count: int):
        """Show debug response when LLM not available."""
        response = f"[Debug] Would process: '{message}'\n"
        response += f"Pinned elements: {pinned_count}\n"

        if pinned_count > 0:
            for elem_type, ids in pinned.items():
                if ids:
                    response += f"  - {elem_type}: {', '.join(ids)}\n"

        # Show selection context
        if self._selected_items:
            response += f"Selected: {len(self._selected_items)} item(s)"

        self._add_message("Assistant", response.strip(), "#aaa")

    @pyqtSlot(dict, str)
    def _on_llm_success(self, modified_schema: dict, description: str):
        """Handle successful LLM response."""
        self._set_processing(False)

        # Update document
        self.document.load_from_dict(modified_schema)

        # Notify success with LLM's description of what changed
        self._add_message("Assistant", description or "Design updated.", "#6bff6b")

        # Emit signal for other components
        self.schema_updated.emit(modified_schema)

    @pyqtSlot(str)
    def _on_llm_error(self, error: str):
        """Handle LLM error."""
        self._set_processing(False)
        self._add_message("Error", error, "#ff6b6b")
        self._set_status("red", f"Error: {error[:50]}")

    def _set_processing(self, processing: bool):
        """Set UI processing state."""
        self.input_field.setEnabled(not processing)
        self.send_btn.setEnabled(not processing)
        self.progress.setVisible(processing)

        if processing:
            self._set_status("yellow", "Processing...")
        else:
            self._set_status("green", "Ready")

    def _add_message(self, sender: str, message: str, color: str = "#d4d4d4"):
        """Add a message to the chat history."""
        # Escape HTML in message but preserve newlines
        escaped = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        escaped = escaped.replace("\n", "<br>")
        self.chat_history.append(
            f'<span style="color: {color};"><b>{sender}:</b> {escaped}</span>'
        )

    def add_response(self, message: str):
        """Add assistant response to chat (public API)."""
        self._add_message("Assistant", message, "#6bff6b")

    def set_context(self, context: str):
        """Update context indicator (public API)."""
        self.context_label.setText(context)

    def update_selection_context(self, selected_items: List):
        """Update context based on selection (public API)."""
        self._selected_items = selected_items
        self._update_context()

    def _update_context(self):
        """Update the context label."""
        # Selection info
        if not self._selected_items:
            select_str = "No selection"
        elif len(self._selected_items) == 1:
            item = self._selected_items[0]
            item_type = type(item).__name__.replace("Item", "")
            select_str = f"{item_type} selected"
        else:
            select_str = f"{len(self._selected_items)} elements selected"

        # Pinned info
        pinned = self.document.get_pinned_elements()
        pinned_count = sum(len(v) for v in pinned.values())
        pin_str = f"{pinned_count} pinned" if pinned_count > 0 else "None pinned"

        self.context_label.setText(f"{select_str} | {pin_str}")

    # =========================================================================
    # Onboarding Mode
    # =========================================================================

    def start_onboarding(self):
        """
        Start onboarding mode - LLM asks questions to understand requirements.

        In onboarding mode:
        1. LLM asks an opening question
        2. User responds
        3. LLM analyzes and asks follow-up (up to 3 questions)
        4. After 3 questions, generates building from collected info
        """
        self._onboarding_mode = True
        self._onboarding_turn = 0
        self._onboarding_max = 3
        self._onboarding_data = {}
        self._onboarding_history = []

        # Update placeholder
        self.input_field.setPlaceholderText("Tell me about your dream home...")

        # Clear chat and show welcome
        self.chat_history.clear()
        self._add_message("System", "Starting design conversation...", "#888")

        # Ask first question
        self._ask_onboarding_question()

    def _ask_onboarding_question(self):
        """Ask the next onboarding question using LLM."""
        from onboarding.question_bank import get_question_bank_text, ONBOARDING_SYSTEM_PROMPT

        self._onboarding_turn += 1

        # Emit progress signal
        self.onboarding_progress.emit(self._onboarding_turn, self._onboarding_max)

        # Build context from previous turns
        context_lines = []
        for turn in self._onboarding_history:
            context_lines.append(f"Q: {turn['question']}")
            context_lines.append(f"A: {turn['response']}")
            if turn.get('extracted'):
                context_lines.append(f"   [Extracted: {turn['extracted']}]")

        previous_context = "\n".join(context_lines) if context_lines else "This is the first question."

        # Build system prompt
        system_prompt = ONBOARDING_SYSTEM_PROMPT.format(
            question_bank=get_question_bank_text(),
            question_number=self._onboarding_turn,
            previous_context=previous_context
        )

        if LLM_AVAILABLE and self.modifier:
            # Use LLM to generate question
            self._generate_onboarding_question(system_prompt)
        else:
            # Fallback questions
            fallback = [
                "What kind of space are you dreaming of creating today?",
                "Who will be living in this home and what are their needs?",
                "What's most important to you - open spaces, natural light, or cozy defined rooms?"
            ]
            idx = min(self._onboarding_turn - 1, len(fallback) - 1)
            self._add_message("Assistant", fallback[idx], "#6bff6b")

    def _generate_onboarding_question(self, system_prompt: str):
        """Generate onboarding question using LLM."""
        from .chat_panel import LLMWorker  # Avoid circular import

        # For onboarding, we use a simpler direct call
        try:
            provider = LLMConfig.get_active() if LLM_AVAILABLE else None
            if provider:
                from llm.provider import Message
                messages = [
                    Message("system", system_prompt),
                    Message("user", f"Ask question {self._onboarding_turn} of {self._onboarding_max}.")
                ]
                response = provider.chat(messages)
                question = response.content.strip()
                self._add_message("Assistant", question, "#6bff6b")
                self._current_onboarding_question = question
            else:
                self._ask_fallback_question()
        except Exception as e:
            print(f"[Chat] Onboarding LLM error: {e}")
            self._ask_fallback_question()

    def _ask_fallback_question(self):
        """Ask fallback question when LLM unavailable."""
        fallback = [
            "What kind of space are you dreaming of creating today?",
            "Who will be living here and what rooms do you need?",
            "Any specific style or features that are important to you?"
        ]
        idx = min(self._onboarding_turn - 1, len(fallback) - 1)
        question = fallback[idx]
        self._add_message("Assistant", question, "#6bff6b")
        self._current_onboarding_question = question

    def _process_onboarding_response(self, user_response: str):
        """Process user response in onboarding mode."""
        from onboarding.onboarding_manager import OnboardingManager

        # Extract data from response
        manager = OnboardingManager()
        extracted = manager._extract_data(user_response)

        # Store this turn
        self._onboarding_history.append({
            "question": getattr(self, '_current_onboarding_question', ''),
            "response": user_response,
            "extracted": extracted
        })

        # Merge extracted data
        self._onboarding_data.update(extracted)

        # Check if done
        if self._onboarding_turn >= self._onboarding_max:
            self._complete_onboarding()
        else:
            # Ask next question
            self._ask_onboarding_question()

    def _complete_onboarding(self):
        """Complete onboarding and generate building."""
        self._onboarding_mode = False

        # Show completion message
        self._add_message("System",
            f"Great! I've gathered enough information. Let me generate your design...",
            "#6bff6b")

        # Build requirements summary
        data = self._onboarding_data
        summary = []
        if data.get('bedrooms'):
            summary.append(f"{data['bedrooms']} bedrooms")
        if data.get('bathrooms'):
            summary.append(f"{data['bathrooms']} bathrooms")
        if data.get('sqft'):
            summary.append(f"{data['sqft']} sq ft")
        if data.get('style'):
            summary.append(f"{data['style']} style")
        if data.get('special_rooms'):
            summary.append(f"with {', '.join(data['special_rooms'])}")

        if summary:
            self._add_message("System", f"Design requirements: {', '.join(summary)}", "#888")

        # Emit signal for building generation
        self.onboarding_complete.emit(self._onboarding_data)

        # Reset placeholder
        self.input_field.setPlaceholderText("Describe design changes...")

    @property
    def is_onboarding(self) -> bool:
        """Check if in onboarding mode."""
        return getattr(self, '_onboarding_mode', False)
