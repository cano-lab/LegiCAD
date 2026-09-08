"""Conversation engine for LegiQBD.

Orchestrates the LLM and QBD systems to have natural conversations
about building design. The engine:
1. Takes user input
2. Uses LLM to understand intent
3. Emits fragments to QBD
4. Generates questions
5. Formats natural responses
"""

import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

# Import QBD
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from qbd import (
    QBDState, Fragment, FragmentParser, solve_state,
    generate_questions, validate_state, error_to_natural_language
)
from llm import LLMConfig, FragmentEmitter
from llm.provider import Message, LLMProvider

from .session import Session, SessionPhase


# =============================================================================
# Intent Classification
# =============================================================================

INTENT_PROMPT = """You are an intent classifier for a building design assistant.

Classify the user's message into ONE of these intents:
- describe_building: User is describing what they want (rooms, size, style)
- modify_design: User wants to change something specific
- ask_question: User is asking about their design or options
- answer_question: User is responding to a question we asked
- confirm: User is confirming or approving something
- reject: User is rejecting or wants to undo something
- greeting: User is saying hello or starting
- farewell: User is saying goodbye or ending
- help: User needs help or is confused
- other: Doesn't fit other categories

Also extract any specific entities mentioned (rooms, sizes, styles, etc).

Output JSON only:
{
    "intent": "...",
    "confidence": 0.0-1.0,
    "entities": {
        "rooms": [...],
        "sizes": [...],
        "styles": [...],
        "modifications": [...],
        "questions": [...]
    },
    "sentiment": "positive|neutral|negative"
}
"""

RESPONSE_PROMPT = """You are a friendly, knowledgeable home design assistant for LegiQBD.

Your personality:
- Warm and conversational, not robotic
- Knowledgeable about home design but accessible
- Ask clarifying questions naturally
- Celebrate progress and good decisions
- Guide without being pushy

Current session state:
{state_summary}

Design status:
{design_summary}

User message: {user_message}

{intent_context}

{question_context}

Generate a natural, conversational response. Keep it concise (2-4 sentences typically).
If asking a question, make it feel natural in conversation.

Output only the response text, no JSON or formatting.
"""


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: str
    confidence: float
    entities: Dict[str, Any]
    sentiment: str
    raw: Dict[str, Any]


@dataclass
class EngineResponse:
    """Response from the conversation engine."""
    text: str
    fragments_applied: List[Dict]
    errors: List[str]
    questions: List[Dict]
    design_changed: bool
    phase: str
    is_solvable: bool
    is_solved: bool


# =============================================================================
# Conversation Engine
# =============================================================================

class ConversationEngine:
    """Orchestrates conversation between user, LLM, and QBD."""

    def __init__(
        self,
        session: Session = None,
        provider: LLMProvider = None,
        auto_solve: bool = True
    ):
        self.session = session or Session()
        self.provider = provider
        self.auto_solve = auto_solve
        self.fragment_emitter = FragmentEmitter(provider)

        # Conversation tracking
        self.pending_questions: List[Dict] = []
        self.last_intent: Optional[IntentResult] = None

    def _get_provider(self) -> LLMProvider:
        """Get LLM provider."""
        if self.provider:
            return self.provider
        provider = LLMConfig.get_active()
        if not provider:
            raise RuntimeError("No LLM provider available")
        return provider

    # =========================================================================
    # Main Interface
    # =========================================================================

    def process_input(self, user_input: str) -> EngineResponse:
        """Process user input and generate response.

        This is the main entry point for the conversation engine.

        Args:
            user_input: The user's message

        Returns:
            EngineResponse with text, changes, and status
        """
        # Add user message to history
        self.session.add_user_message(user_input)

        # Classify intent
        intent = self._classify_intent(user_input)
        self.last_intent = intent

        # Route based on intent
        if intent.intent == "greeting":
            response = self._handle_greeting(user_input, intent)

        elif intent.intent == "describe_building":
            response = self._handle_description(user_input, intent)

        elif intent.intent == "modify_design":
            response = self._handle_modification(user_input, intent)

        elif intent.intent == "answer_question":
            response = self._handle_answer(user_input, intent)

        elif intent.intent == "ask_question":
            response = self._handle_user_question(user_input, intent)

        elif intent.intent == "confirm":
            response = self._handle_confirm(user_input, intent)

        elif intent.intent == "reject":
            response = self._handle_reject(user_input, intent)

        elif intent.intent == "help":
            response = self._handle_help(user_input, intent)

        elif intent.intent == "farewell":
            response = self._handle_farewell(user_input, intent)

        else:
            response = self._handle_general(user_input, intent)

        # Add assistant response to history
        self.session.add_assistant_message(
            response.text,
            intent=intent.intent,
            fragments_applied=len(response.fragments_applied),
            errors=len(response.errors)
        )

        # Update phase
        self.session.advance_phase()

        return response

    def start_conversation(self) -> EngineResponse:
        """Start a new conversation with a greeting."""
        greeting = self._generate_greeting()

        self.session.add_assistant_message(greeting, intent="greeting")
        self.session.set_phase(SessionPhase.GREETING)

        return EngineResponse(
            text=greeting,
            fragments_applied=[],
            errors=[],
            questions=[],
            design_changed=False,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def solve(self) -> Tuple[bool, Dict[str, Any]]:
        """Attempt to solve the current design.

        Returns:
            Tuple of (success, result_dict)
        """
        if not self.session.is_solvable:
            return False, {"error": "Design is not ready to solve"}

        result = solve_state(self.session.qbd_state)

        if result.status == "solved":
            self.session.solve_count += 1
            self.session.set_phase(SessionPhase.REVIEWING)
            # Extract score from best candidate
            score = result.candidates[0].score if result.candidates else 0.0
            metrics = result.layout.get("metrics", {}) if result.layout else {}
            return True, {
                "layout": result.layout,
                "score": score,
                "metrics": metrics
            }
        else:
            # Extract error message from errors list
            message = result.errors[0].message if result.errors else "Solver failed"
            return False, {
                "error": result.status,
                "message": message
            }

    # =========================================================================
    # Intent Classification
    # =========================================================================

    def _classify_intent(self, user_input: str) -> IntentResult:
        """Classify user intent using LLM."""
        provider = self._get_provider()

        messages = [
            Message(role="system", content=INTENT_PROMPT),
            Message(role="user", content=user_input)
        ]

        response = provider.chat(messages, temperature=0.1, max_tokens=500)

        try:
            # Extract JSON from response
            content = response.content.strip()
            if "```" in content:
                import re
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
                if match:
                    content = match.group(1)

            data = json.loads(content)

            return IntentResult(
                intent=data.get("intent", "other"),
                confidence=data.get("confidence", 0.5),
                entities=data.get("entities", {}),
                sentiment=data.get("sentiment", "neutral"),
                raw=data
            )
        except json.JSONDecodeError:
            # Fallback: simple keyword matching
            return self._classify_intent_fallback(user_input)

    def _classify_intent_fallback(self, user_input: str) -> IntentResult:
        """Fallback intent classification using keywords."""
        text = user_input.lower()

        # Check for greetings
        if any(w in text for w in ["hello", "hi", "hey", "start"]):
            return IntentResult("greeting", 0.7, {}, "positive", {})

        # Check for farewell
        if any(w in text for w in ["bye", "goodbye", "done", "finish", "thanks"]):
            return IntentResult("farewell", 0.7, {}, "positive", {})

        # Check for help
        if any(w in text for w in ["help", "confused", "don't understand", "what"]):
            return IntentResult("help", 0.7, {}, "neutral", {})

        # Check for confirmation
        if any(w in text for w in ["yes", "ok", "sure", "sounds good", "confirm", "approve"]):
            return IntentResult("confirm", 0.7, {}, "positive", {})

        # Check for rejection
        if any(w in text for w in ["no", "don't", "cancel", "undo", "wrong"]):
            return IntentResult("reject", 0.7, {}, "negative", {})

        # Check for modification
        if any(w in text for w in ["change", "modify", "make", "add", "remove", "bigger", "smaller"]):
            return IntentResult("modify_design", 0.6, {}, "neutral", {})

        # Check for questions
        if "?" in text or text.startswith(("what", "how", "why", "can", "is", "are")):
            return IntentResult("ask_question", 0.6, {}, "neutral", {})

        # Default: assume describing building
        return IntentResult("describe_building", 0.5, {}, "neutral", {})

    # =========================================================================
    # Intent Handlers
    # =========================================================================

    def _handle_greeting(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle greeting intent."""
        self.session.set_phase(SessionPhase.DISCOVERY)

        response_text = self._generate_response(
            user_input,
            intent,
            "Welcome the user warmly. Ask what kind of home they're thinking about."
        )

        return EngineResponse(
            text=response_text,
            fragments_applied=[],
            errors=[],
            questions=[],
            design_changed=False,
            phase=self.session.phase.value,
            is_solvable=False,
            is_solved=False
        )

    def _handle_description(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle building description intent."""
        self.session.set_phase(SessionPhase.DISCOVERY)

        # Emit fragments from description
        fragments_applied = []
        errors = []

        try:
            fragments = self.fragment_emitter.emit_from_description(user_input)

            # Apply fragments to state
            for frag_data in fragments:
                try:
                    fragment = FragmentParser.parse(frag_data)
                    result = self.session.qbd_state.apply_fragment(fragment)

                    if result.valid:
                        fragments_applied.append(frag_data)
                    else:
                        for err in result.errors:
                            errors.append(error_to_natural_language(err))
                except Exception as e:
                    errors.append(str(e))

        except Exception as e:
            errors.append(f"Could not understand description: {e}")

        # Generate questions if needed
        questions = []
        if not self.session.is_solvable:
            questions = generate_questions(self.session.qbd_state, max_questions=2)
            self.pending_questions = questions

        # Auto-solve if ready
        solved = False
        if self.auto_solve and self.session.is_solvable and not self.session.is_solved:
            success, result = self.solve()
            solved = success

        # Generate response
        intent_context = f"Applied {len(fragments_applied)} changes to the design."
        if errors:
            intent_context += f" {len(errors)} issues: {'; '.join(errors[:2])}"
        if solved:
            intent_context += " Design has been solved!"

        question_context = ""
        if questions:
            q = questions[0]
            question_context = f"Ask about: {q.get('text', '')}"

        response_text = self._generate_response(
            user_input,
            intent,
            intent_context,
            question_context
        )

        return EngineResponse(
            text=response_text,
            fragments_applied=fragments_applied,
            errors=errors,
            questions=questions,
            design_changed=len(fragments_applied) > 0,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def _handle_modification(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle design modification intent."""
        self.session.set_phase(SessionPhase.MODIFYING)

        fragments_applied = []
        errors = []

        try:
            fragments = self.fragment_emitter.emit_for_modification(
                self.session.qbd_state,
                user_input
            )

            for frag_data in fragments:
                try:
                    fragment = FragmentParser.parse(frag_data)
                    result = self.session.qbd_state.apply_fragment(fragment)

                    if result.valid:
                        fragments_applied.append(frag_data)
                    else:
                        for err in result.errors:
                            errors.append(error_to_natural_language(err))
                except Exception as e:
                    errors.append(str(e))

        except Exception as e:
            errors.append(f"Could not process modification: {e}")

        # Re-solve if design was solved (fragments already invalidate solved state)
        if self.auto_solve and self.session.solve_count > 0 and self.session.is_solvable:
            success, result = self.solve()

        intent_context = f"Made {len(fragments_applied)} changes."
        if errors:
            intent_context += f" Issues: {'; '.join(errors[:2])}"

        response_text = self._generate_response(
            user_input,
            intent,
            intent_context
        )

        return EngineResponse(
            text=response_text,
            fragments_applied=fragments_applied,
            errors=errors,
            questions=[],
            design_changed=len(fragments_applied) > 0,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def _handle_answer(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle user answering a question."""
        # Try to apply answer as fragment
        fragments_applied = []
        errors = []

        if self.pending_questions:
            # Use LLM to interpret answer in context of question
            question = self.pending_questions[0]
            fragments = self._interpret_answer(question, user_input)

            for frag_data in fragments:
                try:
                    fragment = FragmentParser.parse(frag_data)
                    result = self.session.qbd_state.apply_fragment(fragment)
                    if result.valid:
                        fragments_applied.append(frag_data)
                except Exception as e:
                    errors.append(str(e))

            # Mark question as asked
            self.session.mark_question_asked(question.get("id", ""))
            self.pending_questions = self.pending_questions[1:]

        # Generate next question or confirm
        questions = []
        if not self.session.is_solvable:
            questions = generate_questions(self.session.qbd_state, max_questions=2)
            # Filter out already asked
            questions = [q for q in questions
                        if not self.session.was_question_asked(q.get("id", ""))]
            self.pending_questions = questions

        # Auto-solve if ready
        if self.auto_solve and self.session.is_solvable and not self.session.is_solved:
            self.solve()

        question_context = ""
        if questions:
            question_context = f"Next question: {questions[0].get('text', '')}"

        response_text = self._generate_response(
            user_input,
            intent,
            "User answered a question.",
            question_context
        )

        return EngineResponse(
            text=response_text,
            fragments_applied=fragments_applied,
            errors=errors,
            questions=questions,
            design_changed=len(fragments_applied) > 0,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def _handle_user_question(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle user asking a question about their design."""
        # Generate informative response
        response_text = self._generate_response(
            user_input,
            intent,
            "User is asking about their design. Provide helpful information based on current state."
        )

        return EngineResponse(
            text=response_text,
            fragments_applied=[],
            errors=[],
            questions=[],
            design_changed=False,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def _handle_confirm(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle user confirmation."""
        # If in reviewing, move to complete
        if self.session.phase == SessionPhase.REVIEWING:
            self.session.set_phase(SessionPhase.COMPLETE)
            response_text = self._generate_response(
                user_input,
                intent,
                "User confirmed the design. Congratulate them and explain next steps."
            )
        else:
            response_text = self._generate_response(
                user_input,
                intent,
                "User confirmed. Continue with the conversation."
            )

        return EngineResponse(
            text=response_text,
            fragments_applied=[],
            errors=[],
            questions=[],
            design_changed=False,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def _handle_reject(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle user rejection."""
        self.session.set_phase(SessionPhase.MODIFYING)

        response_text = self._generate_response(
            user_input,
            intent,
            "User wants to change something. Ask what they'd like to modify."
        )

        return EngineResponse(
            text=response_text,
            fragments_applied=[],
            errors=[],
            questions=[],
            design_changed=False,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def _handle_help(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle help request."""
        help_text = """I can help you design a home! Here's how we can work together:

1. **Describe your dream home** - Tell me about rooms, size, style
2. **Answer questions** - I'll ask about details to refine the design
3. **Make changes** - Say things like "make the kitchen bigger"
4. **Review the result** - I'll show you what we've created

What would you like to do?"""

        return EngineResponse(
            text=help_text,
            fragments_applied=[],
            errors=[],
            questions=[],
            design_changed=False,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def _handle_farewell(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle farewell."""
        response_text = self._generate_response(
            user_input,
            intent,
            "User is ending the session. Thank them warmly."
        )

        return EngineResponse(
            text=response_text,
            fragments_applied=[],
            errors=[],
            questions=[],
            design_changed=False,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    def _handle_general(self, user_input: str, intent: IntentResult) -> EngineResponse:
        """Handle general/unclear input."""
        # Try to understand as description if we're early in conversation
        if self.session.room_count == 0:
            return self._handle_description(user_input, intent)

        response_text = self._generate_response(
            user_input,
            intent,
            "The intent is unclear. Gently guide the user back to the design task."
        )

        return EngineResponse(
            text=response_text,
            fragments_applied=[],
            errors=[],
            questions=[],
            design_changed=False,
            phase=self.session.phase.value,
            is_solvable=self.session.is_solvable,
            is_solved=self.session.is_solved
        )

    # =========================================================================
    # Response Generation
    # =========================================================================

    def _generate_response(
        self,
        user_input: str,
        intent: IntentResult,
        intent_context: str = "",
        question_context: str = ""
    ) -> str:
        """Generate a natural response using LLM."""
        provider = self._get_provider()

        state_summary = json.dumps(self.session.get_state_summary(), indent=2)
        design_summary = self.session.get_design_summary()

        prompt = RESPONSE_PROMPT.format(
            state_summary=state_summary,
            design_summary=design_summary,
            user_message=user_input,
            intent_context=intent_context or "No specific context.",
            question_context=question_context or "No specific question to ask."
        )

        messages = [
            Message(role="user", content=prompt)
        ]

        # Include recent history for context
        history = self.session.get_history(limit=6)
        if history:
            context = "Recent conversation:\n"
            for msg in history[-6:-1]:  # Exclude current
                context += f"{msg['role'].upper()}: {msg['content'][:200]}...\n"
            messages.insert(0, Message(role="system", content=context))

        response = provider.chat(messages, temperature=0.7, max_tokens=500)

        return response.content.strip()

    def _generate_greeting(self) -> str:
        """Generate an initial greeting."""
        provider = self._get_provider()

        prompt = """You are LegiQBD, a friendly home design assistant.

Generate a warm, welcoming greeting for a new user.
- Introduce yourself briefly
- Express enthusiasm about helping them design their home
- Ask an open-ended question to get started

Keep it to 2-3 sentences. Be warm but not overly effusive."""

        messages = [Message(role="user", content=prompt)]
        response = provider.chat(messages, temperature=0.8, max_tokens=200)

        return response.content.strip()

    def _interpret_answer(self, question: Dict, answer: str) -> List[Dict]:
        """Interpret user's answer to a question as fragments."""
        provider = self._get_provider()

        prompt = f"""Question asked: {question.get('text', '')}
Target field: {question.get('target_field', '')}
Options: {json.dumps(question.get('options', []))}

User's answer: {answer}

Convert this answer into QBD fragments. Output a JSON array.
If the answer is a number or choice from options, use set_constraint.
If it's about rooms, use add_room or update_room.
If unclear, return empty array [].

Output only JSON."""

        messages = [Message(role="user", content=prompt)]
        response = provider.chat(messages, temperature=0.2, max_tokens=500)

        try:
            content = response.content.strip()
            if "```" in content:
                import re
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
                if match:
                    content = match.group(1)
            return json.loads(content)
        except:
            return []
