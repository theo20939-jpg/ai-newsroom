"""KAGE footer custom emoji: configurable, never a send dependency, UTF-16-correct entities."""
from __future__ import annotations

import html
from html.parser import HTMLParser
from uuid import UUID

import pytest
from aiogram.methods import SendPhoto
from aiogram.types import MessageEntity
from aiogram.utils.text_decorations import html_decoration

from bot.keyboards.image_preview import build_editorial_send_keyboard
from core.config import settings
from services.news_telegram_presentation import build_ninja_pulse_footer_html, render_v81_news_card_html

EMOJI_ID = "5368324170671202286"  # Bot API docs example id - NOT the real KAGE emoji
FALLBACK = "🥷"
PLAIN_FOOTER = '<a href="https://t.me/kage_journal">KAGE</a>'
CANARY_TITLE = "На даркнет-маркетплейсах продают доступ к ИИ-моделям со скидками до 97%"
CANARY_BODY = ("Google Threat Intelligence Group обнаружила предложения доступа к моделям "
               "Anthropic, Google и OpenAI.")
CANARY_EVENT = UUID("0c61fab4-90ca-4cf8-a9d8-1e6909a5c027")


def _utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


class _TelegramHtml(HTMLParser):
    """Minimal Telegram-HTML -> (text, entities) parser; offsets in UTF-16 code units, as the
    Bot API measures them. Only the tags this footer/card emit are understood."""

    _TYPES = {"b": "bold", "a": "text_link", "tg-emoji": "custom_emoji", "blockquote": "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text = ""
        self.open: list[tuple[str, int, dict]] = []
        self.entities: list[dict] = []

    def handle_starttag(self, tag, attrs):
        assert tag in self._TYPES, f"unexpected tag {tag}"
        self.open.append((tag, _utf16(self.text), dict(attrs)))

    def handle_endtag(self, tag):
        name, start, attrs = self.open.pop()
        assert name == tag
        entity = {"type": self._TYPES[tag], "offset": start, "length": _utf16(self.text) - start}
        if tag == "a":
            entity["url"] = attrs["href"]
        if tag == "tg-emoji":
            entity["custom_emoji_id"] = attrs["emoji-id"]
        self.entities.append(entity)

    def handle_data(self, data):
        self.text += data


def _parse(markup: str) -> tuple[str, list[dict]]:
    parser = _TelegramHtml()
    parser.feed(markup)
    parser.close()
    assert not parser.open
    return parser.text, sorted(parser.entities, key=lambda e: (e["offset"], -e["length"]))


def _utf16_slice(text: str, offset: int, length: int) -> str:
    raw = text.encode("utf-16-le")
    return raw[offset * 2:(offset + length) * 2].decode("utf-16-le")


@pytest.fixture
def emoji_configured(monkeypatch):
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", EMOJI_ID)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", FALLBACK)


@pytest.fixture
def emoji_absent(monkeypatch):
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", None)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", None)


def _custom_emoji_entities(markup: str) -> list[dict]:
    return [e for e in _parse(markup)[1] if e["type"] == "custom_emoji"]


def test_configured_footer_has_exactly_one_custom_emoji_entity_before_the_kage_link(emoji_configured):
    footer = build_ninja_pulse_footer_html()
    assert footer == f'<tg-emoji emoji-id="{EMOJI_ID}">{FALLBACK}</tg-emoji> {PLAIN_FOOTER}'
    text, entities = _parse(footer)
    assert text == f"{FALLBACK} KAGE"
    assert entities == [
        {"type": "custom_emoji", "offset": 0, "length": 2, "custom_emoji_id": EMOJI_ID},
        {"type": "text_link", "offset": 3, "length": 4, "url": "https://t.me/kage_journal"},
    ]


def test_absent_emoji_keeps_the_exact_plain_footer(emoji_absent):
    assert build_ninja_pulse_footer_html() == PLAIN_FOOTER


@pytest.mark.parametrize("emoji_id,fallback", [
    ("", FALLBACK), ("   ", FALLBACK), ("abc", FALLBACK), ("12 34", FALLBACK), ("12a", FALLBACK),
    ('1"><b>x', FALLBACK), ("1" * 33, FALLBACK), (EMOJI_ID, None), (EMOJI_ID, ""), (EMOJI_ID, "K"),
    (EMOJI_ID, "KAGE"), (EMOJI_ID, "🥷 x"), (EMOJI_ID, "<b>"), (EMOJI_ID, "🥷" * 9),
])
def test_invalid_or_partial_configuration_falls_back_to_plain_footer(monkeypatch, emoji_id, fallback):
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", emoji_id)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", fallback)
    assert build_ninja_pulse_footer_html() == PLAIN_FOOTER


@pytest.mark.parametrize("title,body", [
    (CANARY_TITLE, CANARY_BODY),
    ("Запуск 🚀 и 𝕏: 👨‍👩‍👧 семья", "Текст с астральными символами 😀🧪 и кириллицей & <знаками>."),
])
def test_custom_emoji_entity_offset_is_correct_in_utf16_after_cyrillic_and_astral_text(
    emoji_configured, title, body,
):
    markup = render_v81_news_card_html({"title": title, "main_body": body}, include_ninja_pulse_footer=True)
    text, entities = _parse(markup)
    emoji = _custom_emoji_entities(markup)
    assert len(emoji) == 1
    prefix = text[: text.rindex(f"{FALLBACK} KAGE")]
    assert emoji[0]["offset"] == _utf16(prefix)  # UTF-16 units, not Python code points
    assert _utf16_slice(text, emoji[0]["offset"], emoji[0]["length"]) == FALLBACK
    link = [e for e in entities if e["type"] == "text_link"]
    assert len(link) == 1 and _utf16_slice(text, link[0]["offset"], link[0]["length"]) == "KAGE"
    # aiogram's own UTF-16 entity model renders the same entity set back to the same markup.
    rebuilt = html_decoration.unparse(text, [MessageEntity(**e) for e in entities])
    assert _parse(rebuilt) == (text, entities)


def test_astral_prefix_really_shifts_utf16_offset_relative_to_python_index(emoji_configured):
    markup = render_v81_news_card_html({"title": "𝕏 😀", "main_body": "🚀"}, include_ninja_pulse_footer=True)
    text, _ = _parse(markup)
    offset = _custom_emoji_entities(markup)[0]["offset"]
    prefix = text[: text.rindex(f"{FALLBACK} KAGE")]
    assert offset == _utf16(prefix) == len(prefix) + 3  # three astral characters before the footer


def test_photo_caption_payload_keeps_the_custom_emoji_markup(emoji_configured):
    caption = render_v81_news_card_html({"title": CANARY_TITLE, "main_body": CANARY_BODY},
                                        include_ninja_pulse_footer=True)
    payload = SendPhoto(chat_id=-1004297182444, message_thread_id=2, photo="file-id",
                        caption=caption, parse_mode="HTML").model_dump(exclude_none=True)
    assert payload["caption"] == caption
    assert payload["parse_mode"] == "HTML"
    assert payload["caption"].count(f'<tg-emoji emoji-id="{EMOJI_ID}">') == 1
    assert _utf16(caption) <= 1024


def test_source_and_meme_buttons_are_unaffected_by_the_emoji_setting(monkeypatch):
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", None)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", None)
    plain = build_editorial_send_keyboard("https://example.com/a", CANARY_EVENT).model_dump()
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", EMOJI_ID)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", FALLBACK)
    with_emoji = build_editorial_send_keyboard("https://example.com/a", CANARY_EVENT).model_dump()
    assert plain == with_emoji
    labels = [button["text"] for row in with_emoji["inline_keyboard"] for button in row]
    assert labels == ["🔗 Источник", "😂 Сгенерировать мем"]


def test_no_duplicate_kage_footer(emoji_configured):
    markup = render_v81_news_card_html({"title": CANARY_TITLE, "main_body": CANARY_BODY},
                                       include_ninja_pulse_footer=True)
    assert markup.count("https://t.me/kage_journal") == 1
    assert markup.count("<tg-emoji") == 1
    assert _parse(markup)[0].count("KAGE") == 1


def test_accepted_canary_replay_changes_only_the_footer(monkeypatch):
    card = {"title": CANARY_TITLE, "main_body": CANARY_BODY}
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", None)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", None)
    before = render_v81_news_card_html(card, include_ninja_pulse_footer=True)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_id", EMOJI_ID)
    monkeypatch.setattr(settings, "kage_telegram_custom_emoji_fallback", FALLBACK)
    after = render_v81_news_card_html(card, include_ninja_pulse_footer=True)
    assert before == f"<b>{html.escape(CANARY_TITLE, quote=False)}</b>\n\n{CANARY_BODY}\n\n{PLAIN_FOOTER}"
    assert before.endswith(PLAIN_FOOTER) and after.endswith(PLAIN_FOOTER)
    head = before[: -len(PLAIN_FOOTER)]
    assert after == f'{head}<tg-emoji emoji-id="{EMOJI_ID}">{FALLBACK}</tg-emoji> {PLAIN_FOOTER}'
    assert after.encode("utf-8").startswith(head.encode("utf-8"))  # byte-identical above the footer
