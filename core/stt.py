"""
Speech-to-Text engine for Myanmar Language using Google STT.
ပေါ့ပါးမြန်ဆန်ပြီး RAM/MKL Error လုံးဝမတက်ပါ။
"""
import io
import wave
import numpy as np
import speech_recognition as sr

class WhisperSTT:
    """WhisperSTT class name အတိုင်း interface မပျက်စေဘဲ Google Myanmar STT ဖြင့် အစားထိုးထားသည်"""
    def __init__(self, model_name: str = "tiny", language: str = "my"):
        self.recognizer = sr.Recognizer()
        self.language = "my-MM"  # မြန်မာဘာသာ (Burmese)
        print("[STT] Google Myanmar Speech-to-Text အဆင်သင့်ဖြစ်ပါပြီ။")

    def transcribe(self, audio_np: np.ndarray) -> str:
        """float32 mono 16kHz audio array ကို မြန်မာစာသားအဖြစ် ပြောင်းလဲပေးခြင်း"""
        try:
            # float32 to int16 PCM bytes
            audio_int16 = (audio_np * 32767).astype(np.int16)
            byte_io = io.BytesIO()
            with wave.open(byte_io, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(audio_int16.tobytes())
            
            byte_io.seek(0)
            with sr.AudioFile(byte_io) as source:
                audio_data = self.recognizer.record(source)
                text = self.recognizer.recognize_google(audio_data, language=self.language)
                return text.strip()
        except sr.UnknownValueError:
            return ""  # အသံသဲသဲကွဲကွဲမကြားရပါက
        except Exception as e:
            print(f"[STT Error] {e}")
            return ""