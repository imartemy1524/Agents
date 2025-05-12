from detekt import WhisperStream

SERVER_EXECUTABLE = "./result/bin/whisper-stream"
ACTIVATION_PHRASE = "hi" # Case-insensitive
audio_chunk_length = 4
def on_activation_detected():
    print("\n********************************")
    print(" WOO! ACTIVATION DETECTED! ")
    print("********************************\n")

def on_stream_received(text):
    if text == "stop" or text == "exit" or text == "quit" or text == "bye" or text == "goodbye" or text == "die":
        streamer.stop()
    # Print word followed by a space
    print("User asked a message", text)

streamer = None
try:
    need_activation = True
    while 1:
        streamer = WhisperStream(
            server_path=SERVER_EXECUTABLE,
            activation_phrase=ACTIVATION_PHRASE,
            activation_callback=on_activation_detected,
            handle_user_message_callback=on_stream_received,
            length=audio_chunk_length,
            need_activation=need_activation
        )
        need_activation = False
        text = streamer.ask()
        print("User asked a message: \n\t", text)
        if text == "stop" or text == "exit" or text == "quit" or text == "bye" or text == "goodbye" or text == "die":
            print("Bye")
            break
        streamer.stop()

    # The start() method now blocks until finished or stopped
    print(f"\n--- WhisperStream starting. Listening for '{ACTIVATION_PHRASE}'. Press Ctrl+C to stop ---")

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
