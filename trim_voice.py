# လိုအပ်ပါက: pip install pydub
from pydub import AudioSegment

input_file = "မိန်းမ(09423542801)_20260927122224.mp3"
audio = AudioSegment.from_file(input_file)

# အမျိုးသမီးအသံ သီးသန့် အချိန်ပိုင်းများ (Milliseconds)
female_segments = [
    (1000, 2500),
    (3200, 8800),
    (11000, 14200),
    (15500, 18000),
    (19800, 21000),
    (22800, 24000),
    (25000, 27500),
    (29800, 30800),
]

# အပိုင်းများကို ပေါင်းစပ်ထုတ်ယူခြင်း
clean_voice = AudioSegment.empty()
for start, end in female_segments:
    clean_voice += audio[start:end]

output_file = "female_voice_clean.mp3"
clean_voice.export(output_file, format="mp3", bitrate="192k")
print(f"အောင်မြင်စွာ ဖြတ်ထုတ်ပြီးပါပြီ -> {output_file}")