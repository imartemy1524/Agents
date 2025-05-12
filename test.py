import sys
import time
from detekt import WhisperStream
from llm_agent import LLMAgent

SERVER_EXECUTABLE = "./result/bin/whisper-stream"
ACTIVATION_PHRASE = "hi"
AUDIO_CHUNK_LENGTH = 4

# --- Global Variables ---
streamer = None
agent = None

def handle_user_message(text):
    print(f"\nUser said: '{text}'")

    # Check for stop commands
    stop_commands = {"stop", "exit", "quit", "bye", "goodbye", "die"}
    if text.lower().strip() in stop_commands:
        print("Stop command received. Shutting down.")
        if agent:
            agent._speak("Goodbye!") # Use agent's TTS
        if streamer:
            streamer.stop()
        return # Stop processing further

    # Send the message to the LLM Agent
    if agent:
        print("Sending message to LLM...")
        response = agent.sendUserMessage(text)
        if response:
            print(f"LLM Response: {response}")
            # TTS is handled within sendUserMessage
        else:
            print("LLM did not provide a response.")
            # Optionally speak an error message here if needed
            # agent._speak("Sorry, I couldn't get a response.")
    else:
        print("Error: LLMAgent not initialized.", file=sys.stderr)

    # After handling the message, WhisperStream should automatically go back to listening
    # for the activation phrase if configured correctly (assuming need_activation=True initially).
    # If it doesn't, you might need to manually restart listening or adjust WhisperStream settings.
    print(f"\n--- Listening for activation phrase '{ACTIVATION_PHRASE}' again... ---")


# --- Main Execution ---
if __name__ == "__main__":
    try:
        need_r = True
        while 1:
            agent = LLMAgent(history_file="Agents/data.json")

            #  need_activation=True means it waits for the phrase initially.
            streamer = WhisperStream(
                server_path=SERVER_EXECUTABLE,
                activation_phrase=ACTIVATION_PHRASE,
                length=AUDIO_CHUNK_LENGTH,
                need_activation=need_r # Start by waiting for activation phrase
            )
            need_r = False
            msg = streamer.ask()
            streamer.stop()
            handle_user_message(msg)


    except FileNotFoundError as e:
        print(f"\nError: {e}", file=sys.stderr)
        print(f"Ensure '{SERVER_EXECUTABLE}' exists and has execute permissions.", file=sys.stderr)
    except PermissionError as e:
        print(f"\nError: {e}", file=sys.stderr)
        print(f"Ensure '{SERVER_EXECUTABLE}' has execute permissions (chmod +x).", file=sys.stderr)
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Stopping...", file=sys.stderr)
    except ImportError as e:
         print(f"\nImport Error: {e}. Make sure 'detekt' library and LLMAgent are available.", file=sys.stderr)
    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
    finally:
        # Ensure streamer is stopped cleanly
        if streamer and not streamer._stopped: # Check if streamer exists and _stopped flag
             print("\nEnsuring WhisperStream is stopped...")
             streamer.stop()
        # No need to call agent.stop() unless it has specific cleanup tasks
        print("\n--- Script finished ---")
