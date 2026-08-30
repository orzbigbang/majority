from __future__ import annotations

import hashlib


ANIMALS: tuple[tuple[str, str], ...] = (
    ("rabbit", "うさぎ"),
    ("cat", "ねこ"),
    ("bear", "くま"),
    ("fox", "きつね"),
    ("panda", "パンダ"),
    ("frog", "かえる"),
    ("penguin", "ペンギン"),
    ("koala", "コアラ"),
    ("owl", "ふくろう"),
    ("shiba", "しばいぬ"),
)

BACKGROUNDS: tuple[tuple[str, str, str], ...] = (
    ("#8067ff", "#c9bbff", "#fff2b8"),
    ("#ff6f91", "#ffc2d2", "#bdf3df"),
    ("#36b7df", "#bcecff", "#ffe28a"),
    ("#f38b4b", "#ffd0aa", "#c7f3a8"),
    ("#5dc49c", "#bdeedb", "#ffd47b"),
    ("#9b70dc", "#ddc9ff", "#ffbfa8"),
)


ANIMAL_ART: dict[str, str] = {
    "rabbit": '''
      <g stroke="#553c48" stroke-width="3" stroke-linejoin="round">
        <ellipse cx="58" cy="52" rx="15" ry="34" fill="#fff8ed" transform="rotate(-10 58 52)"/>
        <ellipse cx="102" cy="52" rx="15" ry="34" fill="#fff8ed" transform="rotate(10 102 52)"/>
        <ellipse cx="58" cy="51" rx="6" ry="23" fill="#ffb8c8" stroke="none" transform="rotate(-10 58 51)"/>
        <ellipse cx="102" cy="51" rx="6" ry="23" fill="#ffb8c8" stroke="none" transform="rotate(10 102 51)"/>
        <ellipse cx="80" cy="93" rx="45" ry="38" fill="#fff8ed"/>
        <circle cx="61" cy="88" r="5" fill="#553c48" stroke="none"/><circle cx="99" cy="88" r="5" fill="#553c48" stroke="none"/>
        <circle cx="59" cy="86" r="1.6" fill="#fff" stroke="none"/><circle cx="97" cy="86" r="1.6" fill="#fff" stroke="none"/>
        <ellipse cx="80" cy="102" rx="7" ry="5" fill="#ef7896" stroke="none"/>
        <path d="M80 107v5m0 0c-5 0-8-2-9-5m9 5c5 0 8-2 9-5" fill="none" stroke-linecap="round"/>
        <circle cx="51" cy="103" r="6" fill="#ffc5cf" stroke="none"/><circle cx="109" cy="103" r="6" fill="#ffc5cf" stroke="none"/>
      </g>''',
    "cat": '''
      <g stroke="#563e45" stroke-width="3" stroke-linejoin="round">
        <path d="M39 73 45 38l27 20h16l27-20 6 35" fill="#f3a45f"/>
        <path d="m47 48 4 20 15-10zM113 48l-4 20-15-10z" fill="#ffced0" stroke="none"/>
        <rect x="36" y="55" width="88" height="72" rx="38" fill="#f3a45f"/>
        <path d="M80 56v17M63 59l-6 13M97 59l6 13" fill="none" stroke="#b75f43" stroke-linecap="round"/>
        <path d="M53 88q8 7 16 0M91 88q8 7 16 0" fill="none" stroke-linecap="round"/>
        <path d="m75 99 5 4 5-4z" fill="#d65e74" stroke="none"/>
        <path d="M80 103v5m0 0q-6 6-12 0m12 0q6 6 12 0" fill="none" stroke-linecap="round"/>
        <path d="M62 101H43m19 7-20 4m56-11h19m-19 7 20 4" fill="none" stroke-width="2" stroke-linecap="round"/>
      </g>''',
    "bear": '''
      <g stroke="#493c3a" stroke-width="3" stroke-linejoin="round">
        <circle cx="46" cy="61" r="22" fill="#a66f4f"/><circle cx="114" cy="61" r="22" fill="#a66f4f"/>
        <circle cx="46" cy="61" r="11" fill="#e5af87" stroke="none"/><circle cx="114" cy="61" r="11" fill="#e5af87" stroke="none"/>
        <circle cx="80" cy="87" r="47" fill="#b97b55"/>
        <circle cx="62" cy="83" r="5" fill="#493c3a" stroke="none"/><circle cx="98" cy="83" r="5" fill="#493c3a" stroke="none"/>
        <circle cx="60" cy="81" r="1.5" fill="#fff" stroke="none"/><circle cx="96" cy="81" r="1.5" fill="#fff" stroke="none"/>
        <ellipse cx="80" cy="103" rx="22" ry="17" fill="#efd1ad" stroke="none"/>
        <ellipse cx="80" cy="98" rx="8" ry="6" fill="#493c3a" stroke="none"/>
        <path d="M80 104v5m0 0q-7 6-13 0m13 0q7 6 13 0" fill="none" stroke-linecap="round"/>
      </g>''',
    "fox": '''
      <g stroke="#563b3b" stroke-width="3" stroke-linejoin="round">
        <path d="m37 73 8-38 30 23h10l30-23 8 38" fill="#ed7c43"/>
        <path d="m47 47 4 22 17-12zM113 47l-4 22-17-12z" fill="#573b43" stroke="none"/>
        <path d="M80 50c29 0 45 16 43 44-2 24-20 35-43 35S39 118 37 94c-2-28 14-44 43-44Z" fill="#ed7c43"/>
        <path d="M80 119C60 130 41 112 40 91c16 0 29 8 40 28Zm0 0c20 11 39-7 40-28-16 0-29 8-40 28Z" fill="#fff4df" stroke="none"/>
        <circle cx="61" cy="87" r="5" fill="#563b3b" stroke="none"/><circle cx="99" cy="87" r="5" fill="#563b3b" stroke="none"/>
        <path d="m73 103 7 6 7-6z" fill="#563b3b" stroke="none"/>
      </g>''',
    "panda": '''
      <g stroke="#34323b" stroke-width="3" stroke-linejoin="round">
        <circle cx="45" cy="60" r="22" fill="#34323b"/><circle cx="115" cy="60" r="22" fill="#34323b"/>
        <ellipse cx="80" cy="88" rx="47" ry="43" fill="#fffaf0"/>
        <ellipse cx="60" cy="84" rx="14" ry="18" fill="#34323b" transform="rotate(25 60 84)" stroke="none"/>
        <ellipse cx="100" cy="84" rx="14" ry="18" fill="#34323b" transform="rotate(-25 100 84)" stroke="none"/>
        <circle cx="62" cy="83" r="4" fill="#fff" stroke="none"/><circle cx="98" cy="83" r="4" fill="#fff" stroke="none"/>
        <ellipse cx="80" cy="103" rx="9" ry="7" fill="#34323b" stroke="none"/>
        <path d="M80 109v4m0 0q-7 5-13 0m13 0q7 5 13 0" fill="none" stroke-linecap="round"/>
        <circle cx="49" cy="104" r="6" fill="#ffb8c3" stroke="none"/><circle cx="111" cy="104" r="6" fill="#ffb8c3" stroke="none"/>
      </g>''',
    "frog": '''
      <g stroke="#355344" stroke-width="3" stroke-linejoin="round">
        <circle cx="53" cy="61" r="23" fill="#72ce74"/><circle cx="107" cy="61" r="23" fill="#72ce74"/>
        <circle cx="53" cy="59" r="10" fill="#fff" stroke="none"/><circle cx="107" cy="59" r="10" fill="#fff" stroke="none"/>
        <circle cx="55" cy="60" r="5" fill="#355344" stroke="none"/><circle cx="105" cy="60" r="5" fill="#355344" stroke="none"/>
        <rect x="35" y="60" width="90" height="67" rx="34" fill="#72ce74"/>
        <circle cx="53" cy="91" r="6" fill="#ef879e" stroke="none"/><circle cx="107" cy="91" r="6" fill="#ef879e" stroke="none"/>
        <path d="M55 101q25 22 50 0" fill="none" stroke-linecap="round"/>
        <path d="M70 108q10 8 20 0" fill="#ef7896" stroke="#ef7896" stroke-linecap="round"/>
      </g>''',
    "penguin": '''
      <g stroke="#303544" stroke-width="3" stroke-linejoin="round">
        <ellipse cx="80" cy="85" rx="43" ry="53" fill="#303544"/>
        <ellipse cx="80" cy="91" rx="32" ry="38" fill="#fff9e9" stroke="none"/>
        <path d="M48 70q7-28 32-13 25-15 32 13-16-2-32 14-16-16-32-14Z" fill="#fff9e9" stroke="none"/>
        <circle cx="65" cy="72" r="5" fill="#303544" stroke="none"/><circle cx="95" cy="72" r="5" fill="#303544" stroke="none"/>
        <circle cx="63" cy="70" r="1.5" fill="#fff" stroke="none"/><circle cx="93" cy="70" r="1.5" fill="#fff" stroke="none"/>
        <path d="m70 84 10 8 10-8-10-6z" fill="#f2a542" stroke="none"/>
        <path d="M44 87 28 101l18 5M116 87l16 14-18 5" fill="#303544" stroke-linecap="round"/>
        <path d="m61 132-13 8h22m29-8 13 8H90" fill="#f2a542" stroke-linecap="round"/>
      </g>''',
    "koala": '''
      <g stroke="#434552" stroke-width="3" stroke-linejoin="round">
        <circle cx="43" cy="69" r="25" fill="#87909c"/><circle cx="117" cy="69" r="25" fill="#87909c"/>
        <circle cx="43" cy="69" r="14" fill="#c8ced2" stroke="none"/><circle cx="117" cy="69" r="14" fill="#c8ced2" stroke="none"/>
        <ellipse cx="80" cy="88" rx="44" ry="42" fill="#a9b0b7"/>
        <path d="M55 83q8 7 16 0M89 83q8 7 16 0" fill="none" stroke-linecap="round"/>
        <ellipse cx="80" cy="99" rx="13" ry="17" fill="#434552" stroke="none"/>
        <circle cx="76" cy="94" r="3" fill="#fff" opacity=".65" stroke="none"/>
        <path d="M80 115q-7 6-13 1m13-1q7 6 13 1" fill="none" stroke-linecap="round"/>
        <circle cx="51" cy="101" r="6" fill="#ef9faa" opacity=".8" stroke="none"/><circle cx="109" cy="101" r="6" fill="#ef9faa" opacity=".8" stroke="none"/>
      </g>''',
    "owl": '''
      <g stroke="#493d49" stroke-width="3" stroke-linejoin="round">
        <path d="M42 67 45 38l22 15q13-7 26 0l22-15 3 29c10 17 7 45-8 60H50c-15-15-18-43-8-60Z" fill="#a98469"/>
        <circle cx="61" cy="80" r="22" fill="#f4dba8"/><circle cx="99" cy="80" r="22" fill="#f4dba8"/>
        <circle cx="61" cy="80" r="10" fill="#493d49" stroke="none"/><circle cx="99" cy="80" r="10" fill="#493d49" stroke="none"/>
        <circle cx="58" cy="77" r="3" fill="#fff" stroke="none"/><circle cx="96" cy="77" r="3" fill="#fff" stroke="none"/>
        <path d="m71 95 9 9 9-9-9-5z" fill="#ed9e45" stroke="none"/>
        <path d="M55 116h50M63 124h34" fill="none" stroke="#80604f" stroke-linecap="round"/>
      </g>''',
    "shiba": '''
      <g stroke="#563e3c" stroke-width="3" stroke-linejoin="round">
        <path d="m39 72 8-37 28 24h10l28-24 8 37" fill="#d98b4d"/>
        <path d="m48 47 4 21 15-10zM112 47l-4 21-15-10z" fill="#f3bd91" stroke="none"/>
        <path d="M80 50c27 0 43 16 43 42 0 25-18 39-43 39S37 117 37 92c0-26 16-42 43-42Z" fill="#d98b4d"/>
        <path d="M43 91c13-3 25 3 37 22 12-19 24-25 37-22-3 24-18 35-37 35S46 115 43 91Z" fill="#fff1dc" stroke="none"/>
        <path d="M53 85q8 7 16 0M91 85q8 7 16 0" fill="none" stroke-linecap="round"/>
        <path d="m72 101 8 6 8-6z" fill="#563e3c" stroke="none"/>
        <path d="M80 107v4m0 0q-7 7-14 0m14 0q7 7 14 0" fill="none" stroke-linecap="round"/>
        <circle cx="49" cy="103" r="6" fill="#ef9a9f" stroke="none"/><circle cx="111" cy="103" r="6" fill="#ef9a9f" stroke="none"/>
      </g>''',
}


def animal_kind(user_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(user_id.encode()).digest()
    return ANIMALS[digest[0] % len(ANIMALS)]


def render_cute_animal_svg(user_id: str) -> str:
    digest = hashlib.sha256(user_id.encode()).digest()
    kind, label = ANIMALS[digest[0] % len(ANIMALS)]
    base, soft, accent = BACKGROUNDS[digest[1] % len(BACKGROUNDS)]
    resource_id = digest.hex()[:10]
    tilt = (digest[2] % 9) - 4
    spot_x = 20 + digest[3] % 18
    spot_y = 22 + digest[4] % 22
    art = ANIMAL_ART[kind]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" role="img" aria-labelledby="title" data-animal="{kind}">
  <title id="title">マジョリティの{label}プレイヤーアイコン</title>
  <defs>
    <linearGradient id="background-{resource_id}" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{soft}"/><stop offset="1" stop-color="{base}"/></linearGradient>
    <filter id="shadow-{resource_id}" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="4" stdDeviation="3" flood-color="#30283f" flood-opacity=".22"/></filter>
    <clipPath id="card-{resource_id}"><rect width="160" height="160" rx="36"/></clipPath>
  </defs>
  <g clip-path="url(#card-{resource_id})">
    <rect width="160" height="160" rx="36" fill="url(#background-{resource_id})"/>
    <circle cx="{spot_x}" cy="{spot_y}" r="28" fill="#fff" opacity=".2"/>
    <circle cx="145" cy="137" r="34" fill="{accent}" opacity=".34"/>
    <path d="M19 115l4 8 9 1-7 6 2 9-8-5-8 5 2-9-7-6 9-1zM128 18l3 6 7 1-5 5 1 7-6-4-6 4 1-7-5-5 7-1z" fill="#fff" opacity=".72"/>
    <circle cx="80" cy="85" r="61" fill="#fff9ed" opacity=".82" filter="url(#shadow-{resource_id})"/>
    <g transform="rotate({tilt} 80 84)">{art}</g>
  </g>
</svg>'''
