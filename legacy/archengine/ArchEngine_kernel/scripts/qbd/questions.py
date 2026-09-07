"""Question generator for QBD Algebra.

The question generator is the inverse of fragment processing.
Instead of taking answers and updating state, it reads state
and produces the next best questions to ask.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from .state import QBDState, StateLifecycle
from .defaults import ROOM_DEFAULTS


class QuestionCategory(Enum):
    """Question categories."""
    HOUSEHOLD = "household"
    PROGRAM = "program"
    ROOMS = "rooms"
    RELATIONSHIPS = "relationships"
    SITE = "site"
    PRIORITIES = "priorities"
    CHARACTER = "character"
    DETAILS = "details"


@dataclass
class QuestionOption:
    """An option for a question."""
    value: Any
    label: str
    description: Optional[str] = None


@dataclass
class Question:
    """A question to ask the user."""
    id: str
    text: str
    category: QuestionCategory
    target_field: str
    options: List[QuestionOption] = field(default_factory=list)
    default: Optional[Any] = None
    can_skip: bool = True
    impact: str = "medium"  # low, medium, high
    why: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    follow_ups: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "category": self.category.value,
            "target_field": self.target_field,
            "options": [{"value": o.value, "label": o.label, "description": o.description}
                       for o in self.options],
            "default": self.default,
            "can_skip": self.can_skip,
            "impact": self.impact,
            "why": self.why,
        }


# =============================================================================
# Question Pool
# =============================================================================

QUESTION_POOL: List[Question] = [
    # Household questions
    Question(
        id="q_household_adults",
        text="How many adults will live in the home?",
        category=QuestionCategory.HOUSEHOLD,
        target_field="metadata.household.adults",
        options=[
            QuestionOption(1, "1"),
            QuestionOption(2, "2"),
            QuestionOption(3, "3+"),
        ],
        default=2,
        impact="high",
        why="This helps determine bedroom count and bathroom needs",
    ),
    Question(
        id="q_household_kids",
        text="Any children? How many?",
        category=QuestionCategory.HOUSEHOLD,
        target_field="metadata.household.children",
        options=[
            QuestionOption(0, "None"),
            QuestionOption(1, "1"),
            QuestionOption(2, "2"),
            QuestionOption(3, "3+"),
        ],
        default=0,
        impact="high",
        why="Children need bedrooms and play spaces",
    ),

    # Program questions
    Question(
        id="q_bedrooms",
        text="How many bedrooms do you need?",
        category=QuestionCategory.PROGRAM,
        target_field="program.bedrooms",
        options=[
            QuestionOption(1, "1"),
            QuestionOption(2, "2"),
            QuestionOption(3, "3"),
            QuestionOption(4, "4"),
            QuestionOption(5, "5+"),
        ],
        default=3,
        impact="high",
        why="Core room count affects total size",
    ),
    Question(
        id="q_bathrooms",
        text="How many bathrooms?",
        category=QuestionCategory.PROGRAM,
        target_field="program.bathrooms",
        options=[
            QuestionOption(1, "1"),
            QuestionOption(1.5, "1.5 (one with tub, one powder room)"),
            QuestionOption(2, "2"),
            QuestionOption(2.5, "2.5"),
            QuestionOption(3, "3+"),
        ],
        default=2,
        impact="high",
        why="Bathrooms affect plumbing and layout",
    ),
    Question(
        id="q_garage",
        text="Do you need a garage?",
        category=QuestionCategory.PROGRAM,
        target_field="program.garage",
        options=[
            QuestionOption("none", "No garage"),
            QuestionOption("1car", "1-car garage"),
            QuestionOption("2car", "2-car garage"),
            QuestionOption("3car", "3-car garage"),
        ],
        default="2car",
        impact="medium",
        why="Garage significantly affects footprint",
    ),
    Question(
        id="q_office",
        text="Do you need a home office?",
        category=QuestionCategory.PROGRAM,
        target_field="program.office",
        options=[
            QuestionOption(False, "No"),
            QuestionOption(True, "Yes, dedicated office"),
            QuestionOption("flex", "Flexible space that could be office"),
        ],
        default=False,
        impact="medium",
        why="Work from home needs affect layout",
    ),

    # Room-specific questions
    Question(
        id="q_bed_size_primary",
        text="What size bed in the primary bedroom?",
        category=QuestionCategory.ROOMS,
        target_field="rooms[primary_bedroom].furniture[bed].size",
        options=[
            QuestionOption("queen", "Queen"),
            QuestionOption("king", "King"),
            QuestionOption("cal_king", "California King"),
        ],
        default="queen",
        impact="medium",
        why="Bed size determines minimum room size",
        dependencies=["rooms[primary_bedroom] exists"],
    ),
    Question(
        id="q_open_plan",
        text="Open plan kitchen/living, or separate rooms?",
        category=QuestionCategory.RELATIONSHIPS,
        target_field="priorities.open_plan",
        options=[
            QuestionOption(9, "Open plan (one big space)"),
            QuestionOption(5, "Partial (island divider)"),
            QuestionOption(2, "Separate rooms"),
        ],
        default=7,
        impact="high",
        why="This affects how main living spaces connect",
    ),

    # Site questions
    Question(
        id="q_lot_size",
        text="What's your lot size?",
        category=QuestionCategory.SITE,
        target_field="site.dimensions",
        options=[
            QuestionOption("small", "Small (under 5,000 sqft)"),
            QuestionOption("medium", "Medium (5,000-10,000 sqft)"),
            QuestionOption("large", "Large (over 10,000 sqft)"),
            QuestionOption("unknown", "Not sure"),
        ],
        default="medium",
        impact="high",
        why="Lot size constrains building footprint",
    ),
    Question(
        id="q_stories",
        text="One story or two?",
        category=QuestionCategory.SITE,
        target_field="constraints.stories_max",
        options=[
            QuestionOption(1, "One story (ranch)"),
            QuestionOption(2, "Two stories"),
            QuestionOption(1.5, "1.5 stories (bonus room above garage)"),
        ],
        default=1,
        impact="high",
        why="This fundamentally changes the layout approach",
    ),

    # Priorities
    Question(
        id="q_priority_light",
        text="How important is natural light?",
        category=QuestionCategory.PRIORITIES,
        target_field="priorities.natural_light",
        options=[
            QuestionOption(9, "Very important - lots of windows"),
            QuestionOption(5, "Moderately important"),
            QuestionOption(2, "Not a priority"),
        ],
        default=5,
        impact="medium",
        why="Affects window placement and room orientation",
    ),
    Question(
        id="q_priority_privacy",
        text="How important is privacy?",
        category=QuestionCategory.PRIORITIES,
        target_field="priorities.privacy",
        options=[
            QuestionOption(9, "Very important - bedrooms away from street"),
            QuestionOption(5, "Moderately important"),
            QuestionOption(2, "Not a concern"),
        ],
        default=5,
        impact="medium",
        why="Affects room placement relative to street",
    ),

    # Character
    Question(
        id="q_style",
        text="What architectural style appeals to you?",
        category=QuestionCategory.CHARACTER,
        target_field="character.style",
        options=[
            QuestionOption("modern", "Modern/Contemporary"),
            QuestionOption("traditional", "Traditional"),
            QuestionOption("craftsman", "Craftsman"),
            QuestionOption("farmhouse", "Modern Farmhouse"),
            QuestionOption("colonial", "Colonial"),
            QuestionOption("ranch", "Ranch"),
        ],
        default="traditional",
        impact="low",
        why="Style influences roof shapes and detailing",
    ),

    # Budget
    Question(
        id="q_footprint",
        text="Target total square footage?",
        category=QuestionCategory.SITE,
        target_field="constraints.footprint_max",
        options=[
            QuestionOption(100, "Small (under 1,200 sqft)"),
            QuestionOption(150, "Medium (1,200-2,000 sqft)"),
            QuestionOption(200, "Large (2,000-2,800 sqft)"),
            QuestionOption(280, "Very large (2,800+ sqft)"),
        ],
        default=150,
        impact="high",
        why="Total size affects everything",
    ),
]


# =============================================================================
# Question Generator
# =============================================================================

class QuestionGenerator:
    """Generate questions based on current state."""

    def __init__(self, state: QBDState):
        self.state = state
        self._answered: set = set()  # Track answered question IDs

    def generate(self, max_questions: int = 5) -> List[Question]:
        """Generate the next best questions to ask.

        Args:
            max_questions: Maximum number of questions to return

        Returns:
            List of Question objects, ordered by importance
        """
        # Filter available questions
        available = self._filter_available()

        # Score each question
        scored = [(q, self._score_question(q)) for q in available]

        # Sort by score
        scored.sort(key=lambda x: x[1], reverse=True)

        # Balance categories
        result = self._balance_categories(scored, max_questions)

        return result

    def _filter_available(self) -> List[Question]:
        """Filter questions by dependencies and answered status."""
        available = []

        for question in QUESTION_POOL:
            # Skip if already answered
            if question.id in self._answered:
                continue

            # Check dependencies
            if self._dependencies_met(question):
                available.append(question)

        return available

    def _dependencies_met(self, question: Question) -> bool:
        """Check if question dependencies are met."""
        for dep in question.dependencies:
            # Parse dependency string
            if "exists" in dep:
                # Check if element exists
                element = dep.replace(" exists", "")
                if "rooms[" in element:
                    room_type = element.split("[")[1].split("]")[0]
                    if not self.state.get_room_by_type(room_type):
                        return False
        return True

    def _score_question(self, question: Question) -> float:
        """Score a question by how valuable the answer would be."""
        score = 0.0

        # Impact weight
        impact_scores = {"high": 50, "medium": 30, "low": 10}
        score += impact_scores.get(question.impact, 20)

        # Solver blocking (high priority)
        if self._blocks_solver(question):
            score += 100

        # Category priority based on lifecycle
        lifecycle = self.state.lifecycle
        if lifecycle == StateLifecycle.EMPTY:
            if question.category in (QuestionCategory.HOUSEHOLD, QuestionCategory.PROGRAM):
                score += 40
        elif lifecycle == StateLifecycle.ACCUMULATING:
            if question.category in (QuestionCategory.ROOMS, QuestionCategory.RELATIONSHIPS):
                score += 30
            if question.category == QuestionCategory.SITE:
                score += 20

        # Recently related (conversational flow)
        # TODO: Track recent answers and boost related questions

        return score

    def _blocks_solver(self, question: Question) -> bool:
        """Check if this question blocks the solver."""
        blocking_fields = [
            "program.bedrooms",  # Need room count
            "constraints.footprint_max",  # Need size bounds
            "constraints.stories_max",  # Need story count
        ]
        return question.target_field in blocking_fields

    def _balance_categories(
        self,
        scored: List[tuple],
        max_questions: int
    ) -> List[Question]:
        """Balance questions across categories."""
        result = []
        category_counts: Dict[QuestionCategory, int] = {}
        max_per_category = max(2, max_questions // 3)

        for question, score in scored:
            cat = question.category
            count = category_counts.get(cat, 0)

            if count < max_per_category:
                result.append(question)
                category_counts[cat] = count + 1

            if len(result) >= max_questions:
                break

        return result

    def mark_answered(self, question_id: str):
        """Mark a question as answered."""
        self._answered.add(question_id)

    def get_minimum_required(self) -> List[Question]:
        """Get the minimum questions required to generate any design."""
        required_ids = ["q_bedrooms", "q_footprint", "q_stories"]
        return [q for q in QUESTION_POOL if q.id in required_ids]


def generate_questions(state: QBDState, max_questions: int = 5) -> List[Dict]:
    """Convenience function to generate questions."""
    generator = QuestionGenerator(state)
    questions = generator.generate(max_questions)
    return [q.to_dict() for q in questions]
