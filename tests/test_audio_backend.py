"""Exercise SoundDeviceBackend callbacks with a fake 'sounddevice' module (48 kHz device)."""
import array
import sys
import types

streams = []


class _S:
    def __init__(self, samplerate, channels, dtype, blocksize, callback, latency):
        if samplerate == 16000:
            raise RuntimeError("Invalid sample rate")       # force the 48 kHz conversion path
        self.rate, self.block, self.cb = samplerate, blocksize, callback
        streams.append(self)

    def start(self): pass
    def stop(self): pass
    def close(self): pass


fake = types.ModuleType("sounddevice")
fake.RawInputStream = fake.RawOutputStream = _S
sys.modules["sounddevice"] = fake

from tda.calls import FRAME_BYTES, FRAME_SAMPLES, SoundDeviceBackend  # noqa: E402

got = []
b = SoundDeviceBackend()
b.start(got.append)
assert b.input_ok and b.output_ok and len(streams) == 2, b.error
mic, spk = streams
assert mic.rate == 48000 and mic.block == FRAME_SAMPLES * 3

# microphone: 960 samples at 48 kHz -> one 320-sample frame
mic.cb(array.array("h", [300] * 960).tobytes(), 960, None, None)
assert len(got) == 1 and len(got[0]) == FRAME_BYTES and array.array("h", got[0])[0] == 300

# speaker: silence until 3 frames are buffered, then upsampled x3
out = bytearray(960 * 2)
spk.cb(out, 960, None, None)
assert out == bytearray(len(out))
frame = array.array("h", range(FRAME_SAMPLES)).tobytes()
for _ in range(3):
    b.play(frame)
spk.cb(out, 960, None, None)
s = array.array("h", bytes(out))
assert list(s[:6]) == [0, 0, 0, 1, 1, 1], list(s[:6])
print("AUDIO BACKEND TEST PASSED (48 kHz device, resampling ok)")
