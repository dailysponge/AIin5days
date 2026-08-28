"""Context Bloat Management: Sliding Windows and Rolling Conversation Summarization."""

import re
from typing import Any, Dict, List, Optional, Tuple


class ContextManager:
    """Manages context bloat via sliding windows and incremental extractive/rolling summarization."""

    def __init__(self, max_turns: int = 4, max_tokens: int = 2000):
        self.max_turns = max_turns
        self.max_tokens = max_tokens

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Rough token estimation (approx 4 chars per token)."""
        return max(1, len(text) // 4)

    def compact_context(
        self,
        messages: List[Dict[str, str]],
        existing_summary: str = "",
    ) -> Tuple[List[Dict[str, str]], str]:
        """Prunes conversation history outside the sliding window and updates the rolling summary.
        
        Args:
            messages: Full list of message dicts [{"role": "user"/"assistant", "content": "..."}]
            existing_summary: Previously accumulated conversation summary.
            
        Returns:
            Tuple of (compacted_messages, updated_summary).
        """
        # 1 turn = 1 user message + 1 assistant message (2 messages)
        max_messages = self.max_turns * 2
        
        if len(messages) <= max_messages:
            # Within window bounds
            return messages, existing_summary

        # Split messages: older ones to summarize, recent ones to keep in sliding window
        cutoff_idx = len(messages) - max_messages
        messages_to_summarize = messages[:cutoff_idx]
        active_window_messages = messages[cutoff_idx:]

        # Extract essential entities and decisions from pruned messages
        extracted_facts: List[str] = []
        
        # Regex patterns for key logistics entities
        shipment_pattern = re.compile(r"SHP-[A-Z0-9]{6}", re.IGNORECASE)
        approval_pattern = re.compile(r"APPR-(?:AUTO|HITL)-[A-Z0-9]+", re.IGNORECASE)
        
        for msg in messages_to_summarize:
            content = msg.get("content", "")
            role = msg.get("role", "unknown").upper()
            
            # Find shipments
            shps = shipment_pattern.findall(content)
            if shps:
                extracted_facts.append(f"{role} referenced shipment(s): {', '.join(set(shps))}")
            
            # Find approvals
            apprs = approval_pattern.findall(content)
            if apprs:
                extracted_facts.append(f"{role} processed approval ticket: {', '.join(set(apprs))}")
                
            # Key outcomes
            if "AUTO_APPROVED" in content:
                extracted_facts.append("Action automatically authorized under budget threshold.")
            elif "PENDING_HUMAN_APPROVAL" in content:
                extracted_facts.append("Action held pending dispatcher authorization.")
            elif "DELAYED_COLD_CHAIN_ALERT" in content or "cold chain" in content.lower():
                extracted_facts.append("Cold-chain temperature deviation flagged.")
            elif "WEATHER_HOLD" in content or "blizzard" in content.lower():
                extracted_facts.append("Highway winter weather disruption evaluated.")

        # Build concise incremental summary
        new_facts_block = "; ".join(dict.fromkeys(extracted_facts)) if extracted_facts else "Routine tracking queries."
        
        if existing_summary:
            updated_summary = f"{existing_summary} | Earlier: {new_facts_block}"
        else:
            updated_summary = f"Summary of earlier turns: {new_facts_block}"
            
        # Ensure summary itself does not bloat indefinitely (cap at 400 chars)
        if len(updated_summary) > 400:
            updated_summary = updated_summary[-400:]

        return active_window_messages, updated_summary

    def build_effective_prompt(
        self,
        new_query: str,
        active_messages: List[Dict[str, str]],
        summary: str,
    ) -> str:
        """Injects rolling summary and active sliding window into effective agent prompt context."""
        parts: List[str] = []
        if summary:
            parts.append(f"[CONVERSATION MEMORY SUMMARY]: {summary}")
        
        for msg in active_messages:
            role = msg.get("role", "user").capitalize()
            parts.append(f"{role}: {msg.get('content', '')}")
            
        parts.append(f"Dispatcher: {new_query}")
        return "\n\n".join(parts)


context_manager = ContextManager()
