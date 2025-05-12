import requests
import json
import os
import subprocess
import sys

class LLMAgent:
    """
    An agent to communicate with a local LLM (like LM Studio),
    manage conversation history, and provide text-to-speech output.
    """
    def __init__(self, history_file="Agents/data.json", lm_studio_url="http://localhost:1234/v1/chat/completions"):
        """
        Initializes the agent, loads history, and sets up configuration.

        Args:
            history_file (str): Path to the JSON file for storing conversation history.
            lm_studio_url (str): The API endpoint for the LM Studio compatible server.
        """
        self.history_file = history_file
        self.lm_studio_url = lm_studio_url
        self.messages = self._load_history()
        # Add a default system prompt if history is empty or lacks one
        if not self.messages or not any(m['role'] == 'system' for m in self.messages):
             # Use the refined system prompt
             new_system_prompt = "You are a concise and helpful AI assistant. Respond clearly and briefly. User input may contain transcription errors or repeated words due to voice recognition; interpret the user's likely intent despite these potential inaccuracies, he may hav echo on his side - ignore it and pretend as if it was a single sentence."
             # Check if there's an old system prompt to replace, otherwise insert
             system_prompt_index = -1
             for i, msg in enumerate(self.messages):
                 if msg.get('role') == 'system':
                     system_prompt_index = i
                     break
             if system_prompt_index != -1:
                 self.messages[system_prompt_index]['content'] = new_system_prompt
             else:
                self.messages.insert(0, {"role": "system", "content": new_system_prompt})
             # Save history immediately after potentially adding/updating system prompt
             self._save_history()
        print(f"LLMAgent initialized. History loaded from {self.history_file}")


    def _load_history(self):
        """Loads conversation history from the JSON file."""
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not decode JSON from {self.history_file}. Starting with empty history.", file=sys.stderr)
                return []
            except Exception as e:
                 print(f"Error loading history from {self.history_file}: {e}", file=sys.stderr)
                 return []
        return []

    def _save_history(self):
        """Saves the current conversation history to the JSON file."""
        try:
            # Ensure the directory exists before trying to save
            os.makedirs(os.path.dirname(self.history_file) or '.', exist_ok=True)
            with open(self.history_file, 'w') as f:
                json.dump(self.messages, f, indent=2)
        except Exception as e:
            print(f"Error saving history to {self.history_file}: {e}", file=sys.stderr)

    def _speak(self, text):
        """Uses macOS 'say' command for text-to-speech."""
        if sys.platform != 'darwin':
            print("TTS Info: 'say' command is only available on macOS. Skipping TTS.", file=sys.stderr)
            return
        if not text:
             print("TTS Info: No text provided to speak.", file=sys.stderr)
             return
        try:
            # Use subprocess.run for better control and error handling
            subprocess.run(['say', "-r", "300", text], check=True, capture_output=True, text=True)
            # print(f"TTS Spoke: '{text}'") # Optional: log successful TTS
        except FileNotFoundError:
            print("Error: 'say' command not found. Is it installed and in PATH?", file=sys.stderr)
        except subprocess.CalledProcessError as e:
            print(f"Error during TTS execution: {e}", file=sys.stderr)
            print(f"TTS Stderr: {e.stderr}", file=sys.stderr) # Log stderr for debugging
        except Exception as e:
            print(f"An unexpected error occurred during TTS: {e}", file=sys.stderr)


    def sendUserMessage(self, user_message):
        """
        Sends a user message to the LLM, gets the response, speaks it, saves history, and returns the response.

        Args:
            user_message (str): The message from the user.

        Returns:
            str or None: The text response from the LLM, or None if an error occurs or the response is empty.
        """
        if not user_message:
            print("User message is empty, skipping.", file=sys.stderr)
            return None

        # Append user message to history
        self.messages.append({"role": "user", "content": user_message})

        try:
            # Prepare request payload
            # Ensure messages payload is correctly formatted list of dicts
            payload = {
                "messages": [msg for msg in self.messages if isinstance(msg, dict) and 'role' in msg and 'content' in msg],
                "temperature": 0.4, # Example temperature
                # Add other parameters like max_tokens if needed by your LM Studio model/settings
                "stream": False # Keep response handling simple
            }

            # Send request to LM Studio
            print(f"Sending request to {self.lm_studio_url}...")
            response = requests.post(self.lm_studio_url, json=payload, timeout=120) # Added timeout
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

            # Process response
            response_data = response.json()
            assistant_message_content = ""
            if response_data.get("choices") and len(response_data["choices"]) > 0:
                message = response_data["choices"][0].get("message")
                if message and message.get("content"):
                     raw_content = message["content"].strip()
                     # Remove <think>...</think> blocks if they exist at the start
                     think_end_tag = '</think>'
                     think_start_tag = '<think>' # Check for start tag too for robustness

                     # Find the first closing tag
                     think_end_index = raw_content.find(think_end_tag)

                     if think_end_index != -1 and raw_content.startswith(think_start_tag):
                         # If <think> is at the start and </think> is found,
                         # extract the content after </think>
                         assistant_message_content = raw_content[think_end_index + len(think_end_tag):].strip()
                         if not assistant_message_content:
                              print(f"Warning: Response contained only a <think> block: {raw_content}", file=sys.stderr)
                              # Keep it empty, the next check will handle it.
                     else:
                         # No think block found at the start, or tags are mismatched/missing
                         # Use the raw content as is
                         assistant_message_content = raw_content

            if not assistant_message_content:
                 print("Warning: Received empty or improperly formatted response from LM Studio (after potential <think> removal).", file=sys.stderr)
                 # Remove the user message that got no reply? Optional, but might prevent loops.
                 self.messages.pop()
                 return None # Return None

            print(f"LLM Raw Response: '{assistant_message_content}'")

            # Append assistant response to history
            self.messages.append({"role": "assistant", "content": assistant_message_content})

            # Save updated history
            self._save_history()

            # Speak the response
            self._speak(assistant_message_content)

            return assistant_message_content

        except requests.exceptions.Timeout:
             print(f"Error: Request to LM Studio timed out ({self.lm_studio_url}).", file=sys.stderr)
             self.messages.pop() # Remove user message that failed
             return "Error: The request to the language model timed out."
        except requests.exceptions.RequestException as e:
            print(f"Error communicating with LM Studio at {self.lm_studio_url}: {e}", file=sys.stderr)
            self.messages.pop() # Remove user message that failed
            return f"Error: Could not reach LM Studio. {e}" # Return error message
        except json.JSONDecodeError:
             print("Error: Could not decode JSON response from LM Studio.", file=sys.stderr)
             self.messages.pop() # Remove user message that failed
             return "Error: Invalid response format from LM Studio."
        except Exception as e:
            print(f"An unexpected error occurred in sendUserMessage: {e}", file=sys.stderr)
            # Attempt to remove the last user message if an unexpected error occurred
            if self.messages and self.messages[-1].get("role") == "user":
                self.messages.pop()
            return f"Error: An unexpected error occurred. {e}" # Return error message
