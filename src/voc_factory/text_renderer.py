from __future__ import annotations

import json
import random
import re
from functools import lru_cache
from pathlib import Path

from .source import Scenario


PROTECTED_TERMS = (
    "안 ",
    "못 ",
    "없",
    "아니",
    "연기",
    "화재",
    "부풀",
    "감전",
    "화상",
)

KO_TYPOS = (
    ("습니다", "슴니다"),
    ("됐", "됬"),
    ("며칠", "몇일"),
    ("계속", "게속"),
    ("문제", "문재"),
)

EN_TYPOS = (
    ("happened", "hapened"),
    ("connection", "conection"),
    ("battery", "batery"),
    ("problem", "probelm"),
)

KO_CONNECTORS = (" 그리고 ", " 또 ", " 게다가 ")
EN_CONNECTORS = (" Also, ", " In addition, ", " Another issue is that ")

KO_ENDINGS = (
    "",
    " 원인이 무엇인지 궁금합니다.",
    " 어떻게 해결해야 하나요?",
    " 확인 부탁드립니다.",
    " 점검이 필요한지 알고 싶습니다.",
    " 같은 증상이 계속되어 불편합니다.",
)

EN_ENDINGS = (
    "",
    " What could be causing this?",
    " How can I fix it?",
    " Please check whether it needs service.",
    " It keeps disrupting normal use.",
)

KO_INQUIRY_ENDINGS = (
    "",
    " 안내 부탁드립니다.",
    " 확인할 수 있는 방법이 궁금합니다.",
    " 자세한 설명 부탁드립니다.",
    " 어떻게 설정하면 될까요?",
)

EN_INQUIRY_ENDINGS = (
    "",
    " Please explain how this works.",
    " Where can I find the relevant setting?",
    " I would like to confirm whether this is supported.",
    " Please let me know the correct steps.",
)

KO_OPINION_ENDINGS = (
    "",
    " 이 부분은 개선되면 좋겠습니다.",
    " 실제 사용에서 아쉬움이 큽니다.",
    " 다음 제품에서는 보완되길 바랍니다.",
)

EN_OPINION_ENDINGS = (
    "",
    " I hope this can be improved.",
    " This remains disappointing in actual use.",
    " I would like to see this addressed in a future product.",
)

KO_PRAISE_ENDINGS = ("", " 전반적으로 만족합니다.", " 계속 잘 사용하고 있습니다.")
EN_PRAISE_ENDINGS = ("", " Overall, I am satisfied.", " It has worked well for me.")

CALL_CENTER_TAILS = (
    "상담원: 증상 확인을 위해 몇 가지 안내드리겠습니다.",
    "상담원: 확인 후 필요한 조치를 안내드리겠습니다.",
    "상담원: 말씀하신 내용을 접수하겠습니다.",
)

SAFETY_FLAGS = {
    "BATTERY_SWELL",
    "SMOKE_FIRE",
    "BURN_INJURY",
    "ELECTRIC_SHOCK",
    "DAMAGE_PROGRESSION",
}

KO_TIMES = (
    "오늘",
    "어제부터",
    "지난 이틀 동안",
    "지난 며칠 동안",
    "지난 일주일 동안",
    "지난 보름 동안",
    "지난 한 달 동안",
    "요 며칠",
)

KO_FREQUENCIES = (
    "한 차례",
    "두세 차례",
    "서너 차례",
    "가끔",
    "간헐적으로",
    "자주",
    "거의 매번",
    "사용할 때마다",
)

EN_TIMES = (
    "Today",
    "Since yesterday",
    "Over the past two days",
    "Over the past few days",
    "Over the past week",
    "Over the past two weeks",
    "Over the past month",
    "Recently",
)

EN_FREQUENCIES = (
    "once",
    "two or three times",
    "several times",
    "occasionally",
    "intermittently",
    "frequently",
    "almost every time",
    "whenever I use it",
)

KO_HISTORY_TEMPLATES = (
    "{time} 같은 문제가 {frequency} 생깁니다.",
    "{time} 이 증상이 {frequency} 반복됐습니다.",
    "{time} 동일한 현상을 {frequency} 확인했습니다.",
    "{time} 이 문제를 {frequency} 겪었습니다.",
    "{time} 증상이 {frequency} 재현됐습니다.",
    "{time} 같은 현상이 {frequency} 다시 발생했습니다.",
    "{time} 이 현상이 {frequency} 발생했습니다.",
    "{time} 증상이 {frequency} 이어졌습니다.",
    "{time} 동일 현상이 {frequency} 나타났습니다.",
    "{time} 이 문제를 {frequency} 경험했습니다.",
    "{time} 증상은 {frequency} 확인됐습니다.",
    "{time} 이 문제가 {frequency} 생겨 사용하기 불편했습니다.",
    "{time} 같은 현상을 {frequency} 겪고 있습니다.",
    "{time} 증상이 {frequency} 나타납니다.",
    "{time} 이 문제가 {frequency} 되풀이됐습니다.",
    "{time} 동일한 증상이 {frequency} 발생했습니다.",
)

EN_HISTORY_TEMPLATES = (
    "{time}, the same problem occurred {frequency}.",
    "{time}, this happened {frequency}.",
    "{time}, I saw the issue {frequency}.",
    "{time}, I experienced it {frequency}.",
    "{time}, the symptom recurred {frequency}.",
    "{time}, the same behavior appeared {frequency}.",
    "{time}, it occurred {frequency}.",
    "{time}, the symptom continued {frequency}.",
    "{time}, I noticed the same behavior {frequency}.",
    "{time}, the issue showed up {frequency}.",
    "{time}, I encountered the problem {frequency}.",
    "{time}, this affected normal use {frequency}.",
    "{time}, the behavior returned {frequency}.",
    "{time}, the symptom was visible {frequency}.",
    "{time}, the same issue repeated {frequency}.",
    "{time}, I observed the same symptom {frequency}.",
)

KO_SAFETY_TEMPLATES = (
    "제품은 {age} 정도 사용했으며 위험 증상은 {time} 처음 확인해 바로 사용을 중단했습니다.",
    "{age}가량 사용한 제품에서 {time} 증상을 발견한 뒤 전원을 껐습니다.",
    "사용 기간은 {age} 정도이며 {time} 이상을 확인해 더 이상 사용하지 않고 있습니다.",
    "{age} 정도 쓴 제품에서 {time} 위험 징후가 보여 즉시 사용을 멈췄습니다.",
)

EN_SAFETY_TEMPLATES = (
    "I had used it for about {age} when I noticed the safety issue {time} and stopped using it.",
    "After roughly {age} of use, I saw the warning sign {time} and powered the device off.",
    "The device had been used for {age}; I noticed the hazard {time} and have not used it since.",
    "I found the safety problem {time} after about {age} of use and stopped using the device.",
)

KO_AGES = ("일주일", "보름", "한 달", "두 달", "세 달", "반년", "1년", "2년")
EN_AGES = ("a week", "two weeks", "one month", "two months", "three months", "six months", "a year", "two years")
KO_SAFETY_TIMES = ("오늘", "어제", "이틀 전", "며칠 전", "일주일 전", "보름 전", "한 달 전", "최근")
EN_SAFETY_TIMES = ("today", "yesterday", "two days ago", "a few days ago", "a week ago", "two weeks ago", "a month ago", "recently")

KO_INQUIRY_FOCUS = (
    "기능 동작 방식",
    "지원 범위",
    "설정 방법",
    "필요 조건",
    "사용 절차",
    "제한 사항",
    "권장 설정",
    "공식 안내",
)
EN_INQUIRY_FOCUS = (
    "how the feature works",
    "what is supported",
    "how to configure it",
    "the requirements",
    "the usage steps",
    "the limitations",
    "the recommended settings",
    "the official guidance",
)
KO_INQUIRY_TEMPLATES = (
    "{age} 정도 사용하면서 {focus} 관련 내용을 확인하고 싶었습니다.",
    "사용한 지 {age}쯤 되어 {focus} 관련 안내가 필요합니다.",
    "{age}가량 사용했지만 아직 {focus} 관련 내용을 정확히 모르겠습니다.",
    "제품을 {age} 정도 쓴 상태에서 {focus} 관련 내용이 궁금합니다.",
    "{focus} 관련 내용을 알아보는 중이며 사용 기간은 {age} 정도입니다.",
    "{age} 정도 사용한 사용자 입장에서 {focus} 관련 내용을 알고 싶습니다.",
    "사용 기간은 약 {age}이며 {focus} 관련 내용을 확인하려고 합니다.",
    "{age}쯤 쓴 뒤 {focus} 관련 추가 설명이 필요해졌습니다.",
    "{focus} 관련 내용을 확인하고 싶어 남기며 제품은 {age} 정도 사용했습니다.",
    "제품을 약 {age} 사용했고 현재 {focus} 관련 내용을 알아보고 있습니다.",
    "{age} 정도 사용한 뒤에도 {focus} 관련 내용이 명확하지 않았습니다.",
    "사용한 기간은 {age}쯤이고 문의하려는 주제는 {focus}입니다.",
    "{focus} 관련 내용이 궁금한데 제품은 현재 {age} 정도 사용했습니다.",
    "{age} 동안 사용하며 {focus} 관련 정보가 필요했습니다.",
    "제품 사용 기간은 {age}이며 {focus} 관련 안내를 받고 싶습니다.",
    "{age} 정도 써 본 상태에서 {focus} 관련 내용을 확인하고자 합니다.",
)
EN_INQUIRY_TEMPLATES = (
    "After about {age} of use, I would like clarification on {focus}.",
    "I have used it for roughly {age} and need guidance on {focus}.",
    "Even after {age} of use, I am still unsure about {focus}.",
    "The device has been in use for {age}, and I want to understand {focus}.",
    "I am checking {focus} after using the product for about {age}.",
    "As a user of roughly {age}, I would like to know {focus}.",
    "I have had the product for {age} and am trying to confirm {focus}.",
    "After using it for {age}, I need more information about {focus}.",
    "My question is about {focus}; I have used the device for {age}.",
    "I have used the product for around {age} and am looking into {focus}.",
    "After {age} of use, the information on {focus} is still unclear to me.",
    "I have been using it for {age}, and my question concerns {focus}.",
    "I want to confirm {focus} after about {age} with the product.",
    "Over {age} of use, I have needed clearer information on {focus}.",
    "The product has been used for {age}, and I need guidance on {focus}.",
    "Having used it for {age}, I would like to verify {focus}.",
)

KO_OPINION_FOCUS = (
    "처음부터",
    "쓸수록",
    "실사용에서",
    "장시간 사용할수록",
    "특정 상황에서",
    "다른 제품과 비교할 때",
    "일상적으로 사용할 때",
    "전체적인 경험에서",
)
EN_OPINION_FOCUS = (
    "from the beginning",
    "more over time",
    "in actual use",
    "during longer use",
    "in certain situations",
    "compared with other products",
    "in everyday use",
    "in the overall experience",
)
KO_OPINION_TEMPLATES = (
    "약 {age} 사용해 보니 {focus} 이 점이 체감됩니다.",
    "사용 기간은 {age} 정도이며 {focus} 느낀 의견입니다.",
    "{age}가량 경험한 결과 {focus} 이 부분이 눈에 띕니다.",
    "제품을 {age} 정도 써 보면서 {focus} 이런 인상을 받았습니다.",
    "{focus} 느낀 점이며 지금까지 약 {age} 사용했습니다.",
    "{age} 동안 사용한 사용자로서 {focus} 이 부분을 평가했습니다.",
    "약 {age}의 사용 경험에서 {focus} 이 점이 두드러졌습니다.",
    "사용한 지 {age} 정도 됐고 {focus} 같은 생각이 듭니다.",
    "{focus} 체감한 내용이며 사용 기간은 약 {age}입니다.",
    "{age} 정도 직접 사용해 본 뒤 {focus} 남기는 의견입니다.",
    "제품을 약 {age} 경험하면서 {focus} 이 부분을 느꼈습니다.",
    "{age}쯤 사용한 시점에서 {focus} 평가한 내용입니다.",
    "{focus} 보이는 특징이며 지금까지 {age} 정도 사용했습니다.",
    "사용 경험은 약 {age}이고 {focus} 이 점이 인상적입니다.",
    "{age} 동안 써 본 결과 {focus} 이런 차이가 느껴집니다.",
    "제품을 {age} 정도 사용한 뒤 {focus} 이 부분이 남았습니다.",
)
EN_OPINION_TEMPLATES = (
    "After about {age} of use, this stands out {focus}.",
    "I have used it for {age}, and this is how it feels {focus}.",
    "Based on roughly {age} of experience, this is noticeable {focus}.",
    "Over {age} of use, I have had this impression {focus}.",
    "This is what I noticed {focus} after using it for {age}.",
    "After {age} of use, this is how I would assess it {focus}.",
    "Across about {age} of use, this point stood out {focus}.",
    "I have had it for {age}, and this is my impression {focus}.",
    "This reflects what I experienced {focus} over about {age}.",
    "After using it directly for {age}, this is my view {focus}.",
    "During roughly {age} with the product, I noticed this {focus}.",
    "At around {age} of use, this is how I would rate it {focus}.",
    "This characteristic is noticeable {focus} after about {age}.",
    "My experience spans {age}, and this point is clear {focus}.",
    "After {age} of use, the difference is apparent {focus}.",
    "Having used the product for {age}, this is what remains {focus}.",
)

KO_SERVICE_FOCUS = (
    "주문 과정",
    "안내 과정",
    "처리 과정",
    "실제 이용",
    "진행 상황 확인",
    "고객 대응",
    "결과 대기",
    "전체 절차",
)
EN_SERVICE_FOCUS = (
    "the order process",
    "the guidance process",
    "the handling process",
    "actual use of the service",
    "status checks",
    "customer support",
    "the wait for the outcome",
    "the overall process",
)
KO_SERVICE_OPINION_TEMPLATES = (
    "{time} {focus}에서 이 점이 불편했습니다.",
    "{time} 관련 서비스를 이용하며 {focus}에서 이 부분이 눈에 띄었습니다.",
    "{time} 서비스 경험 중 {focus}에서 이런 인상을 받았습니다.",
    "{time} {focus}에서 이 문제를 체감했습니다.",
    "{time} 해당 절차를 겪으면서 {focus}에 아쉬움이 남았습니다.",
    "{time} 서비스 이용 중 {focus}에서 이 점을 확인했습니다.",
    "{time} 관련 업무를 진행하며 {focus}에서 불편을 느꼈습니다.",
    "{time} 서비스 처리 중 {focus}에서 이 부분이 두드러졌습니다.",
    "{time} 경험을 돌아보면 {focus} 부분이 가장 아쉽습니다.",
    "{time} 관련 과정을 거치며 {focus}에 이런 문제가 있었습니다.",
    "{time} 서비스 요청을 진행하면서 {focus}에서 이 점을 느꼈습니다.",
    "{time} 처리 결과를 확인하며 {focus}에 아쉬움이 컸습니다.",
    "{time} 해당 서비스를 경험했고 {focus} 과정에 대한 인상이 남았습니다.",
    "{time} 관련 절차 중 {focus}에 개선이 필요하다고 느꼈습니다.",
    "{time} 서비스를 이용하며 {focus}에 대한 평가를 남깁니다.",
    "{time} 이용 경험에서는 {focus} 부분이 인상적이었습니다.",
)
EN_SERVICE_OPINION_TEMPLATES = (
    "{time}, this was inconvenient during {focus}.",
    "{time}, this point stood out during {focus}.",
    "{time}, the service left this impression during {focus}.",
    "{time}, I noticed the problem during {focus}.",
    "{time}, this remained disappointing during {focus}.",
    "{time}, I observed this issue during {focus}.",
    "{time}, I experienced this inconvenience during {focus}.",
    "{time}, this part of the service stood out during {focus}.",
    "{time}, this was the most disappointing point in {focus}.",
    "{time}, there was a problem with {focus}.",
    "{time}, I noticed this while going through {focus}.",
    "{time}, I was disappointed with {focus}.",
    "{time}, this remained after {focus}.",
    "{time}, I felt {focus} needed improvement.",
    "{time}, this is my assessment of {focus}.",
    "{time}, this point was memorable in {focus}.",
)

INQUIRY_INTENTS = {"HOW_TO", "FEATURE_REQUEST"}
INQUIRY_SYMPTOMS = {"INFORMATION_REQUEST", "FEATURE_MISSING", "DIFFICULT_TO_USE"}
OPINION_INTENTS = {
    "PURCHASE_COMPLAINT",
    "USABILITY_COMPLAINT",
    "COMPARISON",
    "SERVICE_COMPLAINT",
    "WARRANTY_DISPUTE",
    "PRAISE",
}


@lru_cache(maxsize=8)
def load_phrase_bank(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    phrases = value.get("phrases")
    if not isinstance(phrases, dict) or not phrases:
        raise ValueError("phrase bank에 phrases 객체가 없습니다.")
    return value


def _surface_candidates(
    scenario: Scenario,
    profile_id: str,
    phrase_bank: dict,
) -> list[str]:
    entry = phrase_bank["phrases"].get(scenario.scenario_id)
    if not entry:
        raise ValueError(f"phrase bank에 {scenario.scenario_id}가 없습니다.")
    style = {
        "B0_BASE": "formal",
        "P1_PARAPHRASE": "casual",
        "A1_ABBREVIATED": "short",
        "N1_NOISY": "casual",
    }[profile_id]
    if scenario["target_channel"] == "EMAIL_COMPLAINT" and style == "short":
        style = "formal"
    candidates = entry.get(style)
    if not isinstance(candidates, list) or not candidates:
        raise ValueError(f"{scenario.scenario_id}의 {style} 표현이 없습니다.")
    return candidates


def _history(
    scenario: Scenario,
    occurrence: int,
    language: str,
    phrase_count: int,
) -> tuple[int, str]:
    offset = int(scenario.scenario_id.removeprefix("GVS-")) * 37
    if scenario["safety_flag"] in SAFETY_FLAGS:
        styles = EN_SAFETY_TEMPLATES if language == "EN" else KO_SAFETY_TEMPLATES
        ages = EN_AGES if language == "EN" else KO_AGES
        times = EN_SAFETY_TIMES if language == "EN" else KO_SAFETY_TIMES
        style = (occurrence + offset) % len(styles)
        local = occurrence // len(styles)
        capacity = phrase_count * len(ages) * len(times)
        value = (local * 127 + offset) % capacity
        phrase_index = value % phrase_count
        age = ages[(value // phrase_count) % len(ages)]
        time = times[(value // (phrase_count * len(ages))) % len(times)]
        return phrase_index, styles[style].format(age=age, time=time)

    if (
        (
            scenario["intent_type"] in INQUIRY_INTENTS
            and scenario["observed_symptom"] in INQUIRY_SYMPTOMS
        )
        or scenario["hard_negative"] == "TRUE"
    ):
        styles = EN_INQUIRY_TEMPLATES if language == "EN" else KO_INQUIRY_TEMPLATES
        ages = EN_AGES if language == "EN" else KO_AGES
        focuses = EN_INQUIRY_FOCUS if language == "EN" else KO_INQUIRY_FOCUS
        style = (occurrence + offset) % len(styles)
        local = occurrence // len(styles)
        capacity = phrase_count * len(ages) * len(focuses)
        value = (local * 127 + offset) % capacity
        phrase_index = value % phrase_count
        age = ages[(value // phrase_count) % len(ages)]
        focus = focuses[(value // (phrase_count * len(ages))) % len(focuses)]
        return phrase_index, styles[style].format(age=age, focus=focus)

    if scenario["intent_type"] in OPINION_INTENTS:
        if scenario["product_type"] in {"COMMERCE", "SERVICE"}:
            styles = (
                EN_SERVICE_OPINION_TEMPLATES
                if language == "EN"
                else KO_SERVICE_OPINION_TEMPLATES
            )
            times = EN_TIMES if language == "EN" else KO_TIMES
            focuses = EN_SERVICE_FOCUS if language == "EN" else KO_SERVICE_FOCUS
            style = (occurrence + offset) % len(styles)
            local = occurrence // len(styles)
            capacity = phrase_count * len(times) * len(focuses)
            value = (local * 127 + offset) % capacity
            phrase_index = value % phrase_count
            time = times[(value // phrase_count) % len(times)]
            focus = focuses[
                (value // (phrase_count * len(times))) % len(focuses)
            ]
            return phrase_index, styles[style].format(time=time, focus=focus)

        styles = EN_OPINION_TEMPLATES if language == "EN" else KO_OPINION_TEMPLATES
        ages = EN_AGES if language == "EN" else KO_AGES
        focuses = EN_OPINION_FOCUS if language == "EN" else KO_OPINION_FOCUS
        style = (occurrence + offset) % len(styles)
        local = occurrence // len(styles)
        capacity = phrase_count * len(ages) * len(focuses)
        value = (local * 127 + offset) % capacity
        phrase_index = value % phrase_count
        age = ages[(value // phrase_count) % len(ages)]
        focus = focuses[(value // (phrase_count * len(ages))) % len(focuses)]
        return phrase_index, styles[style].format(age=age, focus=focus)

    styles = EN_HISTORY_TEMPLATES if language == "EN" else KO_HISTORY_TEMPLATES
    times = EN_TIMES if language == "EN" else KO_TIMES
    frequencies = EN_FREQUENCIES if language == "EN" else KO_FREQUENCIES
    style = (occurrence + offset) % len(styles)
    local = occurrence // len(styles)
    capacity = phrase_count * len(times) * len(frequencies)
    value = (local * 127 + offset) % capacity
    phrase_index = value % phrase_count
    time = times[(value // phrase_count) % len(times)]
    frequency = frequencies[
        (value // (phrase_count * len(times))) % len(frequencies)
    ]
    return phrase_index, styles[style].format(time=time, frequency=frequency)


def _apply_noise(
    clean: str,
    rng: random.Random,
    language: str,
    safety_flag: str,
) -> tuple[str, list[str]]:
    if safety_flag in SAFETY_FLAGS or any(term in clean for term in PROTECTED_TERMS):
        return clean, []

    operations: list[str] = []
    replacements = EN_TYPOS if language == "EN" else KO_TYPOS
    candidates = [(old, new) for old, new in replacements if old in clean]

    if candidates and rng.random() < 0.35:
        old, new = rng.choice(candidates)
        noisy = clean.replace(old, new, 1)
        operations.append(f"TYPO:{old}->{new}")
        return noisy, operations

    if language != "EN":
        spaces = [
            index
            for index, char in enumerate(clean)
            if char == " " and clean[max(0, index - 8) : index + 8].count(".") == 0
        ]
        if spaces:
            index = rng.choice(spaces)
            operations.append(f"SPACE_DELETE:{index}")
            return clean[:index] + clean[index + 1 :], operations

    suffix = rng.choice(("...", "!!", "?!"))
    operations.append(f"EMOTIVE_SUFFIX:{suffix}")
    return clean.rstrip(".!?") + suffix, operations


def render_clause(
    scenario: Scenario,
    profile_id: str,
    occurrence: int,
    rng: random.Random,
    phrase_bank: dict,
) -> tuple[str, str, list[str], list[str]]:
    candidates = _surface_candidates(scenario, profile_id, phrase_bank)
    phrase_index, history = _history(
        scenario,
        occurrence,
        scenario.language,
        len(candidates),
    )
    statement = candidates[phrase_index].strip().rstrip(".!?")
    if scenario.language == "KO_EN_MIXED" and not re.search(r"[A-Za-z]", statement):
        label = scenario["product_family_label"]
        product = (
            "Galaxy 관련 서비스"
            if label in {"COMMERCE", "SERVICE"}
            else label.replace("_", " ").title()
        )
        statement = f"{product}에서 {statement}"
    clean = f"{statement}. {history}"
    if profile_id != "N1_NOISY":
        return clean, clean, [f"PHRASE:{scenario.scenario_id}:{profile_id}:{phrase_index}"], []

    text, operations = _apply_noise(
        clean,
        rng,
        scenario.language,
        scenario["safety_flag"],
    )
    return (
        text,
        clean,
        [f"PHRASE:{scenario.scenario_id}:{profile_id}:{phrase_index}"],
        operations,
    )


def wrap_document(
    clauses: list[str],
    channel: str,
    language: str,
    variant: int,
    safety: bool,
    intent: str,
    symptom: str,
    hard_negative: bool,
) -> tuple[str, str | None]:
    connectors = EN_CONNECTORS if language == "EN" else KO_CONNECTORS
    joined = clauses[0]
    for index, clause in enumerate(clauses[1:], start=1):
        joined += connectors[(variant + index) % len(connectors)] + clause

    sentence = joined if joined.endswith((".", "!", "?")) else joined + "."
    ending = ""
    if not safety:
        if (
            intent in INQUIRY_INTENTS
            and symptom in INQUIRY_SYMPTOMS
        ) or hard_negative:
            endings = EN_INQUIRY_ENDINGS if language == "EN" else KO_INQUIRY_ENDINGS
        elif intent == "PRAISE":
            endings = EN_PRAISE_ENDINGS if language == "EN" else KO_PRAISE_ENDINGS
        elif intent in OPINION_INTENTS:
            endings = EN_OPINION_ENDINGS if language == "EN" else KO_OPINION_ENDINGS
        else:
            endings = EN_ENDINGS if language == "EN" else KO_ENDINGS
        ending = endings[variant % len(endings)]

    title: str | None = None
    if channel == "CALL_CENTER_TRANSCRIPT":
        if language == "EN":
            return (
                f"Customer: {sentence} Agent: I will check the reported issue.",
                None,
            )
        tail = CALL_CENTER_TAILS[variant % len(CALL_CENTER_TAILS)]
        return f"고객: {sentence} {tail}", None
    if channel == "SERVICE_INTAKE":
        prefix = "Reported issue: " if language == "EN" else "접수 내용: "
        return prefix + joined, None
    if channel == "CHAT_SUPPORT":
        prefix = "User: " if language == "EN" else "사용자: "
        return prefix + sentence + ending, None
    if channel == "SNS_POST":
        hashtag = (
            " #Galaxy"
            if language == "EN" and variant % 3 == 0
            else " #갤럭시"
            if language != "EN" and variant % 3 == 0
            else ""
        )
        return sentence + ending + hashtag, None
    if channel in {"ECOMMERCE_REVIEW", "STORE_REVIEW"}:
        title = "사용 후기" if language != "EN" else "Usage review"
        return sentence + ending, title
    if channel == "EMAIL_COMPLAINT":
        title = "제품 사용 중 발생한 증상" if language != "EN" else "Device issue"
        if language == "EN":
            return f"Hello, {sentence}{ending} Thank you.", title
        return f"안녕하세요. {sentence}{ending} 감사합니다.", title
    if channel == "COMMUNITY_POST":
        title = "같은 증상 겪는 분 있나요?" if language != "EN" else "Has anyone seen this?"
        return sentence + ending, title
    return sentence + ending, title
