# Contents for Agents/detekt.py

import subprocess
import sys
import os
import select
import time  # Needed for sleep

BLANK_AUDIO = "[BLANK_AUDIO]"


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

    def __init__(self, server_path, activation_phrase, activation_callback,  length,
                 need_activation):
        """
        Initializes the WhisperStream.

        Args:
            server_path (str): Path to the whisper-server executable.
            activation_phrase (str): The phrase to listen for to start streaming.
                                     Matching is case-insensitive.
            length (int): Length of the audio chunk to process.
            activation_callback (callable): Function called once on activation.
        """
        if not os.path.exists(server_path):
            raise FileNotFoundError(f"Server executable not found at: {server_path}")
        if not os.access(server_path, os.X_OK):
            raise PermissionError(f"Server executable not executable: {server_path}")
        self.length = int(length * 1000)  # Convert to milliseconds
        self.server_path = server_path
        self.activation_phrase = activation_phrase.lower()
        self.activation_callback = activation_callback

        self.process = None
        self.activated = False if need_activation else True
        self._char_buffer = ""  # Buffer for incoming characters
        self.bob = ""  # Buffer for incoming characters
        self._word_detection_buffer = ""  # Buffer used before activation to detect phrase
        self._stopped = False  # Flag to signal stopping
        self._ready = False

    def ask(self):
        """
        Starts the whisper-server process and runs the main processing loop.
        This method will block until the server process exits or stop() is called.
        """
        if self.process and self.process.poll() is None:
            print("WhisperStream is already running.", file=sys.stderr)
            return

        print(f"Starting whisper-server: {self.server_path}", file=sys.stderr)
        self._char_buffer = ""
        self._word_detection_buffer = ""
        self._stopped = False

        try:
            self.process = subprocess.Popen(
                [f"./llm.sh"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                text=True,  # Decode output as text

            )

            print("WhisperStream started. Running processing loop...", file=sys.stderr)
            return self._run_processing_loop()

        except Exception as e:
            print(f"Error starting or running whisper-server: {e}", file=sys.stderr)
            self.process = None
        finally:
            # Ensure cleanup happens if loop exits unexpectedly
            if not self._stopped:
                self.stop()  # Call stop if not already called
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
                    char = self.process.stdout.readline()
                    if char:
                        # Append character and process the buffer
                        # Process the incoming chunk for ANSI codes and structure
                        current_chunk = char.replace('\n', '') # Remove newline first

                        clear_code = '\x1b[2K'
                        carriage_return = '\r'

                        # Strategy: Handle \x1b[2K first as it clears the line conceptually before \r might reposition the cursor.
                        if clear_code in current_chunk:
                            parts = current_chunk.split(clear_code)
                            # The effective content is what comes *after* the last clear code
                            effective_content = parts[-1]

                            # Determine the base buffer to append/overwrite onto:
                            # We conceptually clear the line first, so we operate relative to the last \r in the *existing* buffer.
                            last_r_in_buffer = self._char_buffer.rfind(carriage_return)
                            if last_r_in_buffer != -1:
                                base_buffer = self._char_buffer[:last_r_in_buffer] # Content before the line start
                            else:
                                base_buffer = "" # Clear implies starting fresh if no previous line detected

                            # Now process the effective_content after the clear code
                            if effective_content.startswith(carriage_return):
                                # Case: ...\x1b[2K\rnew_stuff -> Overwrite line with new_stuff
                                self._char_buffer = base_buffer + carriage_return + effective_content[len(carriage_return):]
                            elif carriage_return in effective_content:
                                # Case: ...\x1b[2K... \r ... -> Ambiguous, safest is overwrite line with all effective content
                                # Treat the \r within the effective content as cursor positioning *after* the clear.
                                # Example: "abc\x1b[2Kdef\rghi" -> clear line, write "def", go to start, write "ghi" -> final "ghi"
                                sub_parts = effective_content.split(carriage_return)
                                final_line_content = sub_parts[-1] # Content after the last \r dictates the final state
                                self._char_buffer = base_buffer + carriage_return + final_line_content
                            else:
                                # Case: ...\x1b[2Knew_stuff (no \r) -> Append new_stuff after clearing the line segment
                                # This usually means clearing from cursor to end, then writing. Append to base.
                                self._char_buffer = base_buffer + effective_content

                        # Handle chunks without clear code, but potentially containing just \r for overwrite
                        elif carriage_return in current_chunk:
                            # Split chunk by \r. Each part after a \r overwrites the current line.
                            parts = current_chunk.split(carriage_return)
                            for i, part in enumerate(parts):
                                if i == 0:
                                    # Append the first part normally (unless buffer is empty and chunk starts with \r)
                                    if not (len(self._char_buffer) == 0 and i == 0 and current_chunk.startswith(carriage_return)):
                                      self._char_buffer += part
                                # Subsequent parts (or the first part if the chunk started with \r) overwrite the line
                                if i > 0 or (i == 0 and current_chunk.startswith(carriage_return)):
                                    last_r_in_buffer = self._char_buffer.rfind(carriage_return)
                                    current_line_content = part # The content for the current line segment
                                    if last_r_in_buffer != -1:
                                        # Overwrite from the last \r
                                        self._char_buffer = self._char_buffer[:last_r_in_buffer] + carriage_return + current_line_content
                                    else:
                                        # No prior \r found in buffer, this \r effectively starts a new line
                                        self._char_buffer = carriage_return + current_line_content
                        else:
                            # No clear code or carriage return, just append the chunk
                            self._char_buffer += current_chunk

                        # --- End of new logic block ---


                        self.bob += " "+self._char_buffer.strip()
                        print("Current buffer:", self.bob, file=sys.stderr)
                        g = self._process_buffer()
                        if g: return g
                    else:
                        # Empty read indicates EOF
                        print("Reached EOF for server output.", file=sys.stderr)
                        break  # Exit loop if process output pipe closes
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
        if ("[Start speaking]") in self.bob and not self._ready:
            self._ready = True
            self.bob = ""
            print("Please start speaking!")
            return
        if not self._ready:
            return
        if not self.activated:
            if self.activation_phrase in  self.bob.lower():
                print("Activation phrase received")
                self.activated = True
                self.bob = self.bob.lower().split(self.activation_phrase)[-1]
            else: return
        self.bob = self.bob.replace("[Start speaking]", BLANK_AUDIO) \
            .replace("(keyboard clicking)", BLANK_AUDIO) \
            .replace("[typing sounds]", BLANK_AUDIO) \
            .replace("[ Silence ]", BLANK_AUDIO) \
            .replace('(whooshing)', BLANK_AUDIO) \
            .replace('(sighs)', BLANK_AUDIO)

        words = [i for i in self.bob.split(" ") if normalize_word(i)]
        return self._handle_words(words)


    def _handle_words(self, words):
        """Handles a complete word, checking for activation or streaming."""
        # print(f"Handling word: '{word}'", file=sys.stderr) # Debug
        if len(words) >= 2 and words[-1] == BLANK_AUDIO and any(i for i in words if i != BLANK_AUDIO):
            self.bob = ""
            # Ignore repeated blank audio signals
            return " ".join([i for i in words if i != BLANK_AUDIO])
        return None

    def stop(self):
        """Signals the processing loop to stop and terminates the server process."""
        if self._stopped:
            # print("Stop already called.", file=sys.stderr)
            return

        print("Stopping WhisperStream...", file=sys.stderr)
        self._stopped = True  # Signal the loop to exit

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
