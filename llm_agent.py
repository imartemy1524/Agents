# Refactored Agents/llm_agent.py
import requests
import json
import os
import subprocess
import sys
import logging
from typing import List, Dict, Optional, Any

# Configure basic logging (consider configuring root logger in main script)
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__) # Use a logger specific to this module

DEFAULT_SYSTEM_PROMPT = (
    "You are a concise and helpful AI assistant. Respond clearly and briefly. "
    "User input may contain transcription errors or repeated words due to voice recognition; "
    "interpret the user's likely intent despite these potential inaccuracies, he may hav echo on his side - "
    "ignore it and pretend as if it was a single sentence."
)
THINK_START_TAG = '<think>'
THINK_END_TAG = '</think>'

class LLMAgent:
    """
    Agent to communicate with a local LLM API (LM Studio compatible),
    manage conversation history, and provide text-to-speech output.
    """
    def __init__(self, history_file: str = "Agents/data.json", lm_studio_url: str = "http://localhost:1234/v1/chat/completions"):
        """
        Initializes the agent, loads history, and sets up configuration.

        Args:
            history_file: Path to the JSON file for storing conversation history.
            lm_studio_url: The API endpoint for the LM Studio compatible server.
        """
        self.history_file: str = history_file
        self.lm_studio_url: str = lm_studio_url
        self.messages: List[Dict[str, str]] = self._load_history()
        self._ensure_system_prompt()
        log.info(f"LLMAgent initialized. History ({len(self.messages)} messages) loaded from {self.history_file}")

    def _load_history(self) -> List[Dict[str, str]]:
        """Loads conversation history from the JSON file."""
        if not os.path.exists(self.history_file):
            log.warning(f"History file not found: {self.history_file}. Starting fresh.")
            return []
        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
                if not isinstance(history, list):
                    log.warning(f"History file {self.history_file} does not contain a list. Starting fresh.")
                    return []
                # Basic validation of message structure (optional but good practice)
                valid_history = []
                for msg in history:
                    if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                        valid_history.append(msg)
                    else:
                        log.warning(f"Skipping invalid message format in history: {msg}")
                return valid_history
        except json.JSONDecodeError:
            log.warning(f"Could not decode JSON from {self.history_file}. Starting fresh.")
            return []
        except Exception as e:
            log.exception(f"Error loading history from {self.history_file}: {e}")
            return []

    def _ensure_system_prompt(self):
        """Ensures a system prompt exists, adding or updating if necessary."""
        system_prompt_index = -1
        for i, msg in enumerate(self.messages):
            if msg.get('role') == 'system':
                system_prompt_index = i
                break

        if system_prompt_index != -1:
            # Optionally update existing system prompt if needed, or just ensure it exists
            if self.messages[system_prompt_index].get('content') != DEFAULT_SYSTEM_PROMPT:
                 log.info("Updating existing system prompt.")
                 # Uncomment the line below if you always want to force the default prompt
                 # self.messages[system_prompt_index]['content'] = DEFAULT_SYSTEM_PROMPT
                 # self._save_history() # Save if updated
            else:
                 log.debug("Existing system prompt is up-to-date.")
        else:
            log.info("No system prompt found. Adding default system prompt.")
            self.messages.insert(0, {"role": "system", "content": DEFAULT_SYSTEM_PROMPT})
            self._save_history() # Save immediately after adding

    def _save_history(self):
        """Saves the current conversation history to the JSON file."""
        try:
            # Ensure the directory exists
            history_dir = os.path.dirname(self.history_file)
            if history_dir and not os.path.exists(history_dir):
                 log.info(f"Creating directory for history file: {history_dir}")
                 os.makedirs(history_dir, exist_ok=True)

            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(self.messages, f, indent=2, ensure_ascii=False)
            log.debug(f"History saved to {self.history_file}")
        except IOError as e:
            log.exception(f"IOError saving history to {self.history_file}: {e}")
        except Exception as e:
            log.exception(f"Unexpected error saving history to {self.history_file}: {e}")

    def _speak(self, text: str):
        """Uses macOS 'say' command for text-to-speech."""
        if sys.platform != 'darwin':
            log.info("TTS Info: 'say' command is only available on macOS. Skipping TTS.")
            return
        if not text or text.isspace():
             log.info("TTS Info: No text provided to speak.")
             return
        try:
            # Using -r 300 for rate adjustment
            command = ['say', "-r", "300", text]
            log.debug(f"Executing TTS command: {' '.join(command)}")
            # Use subprocess.run for better control and error handling
            result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8')
            log.debug(f"TTS Spoke: '{text}' (Output: {result.stdout}, {result.stderr})") # Optional: log successful TTS
        except FileNotFoundError:
            log.error("TTS Error: 'say' command not found. Is it installed and in PATH?")
        except subprocess.CalledProcessError as e:
            log.error(f"TTS Error during execution: {e}")
            log.error(f"TTS Stderr: {e.stderr}") # Log stderr for debugging
        except Exception as e:
            log.exception(f"An unexpected error occurred during TTS: {e}")


    def sendUserMessage(self, user_message: str) -> Optional[str]:
        """
        Sends user message to LLM, gets response, speaks it, saves history, returns response.

        Args:
            user_message: The message from the user.

        Returns:
            The text response from the LLM, or None if an error occurs or response is empty.
        """
        if not user_message or user_message.isspace():
            log.warning("User message is empty or whitespace, skipping.")
            return None

        # Append user message to history (temporarily)
        self.messages.append({"role": "user", "content": user_message})
        log.debug(f"Appended user message: '{user_message}'")

        assistant_message_content: Optional[str] = None # Initialize to None

        try:
            # Prepare request payload (ensure messages are valid)
            payload = {
                "messages": [msg for msg in self.messages if isinstance(msg, dict) and 'role' in msg and 'content' in msg],
                "temperature": 0.4, # Example temperature
                # "max_tokens": 150, # Consider adding token limits
                "stream": False # Keeping simple for now
            }

            log.info(f"Sending request to LLM at {self.lm_studio_url}...")
            response = requests.post(
                self.lm_studio_url,
                json=payload,
                timeout=120.0 # Standard float timeout
            )
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            # Process response
            response_data: Dict[str, Any] = response.json()
            log.debug(f"LLM Raw Response Data: {response_data}")

            choices = response_data.get("choices")
            if choices and isinstance(choices, list) and len(choices) > 0:
                message = choices[0].get("message")
                if message and isinstance(message, dict) and message.get("content"):
                    raw_content: str = message["content"].strip()
                    log.debug(f"LLM Raw Content: '{raw_content}'")

                    # Refined <think>...</think> removal
                    if raw_content.startswith(THINK_START_TAG):
                         think_end_index = raw_content.find(THINK_END_TAG)
                         if think_end_index != -1:
                              # Extract content *after* the closing tag
                              assistant_message_content = raw_content[think_end_index + len(THINK_END_TAG):].strip()
                              think_content = raw_content[len(THINK_START_TAG):think_end_index]
                              log.debug(f"Removed thought block: '{think_content}'. Remaining content: '{assistant_message_content}'")
                              if not assistant_message_content:
                                   log.warning(f"LLM response contained only a <think> block: '{raw_content}'")
                                   # Keep assistant_message_content as empty string "" here
                         else:
                              # Starts with <think> but no closing tag found - treat as regular content? Or error?
                              log.warning(f"LLM response started with '{THINK_START_TAG}' but no closing '{THINK_END_TAG}' found. Treating whole message as content.")
                              assistant_message_content = raw_content
                    else:
                         # No think block found at the start
                         assistant_message_content = raw_content
                else:
                     log.warning("LLM response missing 'message' or 'content' structure in choices.")
            else:
                log.warning("LLM response missing 'choices' or choices list is empty.")

            # Check if we actually got content
            if not assistant_message_content: # Handles None or empty string ""
                 log.warning("Received no valid assistant message content from LLM.")
                 self.messages.pop() # Remove the user message that got no reply
                 self._save_history() # Save the state without the failed user message
                 return None # Return None explicitly

            log.info(f"LLM Processed Response: '{assistant_message_content}'")

            # Append valid assistant response to history
            self.messages.append({"role": "assistant", "content": assistant_message_content})

            # Save updated history
            self._save_history()

            # Speak the response
            self._speak(assistant_message_content)

            return assistant_message_content

        except requests.exceptions.Timeout:
             log.error(f"Request to LM Studio timed out ({self.lm_studio_url}).")
             self.messages.pop() # Remove user message that failed
             self._save_history()
             # Return an error message *to the user*? Or just None? Returning None for programmatic use.
             # Consider returning a specific error string if the calling code needs to know.
             # e.g., return "Error: The request to the language model timed out."
             return None
        except requests.exceptions.RequestException as e:
            log.error(f"Error communicating with LLM at {self.lm_studio_url}: {e}")
            self.messages.pop() # Remove user message that failed
            self._save_history()
            # e.g., return f"Error: Could not reach LM Studio. {e}"
            return None
        except json.JSONDecodeError:
             log.error("Could not decode JSON response from LM Studio.")
             self.messages.pop() # Remove user message that failed
             self._save_history()
             # e.g., return "Error: Invalid response format from LM Studio."
             return None
        except Exception as e:
            log.exception(f"An unexpected error occurred in sendUserMessage: {e}")
            # Attempt to remove the last user message if an unexpected error occurred
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
                self._save_history()
            # e.g., return f"Error: An unexpected error occurred. {e}"
            return None
