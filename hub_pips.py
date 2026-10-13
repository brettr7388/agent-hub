"""Deterministic Pip styles, assigned at creation or startup migration only."""
import re

PALETTES = ('blue', 'violet', 'teal', 'charcoal', 'coral', 'orange', 'yellow', 'lime', 'mint', 'sky', 'indigo', 'magenta', 'red', 'brown')
EYES = ('dots', 'happy', 'wide', 'sleepy', 'sparkle')
ANTENNAS = ('dot', 'star', 'bolt', 'heart')
VISORS = ('round', 'squircle')
ROLE_RULES = (
    (r'cod(e|er|ing)|develop|program|software|engineer|javascript|python', 'code'),
    (r'research|search|investigat|analys|detect|find', 'magnifier'),
    (r'audio|podcast|listen|sound|transcrib', 'headphones'),
    (r'writ|edit|author|copy|content|script', 'pencil'),
    (r'ops|operat|build|deploy|infrastructure|construct', 'hard_hat'),
    (r'inbox|email|mail|reply|messag', 'envelope'),
    (r'schedul|calendar|plan|appointment', 'calendar'),
    (r'chart|metric|data|statistic|report|analytics', 'chart'),
    (r'design|paint|illustrat|\bart\b|creative', 'paintbrush'),
    (r'chef|cook|recipe|food|kitchen', 'chef_hat'),
    (r'teach|learn|tutor|school|educat', 'graduation_cap'),
    (r'repair|fix|maintain|mechanic|tool', 'wrench'),
    (r'secur|guard|protect|audit|privacy', 'shield'),
    (r'travel|world|global|language|translat', 'globe'),
    (r'photo|camera|video|film|clip', 'camera'),
    (r'music|song|melody|compos', 'music_note'),
    (r'financ|money|budget|account|sales|revenue', 'dollar_coin'),
    (r'health|care|wellness|therapy|medic', 'heart'),
    (r'book|read|document|librar', 'book'),
    (r'idea|brainstorm|invent|strateg', 'lightbulb'),
    (r'launch|startup|rocket|growth', 'rocket'),
    (r'garden|plant|nature|environment|sustainab', 'leaf'),
    (r'game|play|gaming', 'gamepad'),
    (r'market|promot|advertis|announce|outreach', 'megaphone'))


def style_for(agent, existing=()):
    seed = 2166136261
    for char in str(agent.get('id', '')):
        seed = ((seed ^ ord(char)) * 16777619) & 0xffffffff
    text = ' '.join(str(agent.get(k, '')) for k in ('name', 'title', 'role', 'instructions')).lower()
    accessory = next((a for pattern, a in ROLE_RULES if re.search(pattern, text)), ('none', 'scarf', 'bow', 'glasses', 'cap')[seed % 5])
    if agent.get('guide') or agent.get('name', '').lower() == 'guide':
        return dict(palette='blue', accessory='compass', eyes='dots', antenna='dot', visor='round')
    base = dict(palette=PALETTES[seed % 14], accessory=accessory, eyes=EYES[(seed >> 4) % 5], antenna=ANTENNAS[(seed >> 8) % 4], visor=VISORS[(seed >> 12) % 2])
    used = list(existing)
    best, count = base, used.count(base)
    for n in range(1, 560):
        if not count: break
        k = (seed % 560 + n * 13) % 560
        candidate = dict(palette=PALETTES[k % 14], accessory=accessory, eyes=EYES[(k // 14) % 5], antenna=ANTENNAS[(k // 70) % 4], visor=VISORS[(k // 280) % 2])
        amount = used.count(candidate)
        if amount < count: best, count = candidate, amount
    return best
