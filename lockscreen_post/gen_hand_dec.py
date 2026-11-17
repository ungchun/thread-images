"""손에 든 iPhone 생활 사진(화면은 크로마키 초록)을 만든다. 화면에는 나중에 잠금화면을 원근 합성한다.

    GEMINI_API_KEY=... python gen_hand_dec.py <jp|tw> <round> [model]

12월 공식 글용: 나라별 겨울 장면만 바꾼 gen_hand.py(10/27 운영 글) 복제본.
"""
import os
import sys

from PIL import Image

sys.path.insert(0, "/Users/yoo/github/Trace_iOS/.claude/skills/imagegen")
from nanobanana import generate  # noqa: E402

OUT_ROOT = os.path.expanduser("~/Desktop/trace-imagegen/cloud/dec-month/hand")

COMMON = (
    "a young woman's left hand holds a modern iPhone upright in portrait orientation, the phone facing the camera "
    "almost straight on (only a very slight natural tilt), with a clear transparent phone case. Her fingers wrap "
    "naturally around the sides and bottom, the thumb resting on the side edge, never covering the screen. The phone "
    "fills about 78% of the image height, held close to the camera, and sits slightly right of center. The ENTIRE screen is a perfectly flat, "
    "uniform pure chroma-key green (#00FF00) with no reflections, no glare, no icons, no text, no notch content except "
    "the black Dynamic Island pill at the top. Natural skin, short neat nails with a nude manicure. Shallow depth of "
    "field, like a real photo posted on social media. Output aspect ratio exactly like the given blank image (4:5 portrait)."
)

SCENES = {
    # 도쿄 12월: 코트 소매, 가로수 일루미네이션 보케 — 일본 12월 글의 단골 배경
    "jp": "A close-up, realistic casual smartphone photo taken outdoors on a Tokyo street on a crisp December late afternoon: "
          "the sleeve of a beige wool coat with a cream knit cuff at her wrist. Background: softly blurred tree-lined "
          "street with warm golden winter illumination lights as round bokeh, no readable signs or text anywhere, cool clear air, "
          "natural light, slightly warm tones. ",
    # 타이베이 12월: 따뜻한 날씨라 얇은 니트, 카페 창가·작은 트리·밀크티
    "tw": "A realistic casual smartphone photo taken in a cozy Taipei cafe by the window on a mild December afternoon: "
          "the sleeve of a light oatmeal knit cardigan at her wrist. Background: softly blurred wooden table with a "
          "glass of milk tea, a small Christmas tree with warm fairy lights as bokeh, daylight from the window, "
          "slightly warm tones. ",
}



def main():
    country, rnd = sys.argv[1], sys.argv[2]
    model = sys.argv[3] if len(sys.argv) > 3 else "gemini-3-pro-image"
    OUT = os.path.join(OUT_ROOT, country)
    PROMPT = SCENES[country] + COMMON
    os.makedirs(OUT, exist_ok=True)
    tmp = os.path.join(OUT, ".tmp-%s" % rnd)
    os.makedirs(tmp, exist_ok=True)
    blank = os.path.join(tmp, "blank.png")
    Image.new("RGB", (1440 // 4, 1800 // 4), (200, 200, 196)).save(blank)
    out = os.path.join(OUT, "hand-r%s.png" % rnd)
    err = generate("gemini", os.environ["GEMINI_API_KEY"], model, PROMPT, [blank], out, tmp)
    os.remove(blank)
    os.rmdir(tmp)
    print(out, err or Image.open(out).size)


if __name__ == "__main__":
    main()
