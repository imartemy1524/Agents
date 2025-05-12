\
import subprocess
import threading
import sys
import os
import select

class WhisperStream:
    """
    Manages a whisper-server process, detects an activation phrase,
    and streams subsequent text output.
    """
    def __init__(self, server_path, activation_phrase, activation_callback, stream_callback):
        """
        Initializes the WhisperStream.

        Args:
            server_path (str): Path to the whisper-server executable.
            activation_phrase (str): The phrase to listen for to start streaming.
                                     Matching is case-insensitive.
            activation_callback (callable): A function to call when the activation
                                            phrase is detected. Takes no arguments.
            stream_callback (callable): A function to call with subsequent text chunks
                                        after activation. Takes one string argument.
        """
        if not os.path.exists(server_path):
             raise FileNotFoundError(f"Server executable not found at: {server_path}")
        if not os.access(server_path, os.X_OK):
             raise PermissionError(f"Server executable not executable: {server_path}")

        self.server_path = server_path
        self.activation_phrase = activation_phrase.lower() # Normalize for case-insensitive compare
        self.activation_callback = activation_callback
        self.stream_callback = stream_callback

        self.process = None
        self._read_thread = None
        self._stop_event = threading.Event()
        self.activated = False
        self._output_buffer = ""

    def start(self):
        """Starts the whisper-server process and begins listening."""
        if self.process and self.process.poll() is None:
            print("WhisperStream is already running.", file=sys.stderr)
            return

        print(f"Starting whisper-server: {self.server_path}", file=sys.stderr)
        self.activated = False
        self._output_buffer = ""
        self._stop_event.clear()

        try:
            # Start the server process
            # We use Popen for non-blocking interaction.
            # stdout=PIPE captures output, stderr=STDOUT merges stderr for simplicity here.
            # text=True decodes output as text (uses default encoding).
            # bufsize=1 enables line buffering.
            self.process = subprocess.Popen(
                [self.server_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, # Combine stderr with stdout
                text=True,
                bufsize=1 # Line buffered
            )

            # Start a thread to read the output pipe non-blockingly
            self._read_thread = threading.Thread(target=self._read_output_loop, daemon=True)
            self._read_thread.start()
            print("WhisperStream started and listening.", file=sys.stderr)

        except Exception as e:
            print(f"Error starting whisper-server: {e}", file=sys.stderr)
            self.process = None # Ensure process is None if startup failed

    def _read_output_loop(self):
        """Runs in a separate thread to read and process server output."""
        try:
            # Use select for non-blocking read, checking if the process is alive
            while not self._stop_event.is_set() and self.process and self.process.poll() is None:
                if self.process.stdout and select.select([self.process.stdout], [], [], 0.1)[0]:
                    line = self.process.stdout.readline()
                    if line:
                        self._process_line(line)
                    else:
                        # EOF, process likely exited
                        break
                # Small sleep to prevent busy-waiting if select times out immediately
                # threading.Event().wait(0.01) # Alternative to time.sleep(0.01)

            exit_code = self.process.poll() if self.process else 'N/A'
            print(f"Whisper-server process exited with code: {exit_code}. Read loop ending.", file=sys.stderr)

        except Exception as e:
            if not self._stop_event.is_set(): # Don't report errors if we initiated stop
                 print(f"Error reading whisper-server output: {e}", file=sys.stderr)
        finally:
            print("Exiting read thread.", file=sys.stderr)


    def _process_line(self, line: str):
        """Processes a single line of output from the server."""
        line = line.strip() # Remove leading/trailing whitespace including newline
        if not line:
             return # Ignore empty lines

        # For debugging: print raw lines
        # print(f"RAW: {line}", file=sys.stderr)

        if not self.activated:
            # Append line to buffer and check for activation phrase
            # This simplistic approach assumes the phrase doesn't span lines often
            self._output_buffer += line + " " # Add space to separate words across lines
            lower_buffer = self._output_buffer.lower()

            try:
                phrase_index = lower_buffer.index(self.activation_phrase)
                # Found the phrase!
                self.activated = True
                print(f"\n--- Activation phrase '{self.activation_phrase}' detected! ---", file=sys.stderr)
                self.activation_callback() # Trigger the activation callback

                # Extract text *after* the phrase in the current buffer
                start_streaming_from = phrase_index + len(self.activation_phrase)
                remaining_text = self._output_buffer[start_streaming_from:].strip()

                self._output_buffer = "" # Clear buffer

                if remaining_text:
                     print(f"Streaming initial part: '{remaining_text}'", file=sys.stderr) # Debug
                     self.stream_callback(remaining_text) # Stream the remainder

            except ValueError:
                # Phrase not found yet, keep buffering. Limit buffer size?
                # Maybe add a buffer size limit to prevent memory issues if activation never happens.
                max_buffer_chars = 1024 # Example limit
                if len(self._output_buffer) > max_buffer_chars:
                    self._output_buffer = self._output_buffer[-max_buffer_chars:] # Keep only the last N chars
                pass # Phrase not found yet

        else:
            # Already activated, stream the entire line
            # print(f"Streaming subsequent: '{line}'", file=sys.stderr) # Debug
            self.stream_callback(line)

    def stop(self):
        """Stops the whisper-server process and cleans up."""
        if not self.process or self.process.poll() is not None:
            print("WhisperStream is not running.", file=sys.stderr)
            return

        print("Stopping WhisperStream...", file=sys.stderr)
        self._stop_event.set() # Signal the read thread to stop

        if self.process:
            try:
                if self.process.poll() is None: # Check if still running
                     print("Terminating whisper-server process...", file=sys.stderr)
                     self.process.terminate() # Ask nicely first
                     try:
                         self.process.wait(timeout=2) # Wait a bit
                     except subprocess.TimeoutExpired:
                         print("Process did not terminate, killing...", file=sys.stderr)
                         self.process.kill() # Force kill
                     print("Process stopped.", file=sys.stderr)
                else:
                     print("Process already terminated.", file=sys.stderr)

            except Exception as e:
                print(f"Error stopping whisper-server process: {e}", file=sys.stderr)
            finally:
                self.process = None # Clear the process handle

        if self._read_thread and self._read_thread.is_alive():
            print("Waiting for read thread to join...", file=sys.stderr)
            self._read_thread.join(timeout=2) # Wait for the thread to finish
            if self._read_thread.is_alive():
                 print("Read thread did not join.", file=sys.stderr)
            else:
                 print("Read thread joined.", file=sys.stderr)
            self._read_thread = None

        print("WhisperStream stopped.", file=sys.stderr)


# --- Example Usage ---
if __name__ == "__main__":

    # IMPORTANT: Adjust this path relative to where you RUN this script,
    # or use an absolute path.
    # If you run this script from the root of your project, this relative path should work.
    SERVER_EXECUTABLE = "./result/bin/whisper-server"
    ACTIVATION_PHRASE = "drink tequilla" # Case-insensitive

    # --- Define your callbacks ---
    def on_activation_detected():
        """Called once when the activation phrase is heard."""
        print("\n********************************")
        print(" WOO! ACTIVATION DETECTED! ")
        print("********************************\n")
        # You could trigger other actions here, like playing a sound

    def on_stream_received(text_chunk):
        """Called for each piece of text received after activation."""
        # Print the streamed text immediately. 'end=""' prevents extra newlines
        # if the server output already contains them. 'flush=True' ensures visibility.
        print(text_chunk, end=" ", flush=True)

    # --- Create and run the streamer ---
    streamer = None
    try:
        streamer = WhisperStream(
            server_path=SERVER_EXECUTABLE,
            activation_phrase=ACTIVATION_PHRASE,
            activation_callback=on_activation_detected,
            stream_callback=on_stream_received
        )

        streamer.start()

        # Keep the main script alive until interrupted
        print("\n--- WhisperStream is running ---")
        print(f"--- Listening for '{ACTIVATION_PHRASE}' ---")
        print("--- Press Ctrl+C to stop ---")
        while True:
             # Keep main thread alive cleanly
             # Check if the process died unexpectedly
             if streamer and streamer.process and streamer.process.poll() is not None:
                 print("\n--- Whisper server process seems to have stopped unexpectedly. ---", file=sys.stderr)
                 break
             # Check if the read thread died unexpectedly (less likely with daemon=True)
             if streamer and streamer._read_thread and not streamer._read_thread.is_alive() and not streamer._stop_event.is_set():
                  print("\n--- Read thread seems to have stopped unexpectedly. ---", file=sys.stderr)
                  break
             # Sleep briefly to avoid pegging CPU in the main loop
             threading.Event().wait(1.0)


    except FileNotFoundError as e:
         print(f"\nError: {e}", file=sys.stderr)
         print("Please ensure the 'whisper-server' executable exists at the specified path", file=sys.stderr)
         print("and that you are running this script from the correct directory.", file=sys.stderr)
    except PermissionError as e:
         print(f"\nError: {e}", file=sys.stderr)
         print("Please ensure the 'whisper-server' file has execute permissions (chmod +x).", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Stopping...", file=sys.stderr)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
    finally:
        if streamer:
            streamer.stop()
        print("\n--- Script finished ---")
