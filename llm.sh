#!/run/current-system/sw/bin/bash
c=$(pwd)

$c/result/bin/whisper-stream --step 1000 --no-fallback --length 4000
