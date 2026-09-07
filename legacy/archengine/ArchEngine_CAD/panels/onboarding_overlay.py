"""
Onboarding Overlay - Welcome screen with centered chat

Provides an immersive first-run experience where the chat interface
is centered and prominent. After 3 questions, animates the transition
to move the chat to the side panel.
"""
from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QGraphicsOpacityEffect, QPushButton
)
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QRect,
    QPoint, QTimer, QSequentialAnimationGroup, QParallelAnimationGroup
)
from PyQt6.QtGui import QPainter, QColor, QFont


class OnboardingOverlay(QWidget):
    """
    Full-screen overlay for onboarding experience.

    Features:
    - Centered chat panel for first 3 questions
    - Progress indicator (Question X of 3)
    - Animated transition to side panel after onboarding
    - Blur background effect
    """

    # Signals
    onboarding_complete = pyqtSignal()  # Emitted when animation finishes

    def __init__(self, chat_panel, parent=None):
        super().__init__(parent)
        self.chat_panel = chat_panel
        self.question_count = 0
        self.max_questions = 3
        self._is_transitioning = False

        self._setup_ui()
        self._setup_animations()

    def _setup_ui(self):
        """Set up the overlay UI."""
        # Set up overlay properties
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        # Main layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Create semi-transparent background
        self.background = QFrame()
        self.background.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 35, 0.95);
                border-radius: 0px;
            }
        """)
        layout.addWidget(self.background)

        # Background layout
        bg_layout = QVBoxLayout(self.background)
        bg_layout.setSpacing(20)

        # Top section - Welcome message and progress
        top_section = QVBoxLayout()
        top_section.setSpacing(10)

        # App title
        title_label = QLabel("Welcome to ArchEngine")
        title_label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                font-size: 32px;
                font-weight: bold;
                padding: 20px;
            }
        """)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_section.addWidget(title_label)

        # Subtitle
        subtitle_label = QLabel("Let's design your building. Answer 3 questions to get started.")
        subtitle_label.setStyleSheet("""
            QLabel {
                color: #a0a0a0;
                font-size: 16px;
                padding: 10px;
            }
        """)
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label = subtitle_label  # Store for updates
        top_section.addWidget(subtitle_label)

        # Progress indicator
        self.progress_label = QLabel("Question 1 of 3")
        self.progress_label.setStyleSheet("""
            QLabel {
                color: #4a9eff;
                font-size: 14px;
                font-weight: bold;
                padding: 10px;
                background-color: rgba(74, 158, 255, 0.1);
                border-radius: 5px;
            }
        """)
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_section.addWidget(self.progress_label)

        # Progress bar (visual)
        progress_bar_container = QWidget()
        progress_bar_layout = QHBoxLayout(progress_bar_container)
        progress_bar_layout.setContentsMargins(0, 0, 0, 0)

        self.progress_bar = QFrame()
        self.progress_bar.setFixedSize(300, 4)
        self.progress_bar.setStyleSheet("""
            QFrame {
                background-color: #3a3a3a;
                border-radius: 2px;
            }
        """)
        progress_bar_layout.addWidget(self.progress_bar)
        progress_bar_layout.addStretch()

        self.progress_fill = QFrame()
        self.progress_fill.setFixedSize(100, 4)  # Start at 1/3
        self.progress_fill.setStyleSheet("""
            QFrame {
                background-color: #4a9eff;
                border-radius: 2px;
            }
        """)

        # Stack progress bar and fill
        progress_stack = QWidget()
        progress_stack.setFixedSize(300, 4)
        progress_stack_layout = QVBoxLayout(progress_stack)
        progress_stack_layout.setContentsMargins(0, 0, 0, 0)
        progress_stack_layout.setSpacing(0)
        progress_stack_layout.addWidget(self.progress_bar)
        progress_stack_layout.addWidget(self.progress_fill)
        progress_stack_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        top_section.addWidget(progress_stack, alignment=Qt.AlignmentFlag.AlignCenter)
        bg_layout.addLayout(top_section)

        bg_layout.addStretch()

        # Center section - Chat panel container
        center_section = QHBoxLayout()
        center_section.setSpacing(0)

        # Left spacer for centering
        center_section.addStretch(1)

        # Chat container with shadow/border
        self.chat_container = QFrame()
        self.chat_container.setStyleSheet("""
            QFrame {
                background-color: rgba(45, 45, 50, 0.98);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
        """)
        self.chat_container.setFixedWidth(600)
        self.chat_container.setMinimumHeight(500)

        chat_layout = QVBoxLayout(self.chat_container)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.addWidget(self.chat_panel)

        center_section.addWidget(self.chat_container)
        center_section.addStretch(1)

        bg_layout.addLayout(center_section)

        bg_layout.addStretch()

        # Bottom section - Tips
        bottom_section = QHBoxLayout()
        tip_label = QLabel("Tip: Be descriptive about your space needs for better results")
        tip_label.setStyleSheet("""
            QLabel {
                color: #606060;
                font-size: 12px;
                padding: 10px;
            }
        """)
        tip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_section.addStretch()
        bottom_section.addWidget(tip_label)
        bottom_section.addStretch()

        bg_layout.addLayout(bottom_section)

    def _setup_animations(self):
        """Set up animation objects for transitions."""
        # Fade out animation
        self.fade_out = QPropertyAnimation(self, b"windowOpacity")
        self.fade_out.setDuration(800)  # 800ms fade
        self.fade_out.setStartValue(1.0)
        self.fade_out.setEndValue(0.0)
        self.fade_out.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # Chat panel slide animation
        self.chat_slide = QPropertyAnimation(self.chat_container, b"geometry")
        self.chat_slide.setDuration(1000)  # 1000ms slide
        self.chat_slide.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # Progress bar animation
        self.progress_anim = QPropertyAnimation(self.progress_fill, b"maximumWidth")
        self.progress_anim.setDuration(300)
        self.progress_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def increment_question(self):
        """
        Called when user submits a question.

        After 3 questions, triggers the transition animation.
        """
        self.question_count += 1

        # Update progress
        if self.question_count < self.max_questions:
            self._update_progress(self.question_count + 1)
            self.subtitle_label.setText(
                f"Great! {self.max_questions - self.question_count} more question"
                f"{'s' if self.max_questions - self.question_count > 1 else ''} to go."
            )
        else:
            # Last question answered
            self.subtitle_label.setText("Design complete! Moving to workspace...")
            self._update_progress(self.max_questions)

            # Trigger transition after a short delay
            QTimer.singleShot(1500, self.start_transition)

    def _update_progress(self, question_num: int):
        """Update progress indicator."""
        self.progress_label.setText(f"Question {question_num} of {self.max_questions}")

        # Animate progress bar
        target_width = int(300 * (question_num / self.max_questions))
        self.progress_anim.stop()
        self.progress_anim.setStartValue(self.progress_fill.width())
        self.progress_anim.setEndValue(target_width)
        self.progress_anim.start()

    def start_transition(self):
        """
        Start the animated transition to side panel.

        Animates:
        1. Chat panel slides to the right
        2. Overlay fades out
        3. Emits onboarding_complete signal
        """
        if self._is_transitioning:
            return

        self._is_transitioning = True

        # Get current geometry
        current_geom = self.chat_container.geometry()
        parent = self.parent()

        if parent:
            # Calculate target position (right side of screen)
            parent_width = parent.width()
            target_x = parent_width - current_geom.width() - 20  # 20px margin
            target_geom = QRect(target_x, current_geom.y(), current_geom.width(), current_geom.height())

            # Set up slide animation
            self.chat_slide.setStartValue(current_geom)
            self.chat_slide.setEndValue(target_geom)

            # Create sequential animation group
            anim_group = QSequentialAnimationGroup()

            # First slide the chat panel
            anim_group.addAnimation(self.chat_slide)

            # Then fade out the overlay
            anim_group.addAnimation(self.fade_out)

            # When done, emit signal and hide
            anim_group.finished.connect(self._on_transition_complete)
            anim_group.start()
        else:
            # No parent, just fade out
            self.fade_out.finished.connect(self._on_transition_complete)
            self.fade_out.start()

    def _on_transition_complete(self):
        """Handle transition completion."""
        self.hide()
        self.onboarding_complete.emit()
        self._is_transitioning = False

    def show_overlay(self):
        """Show the overlay with fade-in effect."""
        self.resize(self.parent().size() if self.parent() else self.size())
        self.setWindowOpacity(0.0)

        # Start chat panel onboarding mode
        if hasattr(self.chat_panel, 'start_onboarding'):
            # Connect to progress updates
            try:
                self.chat_panel.onboarding_progress.disconnect(self._on_chat_progress)
            except TypeError:
                pass
            self.chat_panel.onboarding_progress.connect(self._on_chat_progress)

            # Connect to onboarding completion
            try:
                self.chat_panel.onboarding_complete.disconnect(self._on_chat_onboarding_complete)
            except TypeError:
                pass
            self.chat_panel.onboarding_complete.connect(self._on_chat_onboarding_complete)

            # Start onboarding
            self.chat_panel.start_onboarding()

    def _on_chat_progress(self, current: int, total: int):
        """Handle chat panel progress update."""
        self._update_progress(current)
        if current < total:
            self.subtitle_label.setText(
                f"Great! {total - current} more question{'s' if total - current > 1 else ''} to go."
            )

        # Fade in
        fade_in = QPropertyAnimation(self, b"windowOpacity")
        fade_in.setDuration(500)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutCubic)
        fade_in.start()

        self.show()
        self.raise_()

    def _on_chat_onboarding_complete(self, data: dict):
        """Handle chat panel onboarding completion."""
        print(f"[Onboarding] Chat onboarding complete with data: {data}")
        self.subtitle_label.setText("Design complete! Moving to workspace...")
        self._update_progress(self.max_questions)

        # Trigger transition after a short delay
        QTimer.singleShot(1500, self.start_transition)

    def paintEvent(self, event):
        """Paint the overlay with rounded corners."""
        # Allow the background to show through
        super().paintEvent(event)

    def resizeEvent(self, event):
        """Handle resize events."""
        super().resizeEvent(event)
        # Recalculate positions if needed
        if self.parent():
            self.resize(self.parent().size())


class FloatingChatWidget(QWidget):
    """
    Alternative floating chat widget that can be positioned anywhere.

    Used during the transition period.
    """
    def __init__(self, chat_panel, parent=None):
        super().__init__(parent)
        self.chat_panel = chat_panel

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowStaysOnTopHint
        )

        # Set up styling
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(45, 45, 50, 0.98);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 12px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.chat_panel)
