"""Call state machine for QWR AI Voice Bot.

Manages transitions through: GREETING → MODE_SELECTION → IDENTITY_CHECK → INTAKE → CONVERSATION → SUMMARY_CONFIRM → ENDED
"""

from __future__ import annotations
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CallState(str, Enum):
    """Call lifecycle states."""
    GREETING = "greeting"
    MODE_SELECTION = "mode_selection"
    IDENTITY_CHECK = "identity_check"
    UNKNOWN_CALLER_CHOICE = "unknown_caller_choice"
    INTAKE = "intake"
    CONVERSATION = "conversation"
    SUMMARY_CONFIRM = "summary_confirm"
    ENDED = "ended"


class CallStateMachine:
    """Manages call state transitions and associated prompts."""
    
    # DTMF digit to mode mapping
    MODE_SELECTION_MAP = {
        "1": "think",
        "2": "challenge",
        "3": "explore",
        "4": "guide",
    }
    
    # DTMF digit labels for prompts
    MODE_LABELS = {
        "1": "Think Mode",
        "2": "Challenge Mode",
        "3": "Explore Mode",
        "4": "Guide Mode",
    }
    
    # Prompts for each state
    PROMPTS = {
        CallState.GREETING: (
            "Welcome to QWR, the question what's real. "
            "We help you find reliable information. "
            "How can I assist you today?"
        ),
        
        CallState.MODE_SELECTION: (
            "Before we start, please choose your conversation style. "
            "Press 1 for Think Mode - we'll explore ideas critically. "
            "Press 2 for Challenge Mode - we'll question assumptions. "
            "Press 3 for Explore Mode - we'll discover broadly. "
            "Press 4 for Guide Mode - I'll walk you through step by step. "
            "Which mode would you prefer? 1, 2, 3, or 4?"
        ),
        
        CallState.IDENTITY_CHECK: (
            "To better assist you, may I have your name please?"
        ),
        
        CallState.UNKNOWN_CALLER_CHOICE: (
            "Thank you. Would you like to share your company and role? "
            "Say yes to continue, or say anonymous to proceed without sharing."
        ),
        
        CallState.INTAKE: (
            "Great! Let me capture a few details. "
            "What is your company name?"
        ),
        
        CallState.CONVERSATION: (
            "Perfect! Now, what would you like to know?"
        ),
        
        CallState.SUMMARY_CONFIRM: (
            "Thanks for calling QWR. Would you like me to email you a summary of our conversation? "
            "Say yes or press 1 to receive it."
        ),
        
        CallState.ENDED: (
            "Thank you for calling. Goodbye!"
        ),
    }
    
    def __init__(self, call_id: str, call_sid: str):
        self.call_id = call_id
        self.call_sid = call_sid
        self.current_state = CallState.GREETING
        self.selected_mode: str | None = None
        self.retries = 0
        self.max_retries = 3
        
    def transition(self, next_state: CallState) -> None:
        """Move to the next state."""
        logger.info(
            f"call_sid={self.call_sid} state_transition: {self.current_state} → {next_state}"
        )
        self.current_state = next_state
        self.retries = 0
    
    def get_state_prompt(self) -> str:
        """Get the prompt for the current state."""
        return self.PROMPTS.get(self.current_state, "")
    
    def handle_dtmf_mode_selection(self, digit: str) -> bool:
        """
        Handle DTMF input in MODE_SELECTION state.
        Returns True if valid mode selected, False otherwise.
        """
        if digit in self.MODE_SELECTION_MAP:
            self.selected_mode = self.MODE_SELECTION_MAP[digit]
            logger.info(
                f"call_sid={self.call_sid} mode_selected: {self.selected_mode} (digit={digit})"
            )
            return True
        return False
    
    def should_retry(self) -> bool:
        """Check if we should retry current state."""
        self.retries += 1
        return self.retries <= self.max_retries
    
    def get_retry_prompt(self) -> str:
        """Get retry prompt for current state."""
        if self.current_state == CallState.MODE_SELECTION:
            return (
                "I didn't catch that. Please press 1, 2, 3, or 4 to select your conversation style. "
                "1 for Think, 2 for Challenge, 3 for Explore, 4 for Guide."
            )
        elif self.current_state == CallState.SUMMARY_CONFIRM:
            return (
                "I didn't understand. Please say yes or press 1 to receive a summary by email. "
                "Or say no to skip."
            )
        return "I didn't understand. Could you please repeat?"
    
    @staticmethod
    def next_state_after_mode_selection(known_caller: bool) -> CallState:
        """Determine next state after mode selection."""
        if known_caller:
            return CallState.CONVERSATION
        else:
            return CallState.UNKNOWN_CALLER_CHOICE
    
    @staticmethod
    def next_state_after_identity_check(is_anonymous: bool) -> CallState:
        """Determine next state after identity check."""
        if is_anonymous:
            return CallState.CONVERSATION
        else:
            return CallState.INTAKE
