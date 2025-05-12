# Contents for Agents/detekt.py

import subprocess
import sys
import os
import select
import time # Needed for sleep
def normalize_word(word):
    """
    Normalizes a word by removing punctuation and converting to lowercase.
    This is a placeholder function; actual implementation may vary.
    """
    # Example normalization: remove punctuation and convert to lowercase
    return ''.join(char for char in word if char.isalnum()).lower()
class WhisperStream:
    """
    Manages a whisper-server process, detects an activation phrase,
    and streams subsequent text output word by word, operating in a single thread.
    """
    def __init__(self, server_path, activation_phrase, activation_callback, handle_user_message_callback):
        """
        Initializes the WhisperStream.

        Args:
            server_path (str): Path to the whisper-server executable.
            activation_phrase (str): The phrase to listen for to start streaming.
                                     Matching is case-insensitive.
            activation_callback (callable): Function called once on activation.
            handle_user_message_callback (callable): Function called with each word after activation.
        """
        if not os.path.exists(server_path):
             raise FileNotFoundError(f"Server executable not found at: {server_path}")
        if not os.access(server_path, os.X_OK):
             raise PermissionError(f"Server executable not executable: {server_path}")

        self.server_path = server_path
        self.activation_phrase = activation_phrase.lower()
        self.activation_callback = activation_callback
        self.handle_user_message_callback = handle_user_message_callback

        self.process = None
        self.activated = False
        self._char_buffer = "" # Buffer for incoming characters
        self._word_detection_buffer = "" # Buffer used before activation to detect phrase
        self._stopped = False # Flag to signal stopping

    def start(self):
        """
        Starts the whisper-server process and runs the main processing loop.
        This method will block until the server process exits or stop() is called.
        """
        if self.process and self.process.poll() is None:
            print("WhisperStream is already running.", file=sys.stderr)
            return

        print(f"Starting whisper-server: {self.server_path}", file=sys.stderr)
        self.activated = False
        self._char_buffer = ""
        self._word_detection_buffer = ""
        self._stopped = False

        try:
            self.process = subprocess.Popen(
                [self.server_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Combine stderr with stdout
                text=True, # Decode output as text
            )

            print("WhisperStream started. Running processing loop...", file=sys.stderr)
            self._run_processing_loop()

        except Exception as e:
            print(f"Error starting or running whisper-server: {e}", file=sys.stderr)
            self.process = None
        finally:
            # Ensure cleanup happens if loop exits unexpectedly
            if not self._stopped:
                 self.stop() # Call stop if not already called
            print("WhisperStream processing loop finished.", file=sys.stderr)


    def _run_processing_loop(self):
        """The main loop reading and processing output character by character."""
        while not self._stopped:
            if not self.process or self.process.poll() is not None:
                print("Server process terminated unexpectedly.", file=sys.stderr)
                break

            # Check if stdout is readable using select with a timeout
            readable, _, _ = select.select([self.process.stdout], [], [], 0.1)

            if readable:
                try:
                    char = self.process.stdout.read(1)

                    if char:
                        # Append character and process the buffer
                        self._char_buffer += char
                        self._process_buffer()
                    else:
                        # Empty read indicates EOF
                        print("Reached EOF for server output.", file=sys.stderr)
                        break # Exit loop if process output pipe closes
                except Exception as e:
                     # Handle potential errors during read
                     print(f"Error reading from server process: {e}", file=sys.stderr)
                     break
            else:
                # Select timed out, no data available right now.
                # Optional: time.sleep(0.01) - small sleep to prevent tight loop if needed,
                # but select timeout already provides waiting.
                pass

        # Loop finished (either stopped, EOF, or error)
        exit_code = self.process.poll() if self.process else 'N/A'
        print(f"Exiting processing loop. Server exit code: {exit_code}", file=sys.stderr)


    def _process_buffer(self):
        """Processes the character buffer to find words and handle activation."""
        # Process words separated by whitespace (space, tab, newline)
        while True:
            found_space = -1
            for i, char in enumerate(self._char_buffer):
                 if char.isspace():
                     found_space = i
                     break
            if found_space != -1:
                 word = self._char_buffer[:found_space].strip()
                 word = normalize_word(word) # Normalize the word (e.g., remove punctuation)
                 # Keep the whitespace character for potential multi-space scenarios? No, discard.
                 self._char_buffer = self._char_buffer[found_space+1:]

                 if word: # Don't process empty strings from multiple spaces
                     self._handle_word(word)
            else:
                 # No more whitespace found in the current buffer, wait for more chars
                 break

    def _handle_word(self, word):
        """Handles a complete word, checking for activation or streaming."""
        # print(f"Handling word: '{word}'", file=sys.stderr) # Debug
        if not self.activated:
            # Append to the detection buffer (case-insensitive check later)
            self._word_detection_buffer += word + " " # Add space to separate words
            # Check if the activation phrase is present
            if self.activation_phrase in self._word_detection_buffer.lower():
                print(f"\n--- Activation phrase '{self.activation_phrase}' detected! ---", file=sys.stderr)
                self.activated = True
                self.activation_callback()

                # Find where the phrase ends in the buffer
                phrase_end_index = self._word_detection_buffer.lower().find(self.activation_phrase) + len(self.activation_phrase)

                # Extract words *after* the phrase from the buffer
                remaining_text = self._word_detection_buffer[phrase_end_index:].strip()
                self._word_detection_buffer = "" # Clear detection buffer

                if remaining_text:
                    # Stream the remaining words found in the buffer immediately
                    print(f"Streaming remaining words from buffer: '{remaining_text}'", file=sys.stderr) # Debug
                    remaining_words = remaining_text.split()
                    self._word_detection_buffer = remaining_words
            else:
                 # Limit buffer size to prevent excessive memory use if phrase never comes
                 max_buffer_len = len(self.activation_phrase) + 1000 # Keep phrase + some context
                 self._word_detection_buffer = self._word_detection_buffer[-max_buffer_len:]


        elif ("blankaudio".lower() in self._word_detection_buffer or "2k" in self._word_detection_buffer) \
                and (g:= self._word_detection_buffer
                .replace("blankaudio", "")
                .replace("2k", "").strip()):
            # Already activated, stream the word
            self.handle_user_message_callback(g)
            self._word_detection_buffer = ""
            self.activated = False
        else:
            self._word_detection_buffer += word + " " # Add space to separate words

    def stop(self):
        """Signals the processing loop to stop and terminates the server process."""
        if self._stopped:
             # print("Stop already called.", file=sys.stderr)
             return

        print("Stopping WhisperStream...", file=sys.stderr)
        self._stopped = True # Signal the loop to exit

        if self.process and self.process.poll() is None:
            print("Terminating whisper-server process...", file=sys.stderr)
            try:
                self.process.terminate()
                try:
                    # Wait briefly for termination, but loop should exit via _stopped flag
                    self.process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    print("Process did not terminate quickly, killing...", file=sys.stderr)
                    self.process.kill()
                print("Process stopped.", file=sys.stderr)
            except Exception as e:
                print(f"Error stopping whisper-server process: {e}", file=sys.stderr)
            finally:
                 self.process = None
        else:
            print("WhisperStream process already stopped or not started.", file=sys.stderr)

        print("WhisperStream stopped.", file=sys.stderr)


# --- Example Usage ---
if __name__ == "__main__":
    SERVER_EXECUTABLE = "./result/bin/whisper-stream"
    ACTIVATION_PHRASE = "welcome" # Case-insensitive

    def on_activation_detected():
        print("\n********************************")
        print(" WOO! ACTIVATION DETECTED! ")
        print("********************************\n")

    def on_stream_received(text):
        # Print word followed by a space
        print("User asked a message", text)

    streamer = None
    try:
        streamer = WhisperStream(
            server_path=SERVER_EXECUTABLE,
            activation_phrase=ACTIVATION_PHRASE,
            activation_callback=on_activation_detected,
            handle_user_message_callback=on_stream_received
        )

        # The start() method now blocks until finished or stopped
        print(f"\n--- WhisperStream starting. Listening for '{ACTIVATION_PHRASE}'. Press Ctrl+C to stop ---")
        streamer.start() # This call will run the loop and block here

    except FileNotFoundError as e:
         print(f"\nError: {e}", file=sys.stderr)
         print("Ensure 'whisper-server' exists at the specified path and has execute permissions.", file=sys.stderr)
    except PermissionError as e:
         print(f"\nError: {e}", file=sys.stderr)
         print("Ensure 'whisper-server' has execute permissions (chmod +x).", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Stopping...", file=sys.stderr)
        # streamer should already be defined unless init failed
        if streamer:
             streamer.stop()
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        # Ensure stop is called even on unexpected errors if streamer exists
        if streamer and not streamer._stopped:
             streamer.stop()
    finally:
        # Stop might have already been called, but call again ensures cleanup attempt
        # if loop exited abnormally without setting _stopped flag or calling stop.
        # The stop() method handles being called multiple times.
        # if streamer:
        #     streamer.stop() # Redundant due to checks above and in start()'s finally block
        print("\n--- Script finished ---")
