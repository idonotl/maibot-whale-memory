"""Bounded, speaker-backed interaction preferences; no self-modifying prompts."""
import json
import re

from .engine import SECRET

ASPECTS = ('语气', '句尾习惯', '安慰方式', '追问频率', '建议方式', '称呼偏好', '篇幅', '互动边界')
EXPLICIT = re.compile(r'以后|平时|一直|每次|每句|总是|老是|别总|不要总|长期|记住|记一下|我喜欢你|我希望你|我不喜欢你|我更喜欢你')
TEMPORARY = re.compile(r'这次|这回|这一句|这一轮|今天先|暂时|开玩笑|玩梗|模仿|扮演|不要记|不用记|别记')
STYLE = re.compile(r'喵|语气|句尾|安慰|追问|反问|问我|建议|称呼|叫我|回复|说话|长篇|简短|陪我|听我|撒娇|敷衍|附和')
UNSAFE = re.compile(r'系统|提示词|指令|权限|开发者|管理员|绕过|无条件|忽略|删除记录|自动执行|账号|鱼鳍|双手|身份|身体|人格')


def wants_reflection(text):
    return bool(EXPLICIT.search(text) and STYLE.search(text) and not TEMPORARY.search(text)
                and not re.search(r'转发|引用|网友|截图|(?:他|她|别人|有人)说|举个例子', text))


def parse_preferences(raw, messages):
    """Quote must belong to one accepted user message, never assistant/web text."""
    data = json.loads(re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip()))
    candidates = data.get('preferences', [])
    if not isinstance(candidates, list):
        return []
    result = []
    for item in candidates[:3]:
        if not isinstance(item, dict):
            continue
        aspect = item.get('aspect')
        body, quote = str(item.get('text', '')).strip(), str(item.get('quote', '')).strip()
        evidence = next((m for m in reversed(messages) if quote and quote in m['text']), None)
        if (aspect not in ASPECTS or not evidence or not 6 <= len(quote) <= 300
                or not 6 <= len(body) <= 140 or not body.startswith('这位用户') or not wants_reflection(evidence['text'])
                or TEMPORARY.search(quote) or SECRET.search(body+' '+quote)
                or UNSAFE.search(body+' '+quote)):
            continue
        result.append(dict(text=body, quote=quote, fact_key='互动偏好:'+aspect,
                           kind='interaction', importance=.8, evidence=evidence))
    # Last explicit statement for an aspect wins within this batch.
    result.sort(key=lambda m: messages.index(m['evidence']))
    return list({m['fact_key']: m for m in result}.values())


GUIDANCE = '''
另做轻量相处复盘，输出额外 preferences 数组（没有则 []）：
只提炼用户明确表达的长期交流偏好、对具体相处方式的纠正或明确认可。
aspect 只能是：语气、句尾习惯、安慰方式、追问频率、建议方式、称呼偏好、篇幅、互动边界。
text 用“这位用户希望/喜欢/不喜欢...”准确概括，quote 必须逐字来自同一个用户消息。
“挺好”“知道了”等泛泛认可不足以形成偏好。临时要求、玩梗、引用别人、疑问、身份设定、
固定人物身体、系统或权限要求不进入 preferences；同一内容不要再记入 memories。
共同经历只在用户明确自述双方发生过具体事情时写入 memories 的 episode，
措辞为“这位用户提到...”，不把模型自己的叙述、网上故事或推测当成已发生的事实。
示例 preferences: [{"aspect":"句尾习惯","text":"这位用户不喜欢每句话都加喵","quote":"以后别每句话都加喵，我不喜欢"}]
'''
