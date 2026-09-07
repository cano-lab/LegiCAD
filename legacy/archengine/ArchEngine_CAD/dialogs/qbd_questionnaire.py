"""
QBD Questionnaire Dialog - Floating dialog for new building design

Shows a guided questionnaire when creating a new building.
Prompts the user with key design questions and generates a building.
"""
from typing import Dict, List, Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QScrollArea,
    QWidget, QFrame, QLineEdit
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont


class QuestionCard(QFrame):
    """A single question card with label and input widget."""

    def __init__(self, question: str, input_widget, parent=None):
        super().__init__(parent)
        self._setup_ui(question, input_widget)

    def _setup_ui(self, question: str, input_widget):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Question label
        label = QLabel(question)
        label.setWordWrap(True)
        label.setStyleSheet("""
            QLabel {
                font-size: 13px;
                font-weight: 500;
                color: #e0e0e0;
            }
        """)
        layout.addWidget(label)

        # Input widget
        if hasattr(input_widget, 'setStyleSheet'):
            input_widget.setStyleSheet("""
                QWidget {
                    background: #3a3a3a;
                    border: 1px solid #555;
                    border-radius: 4px;
                    padding: 6px;
                    color: #fff;
                }
                QComboBox::drop-down {
                    border: none;
                }
                QComboBox::down-arrow {
                    width: 12px;
                    height: 12px;
                }
            """)
        layout.addWidget(input_widget)

        # Style the card
        self.setStyleSheet("""
            QuestionCard {
                background: #252525;
                border: 1px solid #444;
                border-radius: 8px;
                margin: 4px;
            }
            QuestionCard:hover {
                border: 1px solid #6495ED;
            }
        """)


class QBDQuestionnaireDialog(QDialog):
    """
    Floating questionnaire dialog for new building design.

    Shows in center of screen when creating a new file.
    Prompts user with key design questions.
    """

    # Signal emitted when user wants to generate building
    # Args: dict with answers
    generate_building = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._answers = {}
        self._setup_ui()

    def _setup_ui(self):
        """Set up the dialog UI."""
        self.setWindowTitle("Design Your Building")
        self.setModal(True)
        self.setMinimumWidth(500)
        self.setMaximumWidth(600)

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet("background: #1a1a2e; border-bottom: 2px solid #6495ED;")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Let's Design Your Building")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #6495ED;")
        header_layout.addWidget(title)

        subtitle = QLabel("Answer a few questions to get started")
        subtitle.setStyleSheet("color: #aaa; font-size: 12px;")
        header_layout.addWidget(subtitle)

        layout.addWidget(header)

        # Scrollable content area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: #1e1e1e;
            }
            QScrollBar:vertical {
                background: #2a2a2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #555;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #6495ED;
            }
        """)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(16, 16, 16, 16)
        content_layout.setSpacing(12)

        # Question 1: Building Type
        self._building_type = QComboBox()
        self._building_type.addItems([
            "Residential",
            "Commercial",
            "Mixed Use"
        ])
        self._building_type.setCurrentIndex(0)
        card1 = QuestionCard("What type of building are you designing?", self._building_type)
        content_layout.addWidget(card1)

        # Question 2: Residence Type (for residential)
        self._residence_type = QComboBox()
        self._residence_type.addItems([
            "Single Family Home",
            "Duplex",
            "Townhouse",
            "Apartment",
            "Condo"
        ])
        self._residence_type.setCurrentIndex(0)
        card2 = QuestionCard("What kind of residence?", self._residence_type)
        content_layout.addWidget(card2)

        # Question 3: Size Requirements
        size_layout = QHBoxLayout()

        bedrooms_spin = QSpinBox()
        bedrooms_spin.setRange(0, 20)
        bedrooms_spin.setValue(3)
        bedrooms_spin.setSuffix(" bedrooms")
        bedrooms_spin.setMinimumWidth(120)

        bathrooms_spin = QDoubleSpinBox()
        bathrooms_spin.setRange(0.5, 10.0)
        bathrooms_spin.setSingleStep(0.5)
        bathrooms_spin.setValue(2.0)
        bathrooms_spin.setSuffix(" baths")
        bathrooms_spin.setMinimumWidth(100)

        size_layout.addWidget(QLabel("Bedrooms:"))
        size_layout.addWidget(bedrooms_spin)
        size_layout.addSpacing(20)
        size_layout.addWidget(QLabel("Bathrooms:"))
        size_layout.addWidget(bathrooms_spin)
        size_layout.addStretch()

        size_widget = QWidget()
        size_widget.setLayout(size_layout)

        self._bedrooms = bedrooms_spin
        self._bathrooms = bathrooms_spin

        card3 = QuestionCard("How many bedrooms and bathrooms?", size_widget)
        content_layout.addWidget(card3)

        # Question 4: Square Footage
        sqft_spin = QSpinBox()
        sqft_spin.setRange(500, 20000)
        sqft_spin.setSingleStep(100)
        sqft_spin.setValue(2000)
        sqft_spin.setSuffix(" sq ft")
        self._sqft = sqft_spin

        card4 = QuestionCard("Approximately how big?", sqft_spin)
        content_layout.addWidget(card4)

        # Question 5: Garage
        self._garage = QComboBox()
        self._garage.addItems([
            "No garage",
            "1 car",
            "2 cars",
            "3 cars"
        ])
        self._garage.setCurrentIndex(1)
        card5 = QuestionCard("Do you need a garage?", self._garage)
        content_layout.addWidget(card5)

        # Question 6: Special Rooms
        special_layout = QVBoxLayout()
        self._special_checks = {}

        special_rooms = [
            ("Home Office", "office"),
            ("Laundry Room", "laundry"),
            ("Guest Room", "guest"),
            ("Workshop", "workshop"),
            ("Home Gym", "gym"),
            ("Library/Study", "library"),
            ("Mudroom", "mudroom"),
            ("Porch", "porch"),
            ("Deck", "deck")
        ]

        for display_name, key in special_rooms:
            chk = QCheckBox(display_name)
            chk.setStyleSheet("""
                QCheckBox {
                    color: #e0e0e0;
                    spacing: 8px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                    border: 2px solid #555;
                    border-radius: 3px;
                    background: #2a2a2a;
                }
                QCheckBox::indicator:checked {
                    background: #6495ED;
                    border-color: #6495ED;
                }
            """)
            self._special_checks[key] = chk
            special_layout.addWidget(chk)

        special_widget = QWidget()
        special_widget.setLayout(special_layout)

        card6 = QuestionCard("Any special rooms? (select all that apply)", special_widget)
        content_layout.addWidget(card6)

        # Question 7: Style
        self._style = QComboBox()
        self._style.addItems([
            "Modern",
            "Traditional",
            "Contemporary",
            "Craftsman",
            "Ranch",
            "Colonial",
            "Mediterranean"
        ])
        self._style.setCurrentIndex(0)
        card7 = QuestionCard("What architectural style?", self._style)
        content_layout.addWidget(card7)

        # Question 8: Solver Algorithm
        self._solver = QComboBox()
        self._solver.addItem("Normalized Constraint - Rect/L-shape layouts (recommended)", "normalized_constraint")
        self._solver.addItem("Grid Solver - Simple, rectangular (fast)", "grid")
        self._solver.addItem("Constraint Solver - CSP with backtracking", "constraint")
        self._solver.addItem("Wave Function Collapse - Complex constraints", "wave_collapse")
        self._solver.addItem("Perfect Adjacency - Maximum adjacency satisfaction", "perfect_adjacency")
        self._solver.addItem("Tree Subdivision - Fast, hierarchical (experimental)", "tree")
        self._solver.addItem("Genetic Algorithm - Evolutionary optimization", "genetic")
        self._solver.addItem("Simulated Annealing - Statistical optimization", "annealing")
        self._solver.addItem("Force Directed - Physics-based layout", "force_directed")
        self._solver.addItem("Space Colonization - Organic growth", "space_colonization")
        self._solver.setCurrentIndex(0)
        card8 = QuestionCard("Room layout algorithm?", self._solver)
        content_layout.addWidget(card8)

        content_layout.addStretch()
        scroll.setWidget(content_widget)
        layout.addWidget(scroll, 1)

        # Footer with buttons
        footer = QWidget()
        footer.setStyleSheet("background: #1a1a2e; border-top: 1px solid #444;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 16, 20, 16)

        footer_layout.addStretch()

        skip_btn = QPushButton("Skip")
        skip_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 24px;
                background: transparent;
                border: 1px solid #555;
                color: #aaa;
                border-radius: 4px;
                font-size: 12px;
            }
            QPushButton:hover {
                border-color: #888;
                color: #fff;
            }
        """)
        skip_btn.clicked.connect(self._on_skip)
        footer_layout.addWidget(skip_btn)

        generate_btn = QPushButton("Generate Design")
        generate_btn.setStyleSheet("""
            QPushButton {
                padding: 10px 32px;
                background: #6495ED;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #7aa5ff;
            }
            QPushButton:pressed {
                background: #4a75cc;
            }
        """)
        generate_btn.clicked.connect(self._on_generate)
        footer_layout.addWidget(generate_btn)

        layout.addWidget(footer)

        # Set overall dialog style
        self.setStyleSheet("""
            QDialog {
                background: #1e1e1e;
            }
        """)

    def _on_skip(self):
        """User chose to skip - start with blank document."""
        self.reject()

    def _on_generate(self):
        """Collect answers and emit signal."""
        # Collect special rooms
        special_rooms = [
            key for key, chk in self._special_checks.items()
            if chk.isChecked()
        ]

        # Build answers dictionary
        self._answers = {
            "building_type": self._building_type.currentText().lower().replace(" ", "_"),
            "residence_type": self._residence_type.currentText().lower().replace(" ", "_"),
            "bedrooms": self._bedrooms.value(),
            "bathrooms": self._bathrooms.value(),
            "sqft": self._sqft.value(),
            "garage": self._garage.currentText().lower(),
            "special_rooms": special_rooms,
            "style": self._style.currentText().lower(),
            "solver": self._solver.currentData()
        }

        # Emit signal
        self.generate_building.emit(self._answers)
        self.accept()

    def get_answers(self) -> dict:
        """Get the user's answers."""
        return self._answers.copy()


def show_questionnaire(parent=None) -> Optional[dict]:
    """
    Show the questionnaire dialog.

    Returns:
        dict with answers if user clicked Generate,
        None if user clicked Skip or closed dialog
    """
    dialog = QBDQuestionnaireDialog(parent)
    result = dialog.exec()

    if result == QDialog.DialogCode.Accepted and dialog._answers:
        return dialog.get_answers()
    return None
